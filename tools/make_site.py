"""Build site/: a static copy of the app for hosting (e.g. GitHub Pages) that hosts NO food images.

The site carries only the code and the small search files (~10 MB: signatures, colour counts, labels,
source rows). Photos are fetched at run time from the Hugging Face dataset viewer (meta.images = "hf"),
using src.bin to map each result to its row in ethz/food101.

    python tools/make_site.py            # needs a built data/ (python build_data.py)
    npx --yes serve site                 # try it locally
"""
import json, os, shutil

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, SITE = os.path.join(HERE, "data"), os.path.join(HERE, "site")
APP_FILES = ["index.html", "style.css", "app.js", "worker.js", "score-worker.js", "assign-worker.js",
             "sigcore.js", "core.js"]
DATA_FILES = ["sig.bin", "hist.bin", "labels.bin", "src.bin"]

meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
if meta.get("fake") or "hf" not in meta:
    raise SystemExit("data/ must be the real Food-101 build (with src.bin and meta.hf), not fake data")

shutil.rmtree(SITE, ignore_errors=True)
os.makedirs(os.path.join(SITE, "data"))
for f in APP_FILES:
    shutil.copy2(os.path.join(HERE, f), SITE)
for f in DATA_FILES:
    shutil.copy2(os.path.join(DATA, f), os.path.join(SITE, "data"))
meta["images"] = "hf"
json.dump(meta, open(os.path.join(SITE, "data", "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
open(os.path.join(SITE, ".nojekyll"), "w").close()  # serve files as-is on GitHub Pages
# empty .gitignore: gh-pages commits from a clone of this repo, whose .gitignore would drop data/
open(os.path.join(SITE, ".gitignore"), "w").close()

size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(SITE) for f in fs)
print(f"site/ ready: {size / 1e6:.1f} MB, {meta['count']:,} photos indexed, images from huggingface.co/datasets/{meta['hf']['repo']}")
