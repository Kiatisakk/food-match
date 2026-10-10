"""Build food-match/data/ from the Food-101 parquet files in raw/ (see DATA_FORMAT.md).

Stage 1  decode every image, centre-crop, compute 96px tile / signature / histogram / sharpness
         (cached per parquet row group in cache/, so later stages can be re-run without decoding)
Stage 2  filter (blurry, near-duplicate) and select N images (per-class minimum + farthest-point fill)
Stage 3  write data/ : meta.json, sig.bin, labels.bin, hist.bin, thumbs shards, full/ images
"""
import glob, hashlib, io, json, os, sys, time
from multiprocessing import Pool
import numpy as np
import pyarrow.parquet as pq
from PIL import Image

from classes_info import CLASSES, GROUPS

# ---------------------------------------------------------------- settings
N = 50_000                 # images to select
MIN_PER_CLASS = 150        # guaranteed per class (colour-diverse picks)
BLUR_DROP = 0.15           # fraction of blurriest images dropped
MIN_SHORT_SIDE = 256       # smaller source images are skipped
BLANK_STD = 6.0            # grayscale std below this = near blank

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
CACHE = os.path.join(HERE, "cache")
DATA = os.path.join(HERE, "data")
THUMB, FULL, GRID, PER_SHARD = 96, 256, 16, 256
QUANT = 16

# ---------------------------------------------------------------- signature recipe (DATA_FORMAT.md)
W = np.array([np.sqrt(2.0), 2.0, np.sqrt(3.0)])
_DIRS_RAW = np.array([(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1),
                      (1, -1, 0), (1, 1, -2), (1, 0, -1), (0, 1, -1)], dtype=np.float64)
DIRS = _DIRS_RAW / np.linalg.norm(_DIRS_RAW, axis=1, keepdims=True)
_dw = DIRS * W * 255.0
LO = np.where(_dw < 0, _dw, 0).sum(axis=1)
HI = np.where(_dw > 0, _dw, 0).sum(axis=1)
_QIDX = np.floor((np.arange(QUANT) + 0.5) / QUANT * (THUMB * THUMB)).astype(int)


def signature(rgb96):
    """rgb96: (96,96,3) uint8 -> (128,) uint8."""
    x = rgb96.reshape(-1, 3).astype(np.float64) * W
    p = x @ DIRS.T                                   # (9216, 8)
    u = (p - LO) / (HI - LO) * 255.0
    u.sort(axis=0)
    q = u[_QIDX]                                     # (16, 8)
    return np.clip(np.floor(q.T + 0.5), 0, 255).astype(np.uint8).reshape(-1)  # index d*16+q


def histogram(rgb96):
    """64-bin colour histogram, 4 levels per channel -> (64,) uint8."""
    a = rgb96.reshape(-1, 3).astype(np.int32)
    b = (a[:, 0] >> 6) * 16 + (a[:, 1] >> 6) * 4 + (a[:, 2] >> 6)
    c = np.bincount(b, minlength=64)
    return np.clip(np.floor(c / (THUMB * THUMB) * 255 + 0.5), 0, 255).astype(np.uint8)


def sharpness(rgb256):
    """Variance of the Laplacian of the grayscale 256px crop."""
    g = np.asarray(Image.fromarray(rgb256).convert("L"), dtype=np.float32)
    lap = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    return float(lap.var())


def center_square(im):
    w, h = im.size
    s = min(w, h)
    l, t = (w - s) // 2, (h - s) // 2
    return im.crop((l, t, l + s, t + s))


# ---------------------------------------------------------------- parquet bookkeeping
def parquet_files():
    # train_0..7 then validation_0..2, numeric order -> stable global ids
    def key(p):
        s, n = os.path.basename(p)[:-8].split("_")
        return (0 if s == "train" else 1, int(n))
    return sorted(glob.glob(os.path.join(RAW, "*.parquet")), key=key)


def row_group_units():
    """[(file, rg, first_global_id, nrows)] in global id order."""
    units, gid = [], 0
    for f in parquet_files():
        md = pq.ParquetFile(f).metadata
        for rg in range(md.num_row_groups):
            n = md.row_group(rg).num_rows
            units.append((f, rg, gid, n))
            gid += n
    return units


