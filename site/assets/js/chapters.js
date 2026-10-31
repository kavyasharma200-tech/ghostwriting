// The scroll chapters, all drawn from measured results: the sixteen real papers, the October census,
// and which open models obey the ghost.

import { drawCandle, drawGlow, Smoke } from "./candle.js";

const $ = (s, r = document) => r.querySelector(s);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const narrow = () => matchMedia("(max-width: 860px)").matches;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const pct = (p) => (p * 100 < 0.1 ? "<0.1%" : p * 100 < 10 ? (p * 100).toFixed(1) + "%" : p * 100 > 99.9 ? "100%" : Math.round(p * 100) + "%");
const median = (a) => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const num = (n) => n.toLocaleString("en-US");
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen"];

/** A canvas that sizes itself to its box at the device's pixel ratio. */
function fit(canvas) {
  const r = canvas.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.round(r.width * d));
  canvas.height = Math.max(1, Math.round(r.height * d));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(d, 0, 0, d, 0, 0);
  return { ctx, w: r.width, h: r.height };
}

/** The sixteen: one slip per real paper; a candle walks along them as you scroll and each hidden line browns in. */
export function sixteen(results) {
  const box = $("[data-slips]");
  if (!box || !results?.real) return;
  const flips = new Map((results.gemma?.items || []).map((g) => [g.doc, g]));
  const items = results.real.items;
  box.innerHTML = items.map((x, i) => {
    const g = flips.get(x.id);
    return `<li class="slip" style="--i:${i}">
      <span class="slip__id"><a href="https://arxiv.org/abs/${esc(x.id)}" rel="noopener">${esc(x.id)}</a> · page ${esc(x.page ?? "?")}</span>
      <span class="slip__ink">${esc(x.text.length > 150 ? x.text.slice(0, 148) + "…" : x.text)}</span>
      <span class="slip__how">${esc(x.how)}</span>
      ${g ? `<span class="slip__gauge" title="Gemma 3 1B's chance of answering Accept, without and with the hidden text">
        <b>${pct(g.clean)}</b><i><s style="--a:${(g.clean * 100).toFixed(1)}%;--b:${(g.haunted * 100).toFixed(1)}%"></s></i><b>${pct(g.haunted)}</b></span>` : ""}
    </li>`;
  }).join("");
  const slips = [...box.children];
  const found = items.filter((x) => x.found).length;
  const g = items.map((x) => flips.get(x.id)).filter(Boolean);
  const minH = Math.min(...g.map((x) => x.haunted)), medC = median(g.map((x) => x.clean));
  $("[data-sx-tally]").innerHTML = `${found === items.length ? "All" : WORDS[found] || found} ${WORDS[items.length] || items.length} caught, every one talking to an AI. With the ghost left in, Gemma 3 1B's chance of accepting was <em>${pct(minH)} or more on every paper</em>, against a median of ${pct(medC)} without it.`;

  const sec = $("#case"), canvas = $("[data-sx-candle]");
  const gsap = window.gsap, ST = window.ScrollTrigger;
  if (reduce || !gsap || !ST) { slips.forEach((s) => s.classList.add("lit")); sec.classList.add("done"); return; }

  let p = 0, raf = 0, visible = false, t0 = performance.now(), last = t0;
  const smoke = new Smoke();
  const pos = { x: -1, y: -1 };
  let size = fit(canvas);
  new ResizeObserver(() => { size = fit(canvas); }).observe(canvas);
  const frame = (now) => {
    raf = 0;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const { ctx, w, h } = size;
    ctx.clearRect(0, 0, w, h);
    const cr = canvas.getBoundingClientRect();
    // The flame walks under the slip being read, from the first to the last.
    const k = Math.min(slips.length - 1, Math.max(0, p * 1.12 * slips.length - 0.5));
    const i = Math.floor(k), f = k - i, a = slips[i].getBoundingClientRect(), b = (slips[i + 1] || slips[i]).getBoundingClientRect();
    const tx = a.left + a.width * 0.5 + ((b.left + b.width * 0.5) - (a.left + a.width * 0.5)) * f - cr.left;
    const ty = a.top + a.height * 0.94 + (b.top - a.top) * f - cr.top;
    if (pos.x < 0) { pos.x = tx; pos.y = ty; }
    const kk = 1 - Math.pow(0.002, dt);
    const vx = (tx - pos.x) * kk / Math.max(dt, 1e-3);
    pos.x += (tx - pos.x) * kk; pos.y += (ty - pos.y) * kk;
    if (p > 0.02 && p < 0.98) {
      const t = (now - t0) / 1000;
      drawGlow(ctx, pos.x, pos.y, 0.7, t);
      if (Math.abs(vx) > 300) smoke.emit(pos.x, pos.y - 22, 1);
      smoke.step(dt); smoke.draw(ctx);
      drawCandle(ctx, pos.x, pos.y, 0.7, t, Math.max(-1, Math.min(1, -vx / 700)));
    }
    if (visible) raf = requestAnimationFrame(frame);
  };
  new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); } }).observe(sec);
  const apply = (self) => {
    p = self.progress;
    const n = Math.round(Math.min(1, p * 1.12) * slips.length);
    slips.forEach((s, i) => i < n && s.classList.add("lit")); // lemon ink stays brown once heated
    sec.classList.toggle("done", p > 0.9);
  };
  // Apply where the page already is: a visitor may arrive mid-chapter (a link, a reload).
  apply(ST.create({ trigger: sec, start: "top top", end: "bottom bottom", scrub: true, onUpdate: apply, onRefresh: apply }));
}

