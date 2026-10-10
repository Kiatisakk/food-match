// Pure pixel-rearranging logic. Works in the browser (window.PixelCore) and in Node (require).
// Images are RGBA Uint8ClampedArray of the same size n = width * height.
// An assignment is Int32Array `a` where a[targetIndex] = sourceIndex (a permutation).
(function (root) {
  const lum = (d, i) => 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2];

  // weighted squared color distance between source pixel s and target pixel t
  function cost(src, tgt, s, t) {
    const dr = src[s * 4] - tgt[t * 4], dg = src[s * 4 + 1] - tgt[t * 4 + 1], db = src[s * 4 + 2] - tgt[t * 4 + 2];
    return 2 * dr * dr + 4 * dg * dg + 3 * db * db;
  }

  // Step 1: darkest source pixel goes to darkest target spot, and so on
  function initialAssign(src, tgt, n) {
    const ls = new Float32Array(n), lt = new Float32Array(n);
    for (let i = 0; i < n; i++) { ls[i] = lum(src, i); lt[i] = lum(tgt, i); }
    const s = Int32Array.from({ length: n }, (_, i) => i).sort((a, b) => ls[a] - ls[b]);
    const t = Int32Array.from({ length: n }, (_, i) => i).sort((a, b) => lt[a] - lt[b]);
    const a = new Int32Array(n);
    for (let k = 0; k < n; k++) a[t[k]] = s[k];
    return a;
  }

  // Step 2: try random swaps, keep the ones that make colors match better. Returns swaps kept.
  function refine(src, tgt, a, iters, rand = Math.random) {
    const n = a.length;
    let kept = 0;
    for (let k = 0; k < iters; k++) {
      const i = (rand() * n) | 0, j = (rand() * n) | 0;
      const si = a[i], sj = a[j];
      if (cost(src, tgt, sj, i) + cost(src, tgt, si, j) < cost(src, tgt, si, i) + cost(src, tgt, sj, j)) {
        a[i] = sj; a[j] = si; kept++;
      }
    }
    return kept;
  }

  // 0–100: how close the rearranged picture is to the target
  function similarity(src, tgt, a) {
    let sum = 0;
    for (let t = 0; t < a.length; t++) sum += cost(src, tgt, a[t], t);
    const worst = 9 * 255 * 255;
    return 100 * (1 - Math.sqrt(sum / a.length / worst));
  }

  // small deterministic RNG (mulberry32) so scores can be reproduced
  function seededRand(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = Math.imul(a ^ (a >>> 15), a | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // initialAssign + refine + similarity in one go. Deterministic for a given seed. Returns { a, score }.
  function matchScore(src, tgt, n, iters, seed) {
    const a = initialAssign(src, tgt, n);
    refine(src, tgt, a, iters, seededRand(seed));
    return { a, score: similarity(src, tgt, a) };
  }

  const api = { initialAssign, refine, similarity, cost, seededRand, matchScore };
  if (typeof module !== "undefined") module.exports = api; else root.PixelCore = api;
})(this);
