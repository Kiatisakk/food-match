"""Sanity checks for food-match/data/ (see DATA_FORMAT.md)."""
import io, json, os, random
import numpy as np
import pyarrow.parquet as pq
from PIL import Image

import build_data as b

D = b.DATA
rng = random.Random(1)
meta = json.load(open(os.path.join(D, "meta.json"), encoding="utf-8"))
N = meta["count"]
print("version", meta["version"], "count", N, "shards", meta["shardCount"])

# ---- sizes and label range
sig = np.fromfile(os.path.join(D, "sig.bin"), np.uint8)
lab = np.fromfile(os.path.join(D, "labels.bin"), "<u2")
hist = np.fromfile(os.path.join(D, "hist.bin"), np.uint8)
src = np.fromfile(os.path.join(D, "src.bin"), "<u4")
assert sig.size == N * 128, "sig.bin size"
assert lab.size == N and hist.size == N * 64 and src.size == N, "bin sizes"
assert lab.max() < len(meta["classes"]), "label range"
sig = sig.reshape(N, 128); hist = hist.reshape(N, 64)
print("sizes OK; labels in range")

# ---- re-load tiles from shards, recompute signature/histogram
ds, dh = [], []
for i in rng.sample(range(N), 100):
    k, j = divmod(i, meta["perShard"])
    im = Image.open(os.path.join(D, "thumbs", f"s{k:05d}.jpg")).convert("RGB")
    x, y = (j % 16) * 96, (j // 16) * 96
    t = np.asarray(im.crop((x, y, x + 96, y + 96)))
    ds.append(np.abs(b.signature(t).astype(int) - sig[i]).astype(float))
    dh.append(np.abs(b.histogram(t).astype(int) - hist[i]).astype(float))
ds, dh = np.concatenate(ds), np.concatenate(dh)
print(f"signature diff after JPEG: mean {ds.mean():.3f} max {ds.max():.0f}; "
      f"histogram diff: mean {dh.mean():.3f} max {dh.max():.0f}")

# ---- full/ and thumb/ files
for i in [0, 1, N // 2, N - 1] + rng.sample(range(N), 4):
    f = Image.open(os.path.join(D, "full", f"{i // 1000:02d}", f"{i:05d}.jpg"))
    t = Image.open(os.path.join(D, "thumb", f"{i // 1000:02d}", f"{i:05d}.jpg"))
    assert f.size == (256, 256), (i, f.size)
    assert t.size == (96, 96), (i, t.size)
nf = sum(len(fs) for _, _, fs in os.walk(os.path.join(D, "full")))
nt = sum(len(fs) for _, _, fs in os.walk(os.path.join(D, "thumb")))
assert nf == N and nt == N, (nf, nt)
print(f"full/ ({nf}) 256x256 and thumb/ ({nt}) 96x96 OK")

# ---- src.bin range and match against the raw parquet
ntrain = sum(u[3] for u in b.row_group_units() if os.path.basename(u[0]).startswith("train_"))
nval = sum(u[3] for u in b.row_group_units()) - ntrain
split, row = src >> 31, src & 0x7FFFFFFF
assert ((split == 0) & (row < ntrain) | (split == 1) & (row < nval)).all(), "src.bin out of range"
print("src.bin in range")
files = b.parquet_files()
meds = []
for i in rng.sample(range(N), 5):
    sp, r = int(split[i]), int(row[i])
    gid = r + (ntrain if sp else 0)
    for u in b.row_group_units():
        if u[2] <= gid < u[2] + u[3]:
            break
    rec = pq.ParquetFile(u[0]).read_row_group(u[1]).to_pydict()
    im = Image.open(io.BytesIO(rec["image"][gid - u[2]]["bytes"])).convert("RGB")
    ref = np.asarray(b.center_square(im).resize((256, 256), Image.LANCZOS)).astype(int)
    got = np.asarray(Image.open(os.path.join(D, "full", f"{i // 1000:02d}", f"{i:05d}.jpg")).convert("RGB")).astype(int)
    assert rec["label"][gid - u[2]] == lab[i], "label mismatch"
    meds.append(np.abs(ref - got).mean())
print("src.bin raw-row match: mean abs diff per image", [round(m, 2) for m in meds])
assert max(meds) < 4, "src.bin mismatch"

# ---- class counts
cnt = np.bincount(lab, minlength=len(meta["classes"]))
order = np.argsort(cnt)
print("fewest:", [(meta["classes"][k]["en"], int(cnt[k])) for k in order[:5]])
print("most:  ", [(meta["classes"][k]["en"], int(cnt[k])) for k in order[::-1][:5]])

# ---- coverage: nearest selected signature for non-selected pool images vs random-N baseline
units = b.row_group_units()
parts = [np.load(b.cache_path(u)) for u in units]   # signatures only (no thumbs: saves RAM)
c = {"ids": np.concatenate([p["ids"] for p in parts])}
all_sig = np.concatenate([p["sigs"] for p in parts]).astype(np.float32)
sel_ids = set((np.where(split == 1, row + ntrain, row)).tolist())
is_sel = np.array([int(g) in sel_ids for g in c["ids"]])
nonsel = np.flatnonzero(~is_sel)
qi = np.random.default_rng(2).choice(nonsel, 2000, replace=False)
q = all_sig[qi]
sel_sig = sig.astype(np.float32)
d_sel = np.sqrt(np.maximum(b.min_sqdist_to(q, sel_sig, 250), 0))
# baseline: random N images from everything except the queries (queries excluded)
rest = np.setdiff1d(np.arange(len(all_sig)), qi)
base = all_sig[np.random.default_rng(3).choice(rest, N, replace=False)]
d_base = np.sqrt(np.maximum(b.min_sqdist_to(q, base, 250), 0))
print(f"coverage (NN signature L2 from 2000 non-selected images, lower = better): "
      f"selected mean {d_sel.mean():.1f} p95 {np.percentile(d_sel, 95):.1f} max {d_sel.max():.1f} | "
      f"random-{N} mean {d_base.mean():.1f} p95 {np.percentile(d_base, 95):.1f} max {d_base.max():.1f}")

# ---- total size
tot = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(D) for f in fs)
print(f"data/ total size: {tot/1e6:.0f} MB")