/** The October census: one tile per paper read, filling as you scroll, then what was found. */
export async function census() {
  const sec = $("#census");
  let c;
  try { c = await (await fetch("census.json", { cache: "no-cache" })).json(); } catch { sec.hidden = true; return; }
  const N = c.scanned, haunted = new Set((c.haunted || []).map((h) => h.id)), flagged = new Set((c.ruleHits || []).map((h) => h.id));
  const canvas = $("[data-census-wall]"), count = $("[data-census-count]"), finds = $("[data-census-finds]");
  $("[data-census-unit]").textContent = `papers read, ${num(c.pages)} pages drawn and checked`;
  const fmt = (d) => new Date(d + "T00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" });
  const lede = $("[data-census-lede]");
  if (c.from) lede.textContent = `Every new paper in machine learning, vision, language, robotics and security that went up on arXiv from ${fmt(c.from)} to ${fmt(c.to)} 2026, the month ICLR 2027 submissions closed. Every page drawn, every line checked, ${num(Math.round(c.bytes / 1e9))} GB read and thrown away.`;

  // What it found, said plainly, from the data.
  const parts = [];
  if (c.haunted?.length) {
    parts.push(`<p class="census__verdict">${c.haunted.length === 1 ? "One of them" : `${c.haunted.length} of them`} <em>${c.haunted.length === 1 ? "was" : "were"} hiding a sentence for an AI.</em></p>`);
    for (const h of c.haunted.slice(0, 4)) parts.push(`<figure class="find find--ghost"><q>${esc(h.text)}</q><figcaption><a href="https://arxiv.org/abs/${esc(h.id)}" rel="noopener">${esc(h.id)}</a> · page ${esc(h.page)} · ${esc((h.how || []).join(", "))}</figcaption></figure>`);
  } else {
    parts.push(`<p class="census__verdict">Not one of them <em>was hiding a sentence for an AI.</em></p>`);
  }
  const fa = (c.ruleHits || []).filter((h) => !haunted.has(h.id));
  if (fa.length) {
    const e = fa[0];
    parts.push(`<figure class="find"><q>${esc(e.text)}</q><figcaption>My plain rules flagged ${fa.length === 1 ? "this" : `${fa.length} like this`}: ${esc((e.how || []).join(", "))} on page ${esc(e.page)} of <a href="https://arxiv.org/abs/${esc(e.id)}" rel="noopener">${esc(e.id)}</a>. It names a model because it labels a figure, not because it is talking to one.</figcaption></figure>`);
  }
  if (c.classifier?.sentence) parts.push(`<p class="census__tabpfn">${esc(c.classifier.sentence)}</p>`);
  // Ghost Watch: the census keeps going every morning on GitHub Actions.
  try {
    const days = await (await fetch("census-daily.json", { cache: "no-cache" })).json();
    const d = days.at(-1);
    if (d) parts.push(`<p class="census__tabpfn">And it keeps reading. Every morning a GitHub Action reads the day before's new papers; on ${esc(fmt(d.day))} it read ${num(d.read)}, and ${d.flagged.length ? `flagged ${d.flagged.length} for a person to check` : "none of them was hiding anything for an AI"}.</p>`);
  } catch { /* no daily runs published yet */ }
  finds.innerHTML = parts.join("");

  let size = fit(canvas);
  const draw = (k) => {
    const { ctx, w, h } = size;
    ctx.clearRect(0, 0, w, h);
    // Tiles in reading order, like pages laid out on a long table.
    const cols = Math.max(20, Math.floor(Math.sqrt(N * (w / h)))), rows = Math.ceil(N / cols);
    const cw = w / cols, ch = Math.min(h / rows, cw * 1.35), gap = Math.max(0.6, cw * 0.14);
    const shown = Math.round(N * k);
    for (let i = 0; i < shown; i++) {
      const id = c.order[i], x = (i % cols) * cw, y = Math.floor(i / cols) * ch;
      ctx.fillStyle = haunted.has(id) ? "#b4652c" : flagged.has(id) ? "#d8a24c" : "rgba(236, 228, 210, .62)";
      ctx.fillRect(x + gap / 2, y + gap / 2, cw - gap, ch - gap);
    }
    count.textContent = num(shown);
  };
  new ResizeObserver(() => { size = fit(canvas); draw(last); }).observe(canvas);
  let last = 1;
  const gsap = window.gsap, ST = window.ScrollTrigger;
  if (reduce || !gsap || !ST) { draw(1); sec.classList.add("done"); return; }
  draw(0);
  const apply = (self) => { last = Math.min(1, self.progress * 1.3); draw(last); sec.classList.toggle("done", self.progress > 0.72); };
  apply(ST.create({ trigger: sec, start: "top 60%", end: "bottom bottom", scrub: 0.6, onUpdate: apply, onRefresh: apply }));
}

