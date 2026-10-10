const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { initialAssign, refine, similarity } = require("./core.js");
const SigCore = require("./sigcore.js");

let passed = 0;
const ok = (name, fn) => { fn(); passed++; console.log("  ok  " + name); };

// 1. JS signature == Python signature (fixture from tools/make_fake_data.py)
const fxPath = path.join(__dirname, "tools", "sig_fixture.json");
if (fs.existsSync(fxPath)) {
  const fx = JSON.parse(fs.readFileSync(fxPath, "utf8"));
  fx.images.forEach((im, k) => ok(`signature matches Python on fixture image ${k}`, () => {
    const rgb = Buffer.from(im.rgb, "base64"), rgba = new Uint8ClampedArray(96 * 96 * 4);
    for (let i = 0; i < 96 * 96; i++) { rgba[i * 4] = rgb[i * 3]; rgba[i * 4 + 1] = rgb[i * 3 + 1]; rgba[i * 4 + 2] = rgb[i * 3 + 2]; rgba[i * 4 + 3] = 255; }
    assert.deepStrictEqual(Array.from(SigCore.signature(rgba, fx.meta)), im.sig);
    assert.deepStrictEqual(Array.from(SigCore.histogram(rgba)), im.hist);
  }));
} else console.log("  skip signature fixture (run python tools/make_fake_data.py first)");

// 2. search: synthetic database
const N = 5000, C = 20, K = 50;
let seed = 12345; const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296;
const sig = Uint8Array.from({ length: N * 128 }, () => (rnd() * 256) | 0);
const labels = Uint16Array.from({ length: N }, () => (rnd() * C) | 0);
const hist = Uint8Array.from({ length: N * 64 }, () => (rnd() * 8) | 0);
const query = i => sig.slice(i * 128, i * 128 + 128);

ok("search returns the image itself when queried with its own signature", () => {
  for (const i of [0, 17, 2500, N - 1]) {
    const r = SigCore.search(sig, labels, N, query(i), K, null, false, C);
    assert.strictEqual(r.idx[0], i); assert.strictEqual(r.d2[0], 0);
    assert.strictEqual(r.idx.length, K);
  }
});
ok("top-K equals a full sort", () => {
  const q = query(123), r = SigCore.search(sig, labels, N, q, K, null, false, C);
  const all = Array.from({ length: N }, (_, i) => { let s = 0; for (let j = 0; j < 128; j++) { const d = sig[i * 128 + j] - q[j]; s += d * d; } return [s, i]; }).sort((a, b) => a[0] - b[0]);
  assert.deepStrictEqual(Array.from(r.d2), all.slice(0, K).map(x => x[0]));
});
ok("re-rank keeps the exact match first", () => {
  const i = 777, r = SigCore.search(sig, labels, N, query(i), K, null, false, C);
  const rows = SigCore.rerank(r.idx, r.d2, hist, hist.slice(i * 64, i * 64 + 64), sig, labels, 13);
  assert.strictEqual(rows.length, 13); assert.strictEqual(rows[0].i, i);
});
ok("diversity mode gives unique classes", () => {
  const r = SigCore.search(sig, labels, N, query(42), K, null, true, C);
  const cls = Array.from(r.idx, i => labels[i]);
  assert.strictEqual(new Set(cls).size, cls.length); assert.strictEqual(cls.length, C);
  assert.strictEqual(r.idx[0], 42);
});
ok("class mask restricts results", () => {
  const meta = { classes: [{ th: "พิซซ่า", en: "pizza", group: 0 }, { th: "ผัดไทย", en: "pad thai", group: 1 }, { th: "ราเมน", en: "Ramen", group: 1 }] };
  const m = SigCore.buildMask(meta, -1, "พิซ"); assert.deepStrictEqual(Array.from(m.mask), [1, 0, 0]);
  assert.deepStrictEqual(Array.from(SigCore.buildMask(meta, 1, "ramen").mask), [0, 0, 1]);
  assert.strictEqual(SigCore.buildMask(meta, 0, "ramen").any, 0);
  const mk = Uint8Array.from({ length: C }, (_, c) => +(c === 3));
  const r = SigCore.search(sig, labels, N, query(5), K, mk, false, C);
  assert.ok(r.idx.every(i => labels[i] === 3));
});

