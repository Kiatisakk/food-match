// Signature + search logic shared by the browser (window.SigCore), the Web Worker and Node tests.
// Implements the recipe in DATA_FORMAT.md exactly. Pure functions, no DOM.
(function (root) {
  const SQ2 = Math.sqrt(2), SQ3 = Math.sqrt(3);
  const round = v => Math.floor(v + 0.5); // round half up (the Python side uses np.floor(v + 0.5) too)

  // rgba: 96x96 RGBA array (any length n*4). meta: { dirs, lo, hi, quantiles }. Returns Uint8Array(dirs*quantiles).
  function signature(rgba, meta) {
    const n = rgba.length / 4, Q = meta.quantiles || 16, D = meta.dirs.length;
    const out = new Uint8Array(D * Q), buf = new Float64Array(n);
    const x0 = new Float64Array(n), x1 = new Float64Array(n), x2 = new Float64Array(n);
    for (let i = 0; i < n; i++) { x0[i] = rgba[i * 4] * SQ2; x1[i] = rgba[i * 4 + 1] * 2; x2[i] = rgba[i * 4 + 2] * SQ3; }
    for (let d = 0; d < D; d++) {
      const [d0, d1, d2] = meta.dirs[d], lo = meta.lo[d], span = meta.hi[d] - meta.lo[d];
      for (let i = 0; i < n; i++) {
        const p = x0[i] * d0 + x1[i] * d1 + x2[i] * d2;
        buf[i] = (p - lo) / span * 255;
      }
      buf.sort();
      for (let q = 0; q < Q; q++) {
        const v = round(buf[Math.floor((q + 0.5) / Q * n)]);
        out[d * Q + q] = v < 0 ? 0 : v > 255 ? 255 : v;
      }
    }
    return out;
  }

  // 64-bin colour count: bin = (r>>6)*16 + (g>>6)*4 + (b>>6), value = min(255, round(count / n * 255))
  function histogram(rgba) {
    const n = rgba.length / 4, c = new Uint32Array(64), out = new Uint8Array(64);
    for (let i = 0; i < n; i++) c[(rgba[i * 4] >> 6) * 16 + (rgba[i * 4 + 1] >> 6) * 4 + (rgba[i * 4 + 2] >> 6)]++;
    for (let b = 0; b < 64; b++) out[b] = Math.min(255, round(c[b] / n * 255));
    return out;
  }

  // which classes are allowed: group index (or -1/null for all) + text query (Thai or English, substring)
  function buildMask(meta, group, query) {
    const q = (query || "").trim().toLowerCase().replace(/\s+/g, " ");
    const mask = new Uint8Array(meta.classes.length);
    let any = 0;
    meta.classes.forEach((c, i) => {
      if (group != null && group >= 0 && c.group !== group) return;
      if (q && !(c.th.toLowerCase().includes(q) || c.en.toLowerCase().includes(q))) return;
      mask[i] = 1; any++;
    });
    return { mask, any };
  }

  // squared L2 between query q and signature at offset off, giving up (returns >= limit) once above limit
  function dist2(sig, off, q, limit) {
    let s = 0;
    for (let j = 0; j < 128; j += 16) {
      for (let k = j; k < j + 16; k++) { const d = sig[off + k] - q[k]; s += d * d; }
      if (s >= limit) return s;
    }
    return s;
  }

  // Top-K by signature distance WITHOUT sorting all N. Keeps a small sorted array (insertion), with early abort.
  // diverse: at most one image per class. Returns { idx: Int32Array, d2: Float64Array } sorted ascending.
  function search(sig, labels, N, q, K, mask, diverse, numClasses) {
    let cand = 0;
    if (diverse) {
      const bestD = new Float64Array(numClasses).fill(Infinity), bestI = new Int32Array(numClasses).fill(-1);
      for (let i = 0; i < N; i++) {
        const c = labels[i];
        if (mask && !mask[c]) continue;
        cand++;
        const s = dist2(sig, i * 128, q, bestD[c]);
        if (s < bestD[c]) { bestD[c] = s; bestI[c] = i; }
      }
      const cls = []; for (let c = 0; c < numClasses; c++) if (bestI[c] >= 0) cls.push(c);
      cls.sort((a, b) => bestD[a] - bestD[b]);
      const top = cls.slice(0, K);
      return { idx: Int32Array.from(top, c => bestI[c]), d2: Float64Array.from(top, c => bestD[c]), cand };
    }
    const ti = new Int32Array(K).fill(-1), td = new Float64Array(K).fill(Infinity);
    let worst = Infinity;
    for (let i = 0; i < N; i++) {
      if (mask && !mask[labels[i]]) continue;
      cand++;
      const s = dist2(sig, i * 128, q, worst);
      if (s >= worst) continue;
      let p = K - 1;
      while (p > 0 && td[p - 1] > s) { td[p] = td[p - 1]; ti[p] = ti[p - 1]; p--; }
      td[p] = s; ti[p] = i; worst = td[K - 1];
    }
    let m = 0; while (m < K && ti[m] >= 0) m++;
    return { idx: ti.slice(0, m), d2: td.slice(0, m), cand };
  }

  // Cheap re-rank of the shortlist: signature RMS (0..1) + 0.25 * normalised colour-count L1 difference (0..2).
  // The signature is a sliced approximation, the 64-bin count catches big colour mismatches it blurs.
  function rerank(idx, d2, hist, qhist, sig, labels, keep) {
    let qs = 0; for (let b = 0; b < 64; b++) qs += qhist[b];
    const rows = Array.from(idx, (i, k) => {
      let l1 = 0; for (let b = 0; b < 64; b++) l1 += Math.abs(hist[i * 64 + b] - qhist[b]);
      const rms = Math.sqrt(d2[k] / 128) / 255, hl = l1 / (qs || 1);
      return { i, rms, hl, score: rms + 0.25 * hl };
    });
    rows.sort((a, b) => a.score - b.score);
    return rows.slice(0, keep);
  }

  const api = { signature, histogram, buildMask, search, rerank };
  if (typeof module !== "undefined") module.exports = api; else root.SigCore = api;
})(typeof self !== "undefined" ? self : this);
