const $ = id => document.getElementById(id);
const DATA = (new URLSearchParams(location.search).get("data") || "data").replace(/\/?$/, "/");
const EFFORT = 450; // swap tries per pixel: ~2.5 s at 256x256 on a normal laptop

// All image URLs live here, so a deploy can point them at another host.
const pad = (i, n) => String(i).padStart(n, "0");
const thumbUrl = i => `${DATA}thumb/${pad(Math.floor(i / 1000), 2)}/${pad(i, 5)}.jpg`;
const fullUrl = i => `${DATA}full/${pad(Math.floor(i / 1000), 2)}/${pad(i, 5)}.jpg`;

let meta = null, ready = null;
let img = null;                 // user's picture (canvas, <= 1024px)
let crop = { x: 0, y: 0, s: 1 }; // in img pixels
let items = [], sel = 0;         // 13 re-ranked results
let qid = 0, qhist = null;
let assignWorker = null, last = null; // last = { N, src, a, final } (full-res result)

const searchWorker = new Worker("worker.js");

// ---------- loading ----------
function showNotice(html) { $("notice").innerHTML = html; $("notice").hidden = false; $("loading").hidden = true; }
const weights = {};
searchWorker.onmessage = e => {
  const m = e.data;
  if (m.type === "load") {
    weights[m.label] = m.p * m.weight;
    const tot = Object.values(weights).reduce((a, b) => a + b, 0) / 1.25;
    $("barFill").style.width = Math.min(100, tot * 100) + "%";
    $("loadText").textContent = `กำลังโหลด${m.label}… ${Math.round(m.p * 100)}%`;
  } else if (m.type === "error") {
    if (m.code === "nometa") showNotice("ยังไม่มีข้อมูลอาหาร ให้รัน <code>python build_data.py</code> ก่อน แล้วค่อยเปิดหน้านี้ใหม่");
    else showNotice(`โหลดข้อมูลไม่ได้ (${m.msg}) ลองเปิดผ่าน <code>npm start</code> ไม่ใช่เปิดไฟล์ตรง ๆ`);
    ready.fail();
  } else if (m.type === "ready") {
    meta = m.meta; ready.ok();
  } else if (m.type === "result") onResult(m);
};
ready = (() => { const o = {}; o.p = new Promise((ok, fail) => { o.ok = ok; o.fail = fail; }); return o; })();
ready.p.catch(() => {});
searchWorker.postMessage({ type: "init", base: DATA });
ready.p.then(() => {
  $("loading").hidden = true; $("start").hidden = !!img;
  const g = $("group");
  g.innerHTML = `<option value="-1">ทุกหมวด</option>` + meta.groups.map((x, i) => `<option value="${i}">${x.th} (${x.en})</option>`).join("");
  $("counter").textContent = `พร้อมค้น ${meta.count.toLocaleString("th-TH")} รูป`;
  if (img) search();
}).catch(() => {});

// ---------- image intake + cropper ----------
function readFile(f) {
  if (!f || !f.type.startsWith("image/")) { alert("ไฟล์นี้ไม่ใช่รูป"); return; }
  const im = new Image();
  im.onload = () => {
    const c = document.createElement("canvas");
    const s = Math.min(1, 1024 / Math.max(im.width, im.height));
    c.width = Math.round(im.width * s); c.height = Math.round(im.height * s);
    c.getContext("2d").drawImage(im, 0, 0, c.width, c.height);
    URL.revokeObjectURL(im.src);
    setImage(c);
  };
  im.onerror = () => alert("เปิดรูปนี้ไม่ได้ ลองไฟล์ .jpg หรือ .png");
  im.src = URL.createObjectURL(f);
}

