// Scores candidates for real: rebuild the user's 64x64 crop into each target with PixelCore (seeded, so repeatable).
importScripts("core.js");
onmessage = e => {
  const { src, tgts, ks, iters, seeds } = e.data, s = new Uint8ClampedArray(src), n = 64 * 64;
  tgts.forEach((buf, j) => {
    const r = PixelCore.matchScore(s, new Uint8ClampedArray(buf), n, iters, seeds[j]);
    postMessage({ type: "one", k: ks[j], score: r.score, a: r.a }, [r.a.buffer]);
  });
  postMessage({ type: "done" });
};