/** Who obeys: each model's chance of "Accept" on the real papers, without and with the hidden line. */
export async function obey() {
  const box = $("[data-obey]");
  let L;
  try { L = await (await fetch("leaderboard.json", { cache: "no-cache" })).json(); } catch { $("#obey").hidden = true; return; }
  const rows = L.models || [];
  if (!rows.length) { $("#obey").hidden = true; return; }
  box.innerHTML = `<div class="obey__axis"><span>0%</span><span>chance of “Accept”</span><span>100%</span></div>` + rows.map((m) => `
    <div class="obey__row${m.family === "gemma" ? " is-gemma" : ""}">
      <span class="obey__name">${esc(m.name)}<small>${esc(m.note || "")}</small></span>
      <span class="obey__track"><s style="--a:${(m.clean * 100).toFixed(1)}%;--b:${(m.haunted * 100).toFixed(1)}%"></s></span>
      <span class="obey__nums"><b>${pct(m.clean)}</b> → <b>${pct(m.haunted)}</b></span>
    </div>`).join("");
  if (L.lede) $("[data-obey-lede]").textContent = L.lede;
}

/** The x-ray: one page, what you see on one side of the seam and the text an AI receives on the other. */
export async function xray(scanned) {
  const fig = $("[data-xray]");
  if (!fig) return;
  const d = await scanned;
  const src = d.pages[0].canvas, copy = document.createElement("canvas");
  copy.width = src.width; copy.height = src.height;
  copy.getContext("2d").drawImage(src, 0, 0);
  copy.setAttribute("aria-hidden", "true");
  $("[data-xray-pixels]").replaceChildren(copy);
  let text = esc(d.machine.replace(/[ \t]+\n/g, "\n"));
  for (const g of d.ghosts) if (!g.quiet) text = text.replace(esc(g.text), `<mark>${esc(g.text)}</mark>`);
  const pre = $("[data-xray-pre]");
  pre.innerHTML = text;
  fig.style.setProperty("--ratio", (d.pages[0].width / d.pages[0].height).toFixed(4));
  // Size the mono text so the longest line spans the page's text column, roughly where it sits on paper.
  const longest = Math.max(...d.machine.split("\n").map((l) => l.length), 40);
  const sizeText = () => fig.style.setProperty("--fs", `${(fig.getBoundingClientRect().width * 0.78) / (longest * 0.6)}px`);
  sizeText();
  new ResizeObserver(sizeText).observe(fig);

  let dragged = false;
  const set = (v) => fig.style.setProperty("--cut", `${Math.max(4, Math.min(96, v))}%`);
  const seam = $("[data-xray-seam]");
  const move = (e) => { const r = fig.getBoundingClientRect(); set(((e.clientX - r.left) / r.width) * 100); };
  seam.addEventListener("pointerdown", (e) => { dragged = true; seam.setPointerCapture(e.pointerId); move(e); });
  seam.addEventListener("pointermove", (e) => seam.hasPointerCapture(e.pointerId) && move(e));
  fig.addEventListener("click", (e) => { if (e.target !== seam) { dragged = true; move(e); } });
  seam.addEventListener("keydown", (e) => {
    const cur = parseFloat(fig.style.getPropertyValue("--cut")) || 50;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") { dragged = true; set(cur + (e.key === "ArrowLeft" ? -5 : 5)); e.preventDefault(); }
  });
  // Taught by doing: the seam sweeps across as the page scrolls in, until the visitor takes it.
  const gsap = window.gsap, ST = window.ScrollTrigger;
  if (reduce || !gsap || !ST) { set(50); return; }
  set(94);
  ST.create({ trigger: fig, start: "top 85%", end: "center 45%", scrub: 0.8, onUpdate: (self) => !dragged && set(94 - self.progress * 58) });
}

