"""Download Food-101 parquet files (train + validation) from Hugging Face into raw/. Resumable."""
import os, sys, time, requests
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
API = "https://huggingface.co/api/datasets/ethz/food101/parquet"

def main():
    os.makedirs(RAW, exist_ok=True)
    idx = requests.get(API, timeout=60).json()["default"]
    t0 = time.time()
    for split, urls in idx.items():
        for u in urls:
            name = f"{split}_{os.path.basename(u)}"
            dst = os.path.join(RAW, name)
            head = requests.head(u, allow_redirects=True, timeout=60)
            size = int(head.headers.get("content-length", -1))
            if os.path.exists(dst) and size > 0 and os.path.getsize(dst) == size:
                print("skip", name); continue
            tmp = dst + ".part"
            have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
            hdr = {"Range": f"bytes={have}-"} if have else {}
            with requests.get(u, headers=hdr, stream=True, timeout=60) as r:
                if have and r.status_code != 206:
                    have = 0
                r.raise_for_status()
                with open(tmp, "ab" if have else "wb") as f:
                    for c in r.iter_content(1 << 20):
                        f.write(c)
            os.replace(tmp, dst)
            print("done", name, os.path.getsize(dst), f"{time.time()-t0:.0f}s", flush=True)
    print("total seconds", round(time.time() - t0))

if __name__ == "__main__":
    main()