let disp = { w: 0, h: 0, k: 1 }, box = { x: 0, y: 0, s: 0 };
function setImage(c) {
  img = c;
  $("start").hidden = true; $("work").hidden = false;
  const maxW = Math.min(340, document.querySelector(".left").clientWidth - 30 || 340);
  const k = Math.min(1, maxW / c.width, 340 / c.height * (c.height > c.width ? 1 : 1));
  const cv = $("cropImg");
  cv.width = Math.round(c.width * k); cv.height = Math.round(c.height * k);
  cv.getContext("2d").drawImage(c, 0, 0, cv.width, cv.height);
  disp = { w: cv.width, h: cv.height, k };
  const s = Math.min(disp.w, disp.h);
  box = { x: (disp.w - s) / 2, y: (disp.h - s) / 2, s };
  drawBox(); search();
}
function drawBox() {
  const b = $("cbox").style;
  b.left = box.x - 2 + "px"; b.top = box.y - 2 + "px"; b.width = box.s + 4 + "px"; b.height = box.s + 4 + "px";
  // (border is 2px each side, box-sizing border-box, so offset by 2 keeps the inner area exact)
  crop = { x: box.x / disp.k, y: box.y / disp.k, s: box.s / disp.k };
}
(function cropEvents() {
  let drag = null;
  const pt = e => { const r = $("cropper").getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  $("cbox").addEventListener("pointerdown", e => {
    e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId);
    const h = e.target.dataset.h, [px, py] = pt(e);
    drag = h ? { h, ax: h.includes("w") ? box.x + box.s : box.x, ay: h.includes("n") ? box.y + box.s : box.y }
             : { h: null, dx: px - box.x, dy: py - box.y };
  });
  $("cbox").addEventListener("pointermove", e => {
    if (!drag) return;
    const [px, py] = pt(e);
    if (!drag.h) {
      box.x = Math.max(0, Math.min(disp.w - box.s, px - drag.dx));
      box.y = Math.max(0, Math.min(disp.h - box.s, py - drag.dy));
    } else {
      const sx = drag.h.includes("e") ? 1 : -1, sy = drag.h.includes("s") ? 1 : -1;
      const maxS = Math.min(sx > 0 ? disp.w - drag.ax : drag.ax, sy > 0 ? disp.h - drag.ay : drag.ay);
      const s = Math.max(24, Math.min(maxS, Math.max((px - drag.ax) * sx, (py - drag.ay) * sy)));
      box = { s, x: sx > 0 ? drag.ax : drag.ax - s, y: sy > 0 ? drag.ay : drag.ay - s };
    }
    drawBox();
  });
  const end = () => { if (drag) { drag = null; search(); } };
  $("cbox").addEventListener("pointerup", end);
  $("cbox").addEventListener("pointercancel", end);
})();

function cropCanvas(N) {
  const c = document.createElement("canvas"); c.width = c.height = N;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
  g.drawImage(img, crop.x, crop.y, crop.s, crop.s, 0, 0, N, N);
  return c;
}

// ---------- search ----------
function search() {
  window.__tSearch = performance.now();
  if (!img || !meta) return;
  const d = cropCanvas(96).getContext("2d").getImageData(0, 0, 96, 96).data;
  const sig = SigCore.signature(d, meta);
  qhist = SigCore.histogram(d);
  searchWorker.postMessage({
    type: "search", id: ++qid, sig, hist: qhist,
    mode: document.querySelector("input[name=mode]:checked").value,
    group: +$("group").value, query: $("q").value
  });
}
function onResult(m) {
  if (m.id !== qid) return;
  stopWork();
  if (m.empty || !m.items.length) {
    $("counter").textContent = "ไม่เจอเมนูที่ตรงกับที่พิมพ์ ลองคำอื่นดูนะ";
    return;
  }
  $("counter").textContent = `ค้น ${m.cand.toLocaleString("th-TH")} รูปใน ${(m.ms / 1000).toFixed(3)} วินาที`;
  items = m.items.map(it => ({ ...it, score: null, a64: null })); sel = -1;
  $("pct").textContent = "…%"; $("pctHi").innerHTML = "&nbsp;";
  showUserPixels();
  $("status").textContent = "กำลังลองประกอบ 13 จาน…";
  renderGrid();
  scoreAll(m.id);
}

