// Heavy part off the main thread: initialAssign + refine (PixelCore). Posts progress, then the permutation.
importScripts("core.js");
onmessage = e => {
  const { src, tgt, n, iters } = e.data;
  const s = new Uint8ClampedArray(src), t = new Uint8ClampedArray(tgt);
  const a = PixelCore.initialAssign(s, t, n);
  postMessage({ type: "progress", p: 0 });
  const chunk = Math.max(200000, Math.ceil(iters / 20));
  let done = 0, last = 0;
  while (done < iters) {
    const k = Math.min(chunk, iters - done);
    PixelCore.refine(s, t, a, k);
    done += k;
    if (performance.now() - last > 80) { last = performance.now(); postMessage({ type: "progress", p: done / iters }); }
  }
  const score = PixelCore.similarity(s, t, a);
  postMessage({ type: "done", a, score }, [a.buffer]);
};