def class_names():
    f = pq.ParquetFile(parquet_files()[0])
    meta = json.loads(f.schema_arrow.metadata[b"huggingface"])
    return meta["info"]["features"]["label"]["names"]


# ---------------------------------------------------------------- stage 1
def cache_path(unit):
    return os.path.join(CACHE, f"{os.path.basename(unit[0])[:-8]}_{unit[1]:03d}.npz")


def process_unit(unit):
    path = cache_path(unit)
    if os.path.exists(path):
        return 0
    f, rg, gid0, n = unit
    t = pq.ParquetFile(f).read_row_group(rg).to_pydict()
    ids, labels, thumbs, sigs, hists, sharps, shorts = [], [], [], [], [], [], []
    for i in range(n):
        try:
            im = Image.open(io.BytesIO(t["image"][i]["bytes"]))
            im.load()
            im = im.convert("RGB")
            short = min(im.size)
            if short < MIN_SHORT_SIDE:
                continue
            sq = center_square(im)
            t96 = np.asarray(sq.resize((THUMB, THUMB), Image.LANCZOS))
            if np.asarray(Image.fromarray(t96).convert("L")).std() < BLANK_STD:
                continue
            s256 = np.asarray(sq.resize((FULL, FULL), Image.LANCZOS))
        except Exception:
            continue
        ids.append(gid0 + i); labels.append(t["label"][i])
        thumbs.append(t96); sigs.append(signature(t96)); hists.append(histogram(t96))
        sharps.append(sharpness(s256)); shorts.append(short)
    out = dict(
        ids=np.array(ids, dtype=np.int32), labels=np.array(labels, dtype=np.uint16),
        thumbs=np.array(thumbs, dtype=np.uint8).reshape(-1, THUMB, THUMB, 3),
        sigs=np.array(sigs, dtype=np.uint8).reshape(-1, 128),
        hists=np.array(hists, dtype=np.uint8).reshape(-1, 64),
        sharp=np.array(sharps, dtype=np.float32), short=np.array(shorts, dtype=np.int32))
    np.savez(path + ".tmp.npz", **out)
    os.replace(path + ".tmp.npz", path)
    return n


def stage1(units, procs):
    os.makedirs(CACHE, exist_ok=True)
    todo = [u for u in units if not os.path.exists(cache_path(u))]
    print(f"[stage1] {len(units)} row groups, {len(todo)} to decode", flush=True)
    t0, done = time.time(), 0
    with Pool(procs) as pool:
        for n in pool.imap_unordered(process_unit, todo):
            done += 1
            if done % 20 == 0 or done == len(todo):
                print(f"  {done}/{len(todo)} row groups  {time.time()-t0:.0f}s", flush=True)
    return sum(u[3] for u in units)


def _resig(tiles):
    return (np.array([signature(t) for t in tiles]), np.array([histogram(t) for t in tiles]))


def load_cache(units):
    parts = [np.load(cache_path(u)) for u in units]
    c = {k: np.concatenate([p[k] for p in parts])
         for k in ["ids", "labels", "thumbs", "sigs", "hists", "sharp", "short"]}
    # Signature/histogram are always recomputed from the cached 96px tiles (cheap, ~1 min), so a
    # change to the rounding rule never needs a re-decode of the originals.
    chunks = np.array_split(np.arange(len(c["ids"])), 64)
    with Pool(max(1, (os.cpu_count() or 4) - 1)) as pool:
        res = pool.map(_resig, [c["thumbs"][ix] for ix in chunks])
    c["sigs"] = np.concatenate([r[0] for r in res]).astype(np.uint8)
    c["hists"] = np.concatenate([r[1] for r in res]).astype(np.uint8)
    return c