// ---------- real scores for the shortlist (64x64, off the main thread) ----------
const SCORE_N = 64, SCORE_EFFORT = 120; // swap tries per pixel
let scoreWorker = null, src64 = null, tScore = 0;
let lowTok = 0, hiTok = 0, animLow = 0, animHi = 0, lowP = Promise.resolve(true), t0Sel = 0;
function stopWork() {
  ++lowTok; ++hiTok; cancelAnimationFrame(animLow); cancelAnimationFrame(animHi);
  if (scoreWorker) { scoreWorker.forEach(w => w.terminate()); scoreWorker = null; }
  if (assignWorker) { assignWorker.terminate(); assignWorker = null; }
  last = null; $("outHi").classList.remove("on"); setBtns();
}
function showUserPixels() {
  src64 = cropCanvas(SCORE_N).getContext("2d").getImageData(0, 0, SCORE_N, SCORE_N).data;
  const out = $("out"); out.width = out.height = SCORE_N;
  out.getContext("2d").putImageData(new ImageData(src64.slice(), SCORE_N, SCORE_N), 0, 0);
}
async function thumb64(i) {
  const im = await loadImg(thumbUrl(i));
  const c = document.createElement("canvas"); c.width = c.height = SCORE_N;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.imageSmoothingQuality = "high"; g.drawImage(im, 0, 0, SCORE_N, SCORE_N);
  return g.getImageData(0, 0, SCORE_N, SCORE_N).data;
}
async function scoreAll(id) {
  tScore = performance.now();
  let tg;
  try { tg = await Promise.all(items.map(it => thumb64(it.i))); } catch { $("status").textContent = "โหลดรูปอาหารไม่ได้"; return; }
  if (id !== qid) return;
  window.__thumbMs = performance.now() - tScore;
  const P = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1)), mine = items;
  const pool = scoreWorker = [];
  let left = P;
  const finish = () => {
    window.__scoreMs = performance.now() - tScore;
    items = mine.slice().sort((x, y) => y.score - x.score); // one re-order, so ranks always agree with the numbers
    select(0);
  };
  for (let p = 0; p < P; p++) {
    const w = new Worker("score-worker.js"); pool.push(w);
    w.onmessage = e => {
      if (id !== qid) return;
      const m = e.data;
      if (m.type === "one") {
        mine[m.k].score = m.score; mine[m.k].a64 = m.a;
        const el = document.querySelector(`#grid [data-k="${m.k}"] b`);
        if (el) el.textContent = m.score.toFixed(1) + "%";
      } else if (--left === 0) finish();
    };
    const ks = mine.map((_, k) => k).filter(k => k % P === p), bufs = ks.map(k => tg[k].slice().buffer);
    w.postMessage({ src: src64.slice().buffer, tgts: bufs, ks, iters: SCORE_N * SCORE_N * SCORE_EFFORT, seeds: ks.map(k => mine[k].i) }, bufs);
  }
}

function renderGrid() {
  const g = $("grid"); g.innerHTML = "";
  items.forEach((it, k) => {
    if (k === sel) return;
    const c = meta.classes[it.cls];
    const b = document.createElement("button");
    b.type = "button"; b.dataset.k = k;
    b.innerHTML = `<img alt="" loading="lazy" src="${thumbUrl(it.i)}"><span>${c.th}</span><b>${it.score == null ? "…%" : it.score.toFixed(1) + "%"}</b>`;
    b.addEventListener("click", () => { if (items.every(x => x.score != null)) select(k); });
    g.append(b);
  });
}

// ---------- selected result ----------
function select(k) {
  sel = k;
  const it = items[k], c = meta.classes[it.cls];
  stopWork();
  renderGrid();
  $("nameTh").textContent = c.th; $("nameEn").textContent = c.en;
  $("orig").src = fullUrl(it.i);
  $("pct").textContent = it.score.toFixed(1) + "%"; // same number as in the grid
  $("pctHi").innerHTML = "&nbsp;";
  drawChart(it);
  // 1) instant: animate the 64px assignment we already have (drawn big and blocky)
  const my = lowTok;
  window.__firstMotion = performance.now();
  $("status").textContent = "พิกเซลกำลังบินไปเรียง…";
  lowP = animate($("out"), SCORE_N, it.a64, src64, 1800, v => { animLow = v; }, () => my === lowTok);
  // 2) meanwhile: the sharp version
  runHi(it);
}
const loadImg = url => new Promise((ok, fail) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => fail(new Error(url)); i.src = url; });

