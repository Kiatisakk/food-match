"""Generate a small FAKE dataset into data/ that follows DATA_FORMAT.md, for developing the app.
Refuses to run if data/meta.json exists and is not marked "fake": true (never overwrite real data).
Also writes tools/sig_fixture.json (96x96 images + expected signatures) for test.js.
Usage: python tools/make_fake_data.py [count] [--out=dir]   (open the app with ?data=dir/ for a non-default dir)
"""
import base64, json, math, os, random, shutil, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OUT = next((a[6:] for a in sys.argv[1:] if a.startswith("--out=")), "data")  # e.g. --out=fake_data to leave data/ alone
DATA = os.path.join(ROOT, OUT)
N = int(args[0]) if args else 2000
GRID, TILE, PER = 16, 96, 256

DIRS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1), (1, -1, 0), (1, 1, -2), (1, 0, -1), (0, 1, -1)]
DIRS = [tuple(v / math.sqrt(sum(c * c for c in d)) for v in d) for d in DIRS]
W = (math.sqrt(2), 2.0, math.sqrt(3))
LO = [sum(min(0.0, di * wi * 255) for di, wi in zip(d, W)) for d in DIRS]
HI = [sum(max(0.0, di * wi * 255) for di, wi in zip(d, W)) for d in DIRS]

GROUPS = [{"en": "baked", "th": "อบ"}, {"en": "noodles", "th": "เส้น"},
          {"en": "sweets", "th": "ของหวาน"}, {"en": "fresh", "th": "ของสด"}]
# name, thai, group, base palette (3 colours)
CLASSES = [
    ("pizza", "พิซซ่า", 0, [(200, 60, 40), (240, 190, 80), (250, 240, 200)]),
    ("hamburger", "แฮมเบอร์เกอร์", 0, [(150, 90, 40), (90, 160, 50), (220, 170, 90)]),
    ("pad thai", "ผัดไทย", 1, [(230, 150, 60), (250, 220, 150), (120, 160, 60)]),
    ("ramen", "ราเมน", 1, [(240, 210, 150), (140, 70, 40), (250, 250, 240)]),
    ("donuts", "โดนัท", 2, [(240, 120, 170), (150, 90, 50), (250, 235, 200)]),
    ("ice cream", "ไอศกรีม", 2, [(250, 245, 230), (130, 70, 50), (240, 150, 190)]),
    ("green salad", "สลัดผัก", 3, [(60, 150, 60), (200, 50, 50), (230, 220, 150)]),
    ("sushi", "ซูชิ", 3, [(250, 250, 245), (240, 110, 80), (30, 50, 40)]),
]

def signature(rgb):
    """rgb: HxWx3 uint8 (96x96). Exact recipe of DATA_FORMAT.md. Rounding is floor(v+0.5)."""
    a = rgb.reshape(-1, 3).astype(np.float64)
    x0, x1, x2 = a[:, 0] * math.sqrt(2), a[:, 1] * 2.0, a[:, 2] * math.sqrt(3)
    n = len(a)
    out = np.zeros(128, np.uint8)
    for d, (d0, d1, d2) in enumerate(DIRS):
        p = x0 * d0 + x1 * d1 + x2 * d2
        u = np.sort((p - LO[d]) / (HI[d] - LO[d]) * 255)
        for q in range(16):
            out[d * 16 + q] = int(min(255, max(0, math.floor(u[int((q + 0.5) / 16 * n)] + 0.5))))
    return out

def histogram(rgb):
    a = rgb.reshape(-1, 3)
    b = (a[:, 0] >> 6).astype(int) * 16 + (a[:, 1] >> 6).astype(int) * 4 + (a[:, 2] >> 6).astype(int)
    c = np.bincount(b, minlength=64)
    return np.minimum(255, np.floor(c / len(a) * 255 + 0.5)).astype(np.uint8)

def fake_food(cls, rng):
    pal = CLASSES[cls][3]
    jit = lambda c: tuple(max(0, min(255, v + rng.randint(-35, 35))) for v in c)
    p = [jit(c) for c in pal]
    S = 256
    yy, xx = np.mgrid[0:S, 0:S] / S
    t = (xx * rng.uniform(-1, 1) + yy * rng.uniform(-1, 1)) % 1.0
    bg = np.array(p[0])[None, None] * (1 - t[..., None]) + np.array(p[2])[None, None] * t[..., None]
    img = Image.fromarray(bg.astype(np.uint8))
    d = ImageDraw.Draw(img)
    cx, cy, r = S / 2 + rng.randint(-20, 20), S / 2 + rng.randint(-20, 20), rng.randint(70, 115)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=p[1])
    for _ in range(rng.randint(4, 14)):
        x, y, s = rng.randint(30, 226), rng.randint(30, 226), rng.randint(8, 40)
        d.ellipse([x - s, y - s, x + s, y + s], fill=p[rng.randint(0, 2)])
    return img.filter(ImageFilter.GaussianBlur(1.2))