# ---------------------------------------------------------------- stage 2
def fps(X, k, first):
    """Greedy farthest-point sampling of k rows of X (float32), starting at row `first`."""
    xn = (X * X).sum(1)
    mind = np.full(len(X), np.inf, np.float32)
    picked, cur = [], first
    for _ in range(k):
        picked.append(cur)
        d = xn - 2 * (X @ X[cur]) + xn[cur]
        np.minimum(mind, d, out=mind)
        mind[cur] = -1.0
        cur = int(np.argmax(mind))
    return np.array(picked)


def min_sqdist_to(X, S, chunk=4096):
    """For each row of X: squared distance to the nearest row of S (float32)."""
    sn = (S * S).sum(1)
    out = np.empty(len(X), np.float32)
    for a in range(0, len(X), chunk):
        x = X[a:a + chunk]
        d = (x * x).sum(1)[:, None] - 2 * x @ S.T + sn[None, :]
        out[a:a + chunk] = d.min(1)
    return out


def select(c):
    n0 = len(c["ids"])
    keep = np.ones(n0, bool)
    # (a) drop the blurriest 15%
    thr = np.quantile(c["sharp"], BLUR_DROP)
    keep &= c["sharp"] > thr
    n_blur = n0 - int(keep.sum())
    # (a) exact duplicates: identical signature or identical 96px tile (first id wins)
    seen_s, seen_t, dup = set(), set(), 0
    for i in np.flatnonzero(keep):
        ks = c["sigs"][i].tobytes()
        kt = hashlib.md5(c["thumbs"][i].tobytes()).digest()
        if ks in seen_s or kt in seen_t:
            keep[i] = False; dup += 1
            continue
        seen_s.add(ks); seen_t.add(kt)
    pool = np.flatnonzero(keep)
    print(f"[stage2] decoded-ok {n0}, blur-dropped {n_blur}, duplicates {dup}, pool {len(pool)}", flush=True)
    X = c["sigs"][pool].astype(np.float32)
    X -= X.mean(0)
    lab = c["labels"][pool]
    # (b) per-class colour-diverse picks
    chosen = np.zeros(len(pool), bool)
    for k in range(len(CLASSES)):
        idx = np.flatnonzero(lab == k)
        if len(idx) == 0:
            continue
        Xc = X[idx]
        start = int(np.argmin(((Xc - Xc.mean(0)) ** 2).sum(1)))   # most typical image first
        pk = fps(Xc, min(MIN_PER_CLASS, len(idx)), start)
        chosen[idx[pk]] = True
    print(f"  per-class minimum picks: {int(chosen.sum())}", flush=True)
    # (c) global farthest-point fill, seeded with the per-class picks
    t0 = time.time()
    seeds = np.flatnonzero(chosen)
    mind = min_sqdist_to(X, X[seeds])
    mind[seeds] = -1.0
    need = N - len(seeds)
    xn = (X * X).sum(1)
    for it in range(need):
        cur = int(np.argmax(mind))
        chosen[cur] = True
        d = xn - 2 * (X @ X[cur]) + xn[cur]
        np.minimum(mind, d, out=mind)
        mind[cur] = -1.0
        if (it + 1) % 5000 == 0:
            print(f"  fps {it+1}/{need}  {time.time()-t0:.0f}s", flush=True)
    sel = pool[chosen]                                      # indices into the cache arrays
    order = np.lexsort((c["ids"][sel], c["labels"][sel]))   # class, then original id
    return sel[order], dict(decoded_ok=n0, blur=n_blur, dup=dup, pool=len(pool))