async function targetData(it, N) {
  const im = await loadImg(N === 96 ? thumbUrl(it.i) : fullUrl(it.i));
  const c = document.createElement("canvas"); c.width = c.height = N;
  const g = c.getContext("2d", { willReadFrequently: true });
  g.imageSmoothingQuality = "high";
  g.drawImage(im, 0, 0, N, N);
  return g.getImageData(0, 0, N, N).data;
}

async function runHi(it) {
  const my = ++hiTok, N = +$("size").value, n = N * N;
  t0Sel = performance.now();
  cancelAnimationFrame(animHi); if (assignWorker) assignWorker.terminate();
  last = null; $("outHi").classList.remove("on"); setBtns();
  const srcD = cropCanvas(N).getContext("2d").getImageData(0, 0, N, N).data;
  let tgt;
  try { tgt = await targetData(it, N); } catch { return; }
  if (my !== hiTok) return;
  const w = assignWorker = new Worker("assign-worker.js");
  const s = srcD.slice(), t = new Uint8ClampedArray(tgt);
  w.onmessage = async e => {
    if (my !== hiTok) return;
    if (e.data.type === "progress") { $("pctHi").textContent = `ที่ ${N}px: กำลังจัด ${Math.round(e.data.p * 100)}%`; return; }
    w.terminate(); assignWorker = null;
    window.__hiMs = performance.now() - t0Sel;
    $("pctHi").textContent = `ที่ ${N}px: ${e.data.score.toFixed(1)}%`;
    last = { N, src: srcD, a: e.data.a, final: finalPixels(srcD, e.data.a) };
    await lowP; // let the quick animation finish, then cross-fade to the sharp picture
    if (my !== hiTok) return;
    drawFinal();
    $("outHi").classList.add("on");
    $("status").textContent = "เรียบร้อย"; setBtns();
  };
  w.postMessage({ src: s.buffer, tgt: t.buffer, n, iters: n * EFFORT }, [s.buffer, t.buffer]);
}
function finalPixels(src, a) {
  const sv = new Uint32Array(src.buffer, src.byteOffset, a.length), f = new Uint32Array(a.length);
  for (let t = 0; t < a.length; t++) f[t] = sv[a[t]];
  return f;
}
function drawFinal() {
  const { N, final } = last, cv = $("outHi"); cv.width = cv.height = N;
  const g = cv.getContext("2d"), im = g.createImageData(N, N);
  new Uint32Array(im.data.buffer).set(final); g.putImageData(im, 0, 0);
}

// Flying-pixel animation of rearrangement a (a[target] = source) on canvas cv. Resolves true when finished.
function animate(cv, N, a, src, dur0, setRaf, alive) {
  return new Promise(done => {
    const n = N * N;
    cv.width = cv.height = N;
    const g = cv.getContext("2d");
    const frame = g.createImageData(N, N), view = new Uint32Array(frame.data.buffer);
    const sv = new Uint32Array(src.buffer, src.byteOffset, n);
    const fx = new Float32Array(n), fy = new Float32Array(n), tx = new Float32Array(n), ty = new Float32Array(n);
    const delay = new Float32Array(n), col = new Uint32Array(n);
    for (let t = 0; t < n; t++) {
      const s = a[t];
      fx[t] = s % N; fy[t] = (s / N) | 0; tx[t] = t % N; ty[t] = (t / N) | 0;
      col[t] = sv[s];
      delay[t] = (ty[t] / N) * 0.35 + Math.random() * 0.15;
    }
    const dur = matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : dur0, t0 = performance.now();
    const ease = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
    const step = now => {
      if (!alive()) { done(false); return; }
      const p = Math.min(1, (now - t0) / dur);
      view.fill(0);
      for (let i = 0; i < n; i++) {
        const e = ease(Math.max(0, Math.min(1, (p - delay[i]) / 0.5)));
        view[Math.round(fy[i] + (ty[i] - fy[i]) * e) * N + Math.round(fx[i] + (tx[i] - fx[i]) * e)] = col[i];
      }
      g.putImageData(frame, 0, 0);
      if (p < 1) setRaf(requestAnimationFrame(step)); else done(true);
    };
    setRaf(requestAnimationFrame(step));
  });
}
function replay() {
  if (!last || !last.final) return;
  const my = hiTok, cv = $("outHi");
  cancelAnimationFrame(animHi);
  cv.classList.add("on"); $("save").disabled = true;
  animate(cv, last.N, last.a, last.src, 2600, v => { animHi = v; }, () => my === hiTok).then(ok => { if (ok) setBtns(); });
}
function setBtns() { $("replay").disabled = !(last && last.final); $("save").disabled = !(last && last.final); }