// 3. core permutation validity
ok("core assignment stays a valid permutation and improves", () => {
  const n = 64 * 64, rn = () => Uint8ClampedArray.from({ length: n * 4 }, () => (Math.random() * 256) | 0);
  const src = rn(), tgt = rn(), a = initialAssign(src, tgt, n);
  const perm = arr => new Set(arr).size === n && arr.every(v => v >= 0 && v < n);
  assert.ok(perm(a));
  const before = similarity(src, tgt, a);
  refine(src, tgt, a, n * 50);
  assert.ok(perm(a)); assert.ok(similarity(src, tgt, a) > before);
});

// 3b. real shortlist scoring (64x64, seeded)
ok("scores are deterministic with a seeded RNG and the ranking follows the scores", () => {
  const { matchScore, seededRand } = require("./core.js");
  const n = 64 * 64, mk = f => Uint8ClampedArray.from({ length: n * 4 }, (_, i) => (i % 4 === 3 ? 255 : f(i >> 2)));
  const r = seededRand(5), user = mk(() => (r() * 256) | 0);
  const shuffled = (() => { const o = user.slice(), q = seededRand(9); for (let i = n - 1; i > 0; i--) { const j = (q() * (i + 1)) | 0; for (let c = 0; c < 4; c++) { const t = o[i * 4 + c]; o[i * 4 + c] = o[j * 4 + c]; o[j * 4 + c] = t; } } return o; })();
  const cands = [mk(() => 0), shuffled, mk(i => (i * 7) & 255), mk(() => 255)];
  const run = () => cands.map((c, k) => matchScore(user, c, n, n * 120, 100 + k));
  const a = run(), b = run();
  a.forEach((x, k) => { assert.strictEqual(x.score, b[k].score); assert.deepStrictEqual(Array.from(x.a), Array.from(b[k].a)); });
  const perm = arr => new Set(arr).size === n;
  assert.ok(a.every(x => perm(x.a)));
  const order = a.map((x, k) => [x.score, k]).sort((p, q) => q[0] - p[0]);
  assert.strictEqual(order[0][1], 1, "a rearrangement of the user's own pixels must rank first");
  assert.ok(order[0][0] > 85, "and score high");
  for (let i = 1; i < order.length; i++) assert.ok(order[i - 1][0] >= order[i][0]);
});

// 4. optional: real/fake data on disk (data/ or FAKE_DIR) -> every image finds itself; print timings
const dir = ["data", "fake_data"].map(d => path.join(__dirname, d)).find(d => fs.existsSync(path.join(d, "meta.json")));
if (dir) {
  const meta = JSON.parse(fs.readFileSync(path.join(dir, "meta.json"), "utf8"));
  const S = new Uint8Array(fs.readFileSync(path.join(dir, "sig.bin"))), L = new Uint16Array(new Uint8Array(fs.readFileSync(path.join(dir, "labels.bin"))).buffer);
  const n = meta.count;
  ok(`on-disk ${path.basename(dir)} (${n} images): self-query finds itself`, () => {
    for (let t = 0; t < 20; t++) { const i = Math.floor(t * n / 20), r = SigCore.search(S, L, n, S.slice(i * 128, i * 128 + 128), 50, null, false, meta.classes.length); assert.strictEqual(r.d2[0], 0); }
  });
  const q = S.slice(0, 128); let t0 = performance.now();
  for (let k = 0; k < 20; k++) SigCore.search(S, L, n, q, 50, null, false, meta.classes.length);
  console.log(`  search time over ${n}: ${((performance.now() - t0) / 20).toFixed(2)} ms`);
}

console.log(`\nall ${passed} checks passed`);