# ---------------------------------------------------------------- stage 3
def write_shard(args):
    k, tiles = args
    img = Image.new("RGB", (GRID * THUMB, GRID * THUMB))
    for j, t in enumerate(tiles):
        tile = Image.fromarray(t)
        img.paste(tile, ((j % GRID) * THUMB, (j // GRID) * THUMB))
        oi = k * PER_SHARD + j                      # v2.1: per-image 96px JPEG (q85)
        d = os.path.join(DATA, "thumb", f"{oi // 1000:02d}")
        os.makedirs(d, exist_ok=True)
        tile.save(os.path.join(d, f"{oi:05d}.jpg"), quality=85)
    img.save(os.path.join(DATA, "thumbs", f"s{k:05d}.jpg"), quality=88)


def write_full(args):
    """args: (file, rg, [(row_in_group, output_index), ...])"""
    f, rg, items = args
    t = pq.ParquetFile(f).read_row_group(rg, columns=["image"]).to_pydict()["image"]
    for row, oi in items:
        im = Image.open(io.BytesIO(t[row]["bytes"])).convert("RGB")
        im = center_square(im).resize((FULL, FULL), Image.LANCZOS)
        d = os.path.join(DATA, "full", f"{oi // 1000:02d}")
        os.makedirs(d, exist_ok=True)
        im.save(os.path.join(d, f"{oi:05d}.jpg"), quality=92)
    return len(items)


def stage3(c, sel, units, procs):
    n = len(sel)
    for d in ("thumbs", "thumb", "full"):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    c_sig, c_lab, c_hist = c["sigs"][sel], c["labels"][sel], c["hists"][sel]
    c_sig.tofile(os.path.join(DATA, "sig.bin"))
    c_lab.astype("<u2").tofile(os.path.join(DATA, "labels.bin"))
    c_hist.tofile(os.path.join(DATA, "hist.bin"))
    shards = [(k, c["thumbs"][sel[k * PER_SHARD:(k + 1) * PER_SHARD]])
              for k in range((n + PER_SHARD - 1) // PER_SHARD)]
    # v2.1 src.bin: global id = train rows then validation rows, so split/row are exact
    ntrain = sum(u[3] for u in units if os.path.basename(u[0]).startswith("train_"))
    g = c["ids"][sel].astype(np.int64)
    src = np.where(g >= ntrain, (1 << 31) | (g - ntrain), g).astype("<u4")
    src.tofile(os.path.join(DATA, "src.bin"))
    hf_files = {"train": [], "validation": []}
    for f in parquet_files():
        sp, num = os.path.basename(f)[:-8].split("_")
        hf_files[sp].append(f"default/{sp}/{num}.parquet")
    names = class_names()
    counts = np.bincount(c_lab, minlength=len(names))
    classes = [dict(en=nm.replace("_", " "), th=CLASSES[nm][0], group=CLASSES[nm][1], count=int(counts[i]))
               for i, nm in enumerate(names)]
    meta = dict(version=2.1, count=n, thumb=THUMB, full=FULL, grid=GRID, perShard=PER_SHARD,
                shardCount=len(shards), dims=128, quantiles=QUANT,
                dirs=DIRS.tolist(), lo=LO.tolist(), hi=HI.tolist(),
                groups=[dict(en=e, th=t) for e, t in GROUPS], classes=classes,
                sources=[dict(name="Food-101", url="https://data.vision.ee.ethz.ch/cvl/datasets_extra/food-101/",
                              license="research use only (images from foodspotting.com, see dataset page)",
                              count=n)],
                hf=dict(repo="ethz/food101", files=hf_files))
    with open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"[stage3] writing {len(shards)} thumb shards", flush=True)
    with Pool(procs) as pool:
        list(pool.imap_unordered(write_shard, shards))
        # full images: group the selected originals by parquet row group
        starts = np.array([u[2] for u in units])
        gids = c["ids"][sel]
        ui = np.searchsorted(starts, gids, side="right") - 1
        jobs = {}
        for oi, (g, u) in enumerate(zip(gids, ui)):
            jobs.setdefault(int(u), []).append((int(g - starts[u]), oi))
        args = [(units[u][0], units[u][1], items) for u, items in jobs.items()]
        done, t0 = 0, time.time()
        for m in pool.imap_unordered(write_full, args):
            done += m
            if done % 5000 < m:
                print(f"  full {done}/{n}  {time.time()-t0:.0f}s", flush=True)


def main():
    t0 = time.time()
    procs = max(1, (os.cpu_count() or 4) - 1)
    units = row_group_units()
    total = stage1(units, procs)
    c = load_cache(units)
    sel, stats = select(c)
    stage3(c, sel, units, procs)
    print(f"[done] source images {total}, decoded ok {stats['decoded_ok']}, pool {stats['pool']}, "
          f"selected {len(sel)}, {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
