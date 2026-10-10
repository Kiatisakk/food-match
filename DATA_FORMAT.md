# Data contract (shared by build_data.py and the web app)

Everything the app needs lives in `data/`. Image i (0-based, 0..N-1, N ≈ 50,000) is the same image in every file.
Source: Food-101 (101 classes, 101,000 photos), filtered and selected down to N by build_data.py.

## Color signature: why search is fast
"Can photo X be built from my pixels?" is the optimal-transport (earth mover's) distance between the two
color distributions. For every food photo we precompute a 128-byte signature that approximates it (sliced
Wasserstein): project every pixel's color onto 8 fixed directions and keep 16 quantiles per direction
(= a cumulative color count along that axis). Search = L2 distance between 128-byte vectors.

### Exact recipe (both sides MUST do the same thing)
1. Square crop (center crop for food photos; the user's chosen crop in the app), resize to 96x96
   (Pillow LANCZOS / canvas drawImage with imageSmoothingQuality "high"). Colors r,g,b in 0..255.
   Food photos: compute it from the same 96x96 image that is stored in the thumbs shard (decode it again after JPEG
   encoding is NOT required; compute from the in-memory 96x96 RGB).
2. Weighted color: x = (r*sqrt(2), g*2, b*sqrt(3))   (matches the 2,4,3 cost in core.js).
3. For each direction d (unit 3-vectors, meta.json `dirs`), p = dot(x, d).
   u = (p - lo[d]) / (hi[d] - lo[d]) * 255, where lo[d] = sum of negative parts of (d * w * 255) and
   hi[d] = sum of positive parts, w = (sqrt2, 2, sqrt3). lo/hi are stored in meta.json.
4. Sort the 9216 values u; quantile q (0..15) = sorted[floor((q + 0.5) / 16 * 9216)].
5. Round to uint8. Byte index within the signature = d * 16 + q.

Directions (normalise each to unit length), in this order:
(1,0,0) (0,1,0) (0,0,1) (1,1,1) (1,-1,0) (1,1,-2) (1,0,-1) (0,1,-1)

## Files
- `data/meta.json`
  ```json
  {
    "version": 2, "count": N, "thumb": 96, "full": 256, "grid": 16, "perShard": 256, "shardCount": S,
    "dims": 128, "quantiles": 16,
    "dirs": [[x,y,z], ...8], "lo": [...8], "hi": [...8],
    "groups":  [{"en": "noodles", "th": "เส้น"}, ...],
    "classes": [{"en": "pad thai", "th": "ผัดไทย", "group": 0, "count": 512}, ...],
    "sources": [{"name": "Food-101", "url": "...", "license": "...", "count": N}]
  }
  ```
- `data/sig.bin`    N*128 uint8, image i at offset i*128.
- `data/labels.bin` N uint16 little-endian, index into meta.classes.
- `data/hist.bin`   N*64 uint8 color count, 4 levels per channel: bin = (r>>6)*16 + (g>>6)*4 + (b>>6),
                    value = min(255, round(count / 9216 * 255)), from the same 96x96 image.
- `data/thumbs/s00000.jpg` ... shard k holds images k*256 .. k*256+255 as a 16x16 grid of 96x96 tiles
  (1536x1536 JPEG, quality 88), row-major: tile j at x = (j % 16) * 96, y = floor(j / 16) * 96.
  Last shard may be partial (unused tiles black).
- `data/full/00/00000.jpg` ... 256x256 center crop of image i, JPEG quality 92, folder = floor(i / 1000)
  as 2 digits, file = i as 5 digits. e.g. image 12345 -> data/full/12/12345.jpg

## Added in v2.1 (both agents: please implement)
- `data/thumb/00/00000.jpg` ... the 96x96 tile of image i as its own JPEG (quality 85), same folder/file naming
  as full/ (folder = floor(i / 1000) as 2 digits, file = i as 5 digits). The app loads THESE for the results
  grid and the 96px result (≈4 KB each, so one search fetches ~50 KB instead of up to 13 shards). The thumbs/
  shards stay (verify_data.py and any "browse all" view can use them).
- `data/src.bin` N uint32 little-endian: where image i came from in the Hugging Face `ethz/food101` parquet
  data, = (split << 31) | row, split 0 = train, 1 = validation, row = 0-based row index within that split in
  the order of the HF parquet files (sorted by file name). Lets a future deploy fetch the original from HF
  instead of hosting images. meta.json gains "version": 2.1 and "hf": {"repo": "ethz/food101",
  "files": {"train": [...parquet file names in order], "validation": [...]}}.