// ---------- colour-count chart ----------
function binColor(b) { return [((b >> 4) & 3) * 64 + 32, ((b >> 2) & 3) * 64 + 32, (b & 3) * 64 + 32]; }
const order = Array.from({ length: 64 }, (_, b) => b).sort((a, b) => {
  const l = x => { const [r, g, bl] = binColor(x); return 0.299 * r + 0.587 * g + 0.114 * bl; };
  return l(a) - l(b);
});
function drawChart(it) {
  const cv = $("chart"), dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W) return;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue("--ink").trim(), muted = css.getPropertyValue("--muted").trim();
  const mid = H / 2, bw = W / 64, half = mid - 22;
  const sc = v => Math.sqrt(v / 255) * half; // sqrt so small colours are still visible
  g.clearRect(0, 0, W, H);
  order.forEach((b, k) => {
    const [r, gg, bl] = binColor(b);
    g.fillStyle = `rgb(${r},${gg},${bl})`;
    const hu = sc(qhist[b]), hf = sc(it.hist[b]);
    g.fillRect(k * bw + 1, mid - 1 - hu, bw - 2, hu);
    g.fillRect(k * bw + 1, mid + 1, bw - 2, hf);
  });
  g.fillStyle = ink; g.fillRect(0, mid - 1, W, 2);
  g.fillStyle = muted; g.font = "13px Sarabun, sans-serif";
  g.fillText("รูปของคุณ", 4, 14); g.fillText("รูปอาหาร", 4, H - 6);
}
window.addEventListener("resize", () => { if (items[sel]) drawChart(items[sel]); });

// ---------- save / replay / controls ----------
$("save").addEventListener("click", () => {
  if (!last || !last.final) return;
  const { N } = last, scale = Math.max(1, Math.round(768 / N));
  const c = document.createElement("canvas"); c.width = c.height = N * scale;
  const g = c.getContext("2d"); g.imageSmoothingEnabled = false;
  g.drawImage($("outHi"), 0, 0, c.width, c.height);
  c.toBlob(blob => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `food-match-${Date.now()}.png`; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  });
});
$("replay").addEventListener("click", replay);
$("size").addEventListener("change", () => { if (items[sel]) runHi(items[sel]); });
$("group").addEventListener("change", search);
document.querySelectorAll("input[name=mode]").forEach(r => r.addEventListener("change", search));
let qt = 0; $("q").addEventListener("input", () => { clearTimeout(qt); qt = setTimeout(search, 250); });

function onFile(e) { readFile(e.target.files[0]); e.target.value = ""; }
$("file").addEventListener("change", onFile);
$("file2").addEventListener("change", onFile);
["dragenter", "dragover"].forEach(t => document.addEventListener(t, e => { e.preventDefault(); $("start").classList.add("over"); }));
["dragleave", "drop"].forEach(t => document.addEventListener(t, e => { e.preventDefault(); $("start").classList.remove("over"); }));
document.addEventListener("drop", e => readFile(e.dataTransfer.files[0]));
document.addEventListener("paste", e => { const f = [...(e.clipboardData?.files || [])][0]; if (f) readFile(f); });
