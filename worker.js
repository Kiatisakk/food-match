// Search worker: loads data/ once, then answers queries (L2 over all signatures, top-K, cheap re-rank).
importScripts("sigcore.js");
let meta, sig, labels, hist, N;
const post = m => postMessage(m);

async function getBuf(url, label, weight) {
  const r = await fetch(url);
  if (!r.ok) { const e = new Error(url + " " + r.status); e.status = r.status; throw e; }
  const total = +r.headers.get("content-length") || 0;
  if (!r.body || !total) return new Uint8Array(await r.arrayBuffer());
  const out = new Uint8Array(total), rd = r.body.getReader();
  let got = 0;
  for (;;) {
    const { done, value } = await rd.read();
    if (done) break;
    out.set(value, got); got += value.length;
    post({ type: "load", label, p: got / total, weight });
  }
  return got === total ? out : out.slice(0, got);
}

async function init(base) {
  try {
    const r = await fetch(base + "meta.json");
    if (!r.ok) { post({ type: "error", code: "nometa" }); return; }
    meta = await r.json(); N = meta.count;
    sig = await getBuf(base + "sig.bin", "ลายเซ็นสี", 1);
    const lb = await getBuf(base + "labels.bin", "ป้ายชื่อ", 0.05);
    labels = new Uint16Array(lb.buffer, lb.byteOffset, N);
    hist = await getBuf(base + "hist.bin", "นับสี", 0.2);
    if (sig.length < N * 128 || hist.length < N * 64) throw new Error("data files are shorter than meta.count");
    post({ type: "ready", meta });
  } catch (err) {
    post({ type: "error", code: "fetch", msg: String(err.message || err) });
  }
}

function query(m) {
  const t0 = performance.now();
  const { mask, any } = SigCore.buildMask(meta, m.group, m.query);
  if (!any) { post({ type: "result", id: m.id, items: [], cand: 0, ms: 0, empty: true }); return; }
  const pool = SigCore.search(sig, labels, N, m.sig, 50, mask, m.mode === "diverse", meta.classes.length);
  const rows = SigCore.rerank(pool.idx, pool.d2, hist, m.hist, sig, labels, 13);
  const ms = performance.now() - t0;
  post({
    type: "result", id: m.id, ms, cand: pool.cand,
    items: rows.map(r => ({ i: r.i, cls: labels[r.i], rms: r.rms, score: r.score, hist: hist.slice(r.i * 64, r.i * 64 + 64) }))
  });
}

onmessage = e => { const m = e.data; if (m.type === "init") init(m.base); else if (m.type === "search") query(m); };