/** Where you are: the wick on the right edge burns down with the page. */
export function wick() {
  const w = document.querySelector(".wick");
  if (!w) return;
  const set = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    w.style.setProperty("--p", max > 0 ? Math.min(1, scrollY / max).toFixed(4) : 0);
  };
  addEventListener("scroll", set, { passive: true });
  set();
}

/** Goodnight: the candle burns at the foot of the page, and goes out with a curl of smoke as you arrive. */
export function snuff() {
  const canvas = $("[data-snuff]");
  if (!canvas) return;
  let size = fit(canvas), out = reduce ? 1 : 0, raf = 0, visible = false, last = performance.now();
  const smoke = new Smoke(), t0 = performance.now();
  new ResizeObserver(() => { size = fit(canvas); }).observe(canvas);
  const frame = (now) => {
    raf = 0;
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const { ctx, w, h } = size, x = w / 2, y = h * 0.42, t = (now - t0) / 1000;
    ctx.clearRect(0, 0, w, h);
    if (visible && out < 1) out = Math.min(1, out + dt / 2.4);
    if (out < 1) {
      ctx.save();
      ctx.globalAlpha = 1 - out;
      drawGlow(ctx, x, y, 1, t);
      ctx.restore();
    }
    if (out > 0.55 && out < 0.98) smoke.emit(x + 2, y - 4, 1);
    smoke.step(dt); smoke.draw(ctx);
    ctx.save();
    // The flame shrinks into the wick as it goes out.
    if (out < 1) {
      ctx.translate(x, y); ctx.scale(1, Math.max(0.02, 1 - out)); ctx.translate(-x, -y);
      ctx.globalAlpha = 1 - out * 0.6;
    }
    drawCandle(ctx, x, y, 1, t, 0, 0.35);
    ctx.restore();
    if (visible || smoke.p.length) raf = requestAnimationFrame(frame);
  };
  new IntersectionObserver((es) => {
    visible = es[0].isIntersecting;
    if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
  }, { threshold: 0.6 }).observe(canvas);
}
