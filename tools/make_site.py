"""Build site/: a static copy of the app for hosting (GitHub Pages).

The app needs photos for two roles (see "where photos come from" in app.js):
  thumb  results grid + real 64px scoring of all 13 candidates  -> 13+ requests per search
  full   the chosen dish: original photo + sharp result         -> 1 request per choice

Presets decide where each role's photos come from:
  fallback (default) like hybrid, plus a hosted --full-size copy of every photo that the app switches to when
                    Hugging Face fails (rate limit, outage). Best of both; ~590 MB.
  hybrid            thumb = our own small JPEGs on the site, full = Food-101 original from Hugging Face.
                    One Hugging Face API call per choice instead of 13, so its rate limit is out of reach.
                    Adds ~100 MB of 64px thumbnails.
  pages             thumb and full both hosted on the site. No Hugging Face at all, but the result is capped at
                    --full-size (default 192) to keep the site under GitHub Pages' 1 GB limit.
  hf                no photos on the site at all; everything from Hugging Face (13 API calls per search).

    python tools/make_site.py                         # fallback (hybrid + hosted backup)
    python tools/make_site.py --preset hybrid         # smallest site that avoids the HF rate limit
    python tools/make_site.py --preset pages          # everything on GitHub Pages
    python tools/make_site.py --preset pages --full-size 160 --quality 80
    npx --yes serve site                              # try it locally
"""
import argparse, io, json, os, shutil
from multiprocessing import Pool
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, SITE = os.path.join(HERE, "data"), os.path.join(HERE, "site")
APP_FILES = ["index.html", "style.css", "app.js", "worker.js", "score-worker.js", "assign-worker.js",
             "sigcore.js", "core.js"]
DATA_FILES = ["sig.bin", "hist.bin", "labels.bin", "src.bin"]
PAGES_LIMIT = 1_000_000_000  # GitHub Pages: published site size limit

def rel(i):
    return os.path.join(f"{i // 1000:02d}", f"{i:05d}.jpg")

def shrink(job):
    """Resize data/full/<i>.jpg (256px) to `size` and write it as a site JPEG; returns bytes written."""
    i, role, size, quality = job
    out = os.path.join(SITE, "data", role, rel(i))
    im = Image.open(os.path.join(DATA, "full", rel(i))).convert("RGB")
    if size != im.width:
        im = im.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=False)
    with open(out, "wb") as f:
        f.write(buf.getbuffer())
    return buf.tell()

def write_role(role, n, size, quality):
    for d in range((n - 1) // 1000 + 1):
        os.makedirs(os.path.join(SITE, "data", role, f"{d:02d}"), exist_ok=True)
    with Pool() as pool:
        total = sum(pool.imap_unordered(shrink, [(i, role, size, quality) for i in range(n)], chunksize=256))
    print(f"  {role}/: {n:,} photos at {size}px, {total / 1e6:.0f} MB")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=["fallback", "hybrid", "pages", "hf"], default="fallback")
    ap.add_argument("--thumb-size", type=int, default=64, help="hosted thumbnail size (scoring runs at 64)")
    ap.add_argument("--full-size", type=int, default=192, help="hosted full size for pages/fallback (<= 256)")
    ap.add_argument("--quality", type=int, default=82, help="JPEG quality of hosted photos")
    a = ap.parse_args()

    meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
    if meta.get("fake") or "hf" not in meta:
        raise SystemExit("data/ must be the real Food-101 build (with src.bin and meta.hf), not fake data")
    if a.full_size > meta["full"] or a.thumb_size > meta["full"]:
        raise SystemExit(f"sizes must be <= {meta['full']} (the size of data/full)")

    shutil.rmtree(SITE, ignore_errors=True)
    os.makedirs(os.path.join(SITE, "data"))
    for f in APP_FILES:
        shutil.copy2(os.path.join(HERE, f), SITE)
    for f in DATA_FILES:
        shutil.copy2(os.path.join(DATA, f), os.path.join(SITE, "data"))

    n = meta["count"]
    images = {"thumb": {"src": "hf"}, "full": {"src": "hf"}}
    print(f"preset {a.preset}:")
    if a.preset in ("fallback", "hybrid", "pages"):
        write_role("thumb", n, a.thumb_size, a.quality)
        images["thumb"] = {"src": "local", "size": a.thumb_size}
    if a.preset in ("pages", "fallback"):
        write_role("full", n, a.full_size, a.quality)
        images["full"] = {"src": "local", "size": a.full_size}
    if a.preset == "fallback":
        images["full"] = {"src": "hf", "fallback": {"src": "local", "size": a.full_size}}
    meta["images"] = images
    json.dump(meta, open(os.path.join(SITE, "data", "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(SITE, ".nojekyll"), "w").close()  # serve files as-is on GitHub Pages
    # empty .gitignore: gh-pages commits from a clone of this repo, whose .gitignore would drop data/
    open(os.path.join(SITE, ".gitignore"), "w").close()

    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(SITE) for f in fs)
    print(f"site/ ready: {size / 1e6:.0f} MB, {n:,} photos indexed, images = {json.dumps(images)}")
    if size > PAGES_LIMIT:
        print("WARNING: larger than GitHub Pages' 1 GB limit; lower --full-size / --quality")

if __name__ == "__main__":
    main()