def main():
    mp = os.path.join(DATA, "meta.json")
    if os.path.exists(mp):
        try:
            old = json.load(open(mp, encoding="utf-8"))
        except Exception:
            old = {}
        if old.get("fake") is not True:
            sys.exit("data/meta.json is real data (no \"fake\": true). Refusing to overwrite it.")
        shutil.rmtree(DATA)
    os.makedirs(os.path.join(DATA, "thumbs"))
    rng = random.Random(7)
    sigs, hists, labels = [], [], []
    shards = -(-N // PER)
    counts = [0] * len(CLASSES)
    sheet = None
    for i in range(N):
        if i % PER == 0:
            sheet = Image.new("RGB", (GRID * TILE, GRID * TILE), (0, 0, 0))
        cls = rng.randrange(len(CLASSES))
        counts[cls] += 1
        full = fake_food(cls, rng)
        sub = os.path.join(DATA, "full", "%02d" % (i // 1000))
        os.makedirs(sub, exist_ok=True)
        full.save(os.path.join(sub, "%05d.jpg" % i), quality=92)
        small = full.resize((TILE, TILE), Image.LANCZOS)
        tsub = os.path.join(DATA, "thumb", "%02d" % (i // 1000))
        os.makedirs(tsub, exist_ok=True)
        small.save(os.path.join(tsub, "%05d.jpg" % i), quality=85)
        rgb = np.asarray(small)
        sigs.append(signature(rgb)); hists.append(histogram(rgb)); labels.append(cls)
        j = i % PER
        sheet.paste(small, ((j % GRID) * TILE, (j // GRID) * TILE))
        if j == PER - 1 or i == N - 1:
            sheet.save(os.path.join(DATA, "thumbs", "s%05d.jpg" % (i // PER)), quality=88)
    np.concatenate(sigs).tofile(os.path.join(DATA, "sig.bin"))
    np.concatenate(hists).tofile(os.path.join(DATA, "hist.bin"))
    np.array(labels, dtype="<u2").tofile(os.path.join(DATA, "labels.bin"))
    meta = {
        "version": 2.1, "fake": True, "count": N, "thumb": TILE, "full": 256, "grid": GRID, "perShard": PER,
        "shardCount": shards, "dims": 128, "quantiles": 16,
        "dirs": [list(d) for d in DIRS], "lo": LO, "hi": HI, "groups": GROUPS,
        "classes": [{"en": c[0], "th": c[1], "group": c[2], "count": counts[k]} for k, c in enumerate(CLASSES)],
        "hf": {"repo": "ethz/food101", "files": {"train": ["fake-train.parquet"], "validation": ["fake-val.parquet"]}},
        "sources": [{"name": "FAKE synthetic blobs (tools/make_fake_data.py)", "url": "", "license": "none", "count": N}],
    }
    np.array([(i & 1) << 31 | i for i in range(N)], dtype="<u4").tofile(os.path.join(DATA, "src.bin"))
    json.dump(meta, open(mp, "w", encoding="utf-8"), ensure_ascii=False)

    # fixture: a few 96x96 images (gradients, noise, a fake food) and their expected signatures
    r2 = np.random.RandomState(3)
    imgs = [r2.randint(0, 256, (96, 96, 3), dtype=np.uint8),
            np.asarray(fake_food(2, rng).resize((96, 96), Image.LANCZOS)),
            np.asarray(fake_food(5, rng).resize((96, 96), Image.LANCZOS)),
            np.tile(np.linspace(0, 255, 96).astype(np.uint8)[None, :, None], (96, 1, 3)),
            np.full((96, 96, 3), 128, np.uint8)]
    fx = {"meta": {"dirs": meta["dirs"], "lo": LO, "hi": HI, "quantiles": 16},
          "images": [{"rgb": base64.b64encode(im.tobytes()).decode(), "sig": signature(im).tolist(),
                      "hist": histogram(im).tolist()} for im in imgs]}
    json.dump(fx, open(os.path.join(ROOT, "tools", "sig_fixture.json"), "w"))
    print("fake dataset: %d images, %d shards, %d classes -> %s" % (N, shards, len(CLASSES), DATA))

main()
