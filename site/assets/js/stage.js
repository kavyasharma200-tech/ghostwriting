// A sheet of paper on a dark desk and a candle you hold to it. Hidden words are written in lemon-juice ink:
// heat builds up where the flame passes, and the ink browns from faint yellow to amber to brown and stays,
// as real lemon ink does. Used by the desk (the live tool) and by the scroll story.

import { drawCandle, drawGlow, flicker, Smoke } from "./candle.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const SCALE = 2; // pages are rendered at 2x (scan-pdf.js)

function layer(w, h) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return c;
}

/** Wraps a sentence to a width, in the font already set on ctx. */
function wrap(ctx, text, width) {
  const lines = [];
  let line = "";
  for (const w of text.split(/\s+/)) {
    const t = line ? line + " " + w : w;
    if (ctx.measureText(t).width > width && line) { lines.push(line); line = w; } else line = t;
  }
  if (line) lines.push(line);
  return lines;
}

export class Stage {
  /** `figure` holds `[data-paper]`; the light and the candle are painted on a canvas over the whole figure. */
  constructor(figure, { candleScale = 1, onRevealed } = {}) {
    this.fig = figure;
    this.paper = figure.querySelector("[data-paper]");
    this.light = document.createElement("canvas");
    this.light.className = "stage__lightcanvas";
    this.light.setAttribute("aria-hidden", "true");
    figure.append(this.light);
    this.lctx = this.light.getContext("2d");
    this.s = candleScale;
    this.onRevealed = onRevealed;
    this.smoke = new Smoke();
    this.pos = { x: -200, y: -200 };     // flame, in figure pixels
    this.target = { x: 0.2, y: 0.15 };   // flame target, as fractions of the paper
    this.vel = 0; this.lean = 0;
    this.lastPointer = 0;
    this.path = null;                    // { points, start, dur, loop }
    this.ghosts = [];                    // ghost boxes in paper pixels, for "is it revealed yet"
    this.spans = [];                     // DOM ghosts in sheet mode
    this.revealed = false;
    this.lit = false;
    this.visible = true;
    this.t0 = performance.now();
    new ResizeObserver(() => this.resize()).observe(figure);
    new IntersectionObserver((es) => { this.visible = es[0].isIntersecting; if (this.visible) this.kick(); }).observe(figure);
    const pointer = (e) => {
      const r = this.paper.getBoundingClientRect();
      if (!r.width) return;
      this.target = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height + 0.05 };
      this.lastPointer = performance.now();
      this.path = null;
      this.lit = true;
      this.kick();
    };
    figure.addEventListener("pointermove", pointer);
    figure.addEventListener("pointerdown", pointer);
    this.resize();
  }

  resize() {
    const r = this.fig.getBoundingClientRect();
    this.dpr = Math.min(2, devicePixelRatio || 1);
    this.light.width = Math.max(1, Math.round(r.width * this.dpr));
    this.light.height = Math.max(1, Math.round(r.height * this.dpr));
    this.kick();
  }

  /** A rendered PDF page, with its hidden runs drawn in lemon ink where they sit. */
  showPdfPage(page, ghosts) {
    this.mode = "pdf";
    const W = page.canvas.width, H = page.canvas.height;
    this.W = W; this.H = H;
    this.comp = layer(W, H); this.comp.className = "stage__ink";
    this.cctx = this.comp.getContext("2d");
    page.canvas.className = "stage__page";
    page.canvas.setAttribute("aria-hidden", "true");
    this.paper.replaceChildren(page.canvas, this.comp);
    this.paper.style.setProperty("--ratio", (page.width / page.height).toFixed(4));
    // Two inks and two heat maps: the amber shows after a little heat, the brown only after more.
    this.amber = layer(W, H); this.brown = layer(W, H);
    this.heatA = layer(W >> 1, H >> 1); this.heatB = layer(W >> 1, H >> 1);
    this.scratch = layer(W, H);
    const actx = this.amber.getContext("2d"), bctx = this.brown.getContext("2d");
    const pad = 40 * SCALE;
    this.ghosts = [];
    for (const g of ghosts) {
      if (g.page !== page.number) continue;
      const rects = g.rects?.length ? g.rects : [{ x: 40, y: page.height - 44, w: 0, h: 12 }];
      const h = Math.max(...rects.map((r) => r.h * SCALE));
      const size = Math.max(14 * SCALE, Math.min(18 * SCALE, h * 0.82));
      const x = Math.max(pad, Math.min(Math.min(...rects.map((r) => r.x * SCALE)), W - pad * 4));
      const y = Math.max(pad, Math.min(Math.min(...rects.map((r) => r.y * SCALE)), H - pad));
      for (const [ctx, ink] of [[actx, "rgba(196, 140, 52, 0.85)"], [bctx, "rgba(112, 58, 24, 0.95)"]]) {
        ctx.font = `italic 500 ${size}px "EB Garamond", Georgia, serif`;
        ctx.fillStyle = ink;
        ctx.textBaseline = "top";
        const lines = wrap(ctx, g.text, W - pad - x);
        lines.forEach((l, i) => ctx.fillText(l, x, y + i * size * 1.22));
        if (ctx === bctx) this.ghosts.push({ x, y, w: Math.max(...lines.map((l) => ctx.measureText(l).width)), h: lines.length * size * 1.22 });
      }
    }
    this.boxes = this.ghosts.map((g) => ({ x: g.x / 2, y: g.y / 2, w: g.w / 2, h: g.h / 2, dose: 0 }));
    this.revealed = !this.ghosts.length;
    this.dirty = true;
    this.kick();
  }

  /** Web pages and plain text: a DOM sheet whose hidden spans (.gh) brown in with the heat. */
  showSheet(sheet) {
    this.mode = "sheet";
    this.paper.replaceChildren(sheet);
    this.paper.style.setProperty("--ratio", ".74");
    const r = this.paper.getBoundingClientRect();
    this.W = Math.max(2, Math.round(r.width)); this.H = Math.max(2, Math.round(r.height));
    this.heatA = layer(this.W >> 1, this.H >> 1); this.heatB = layer(this.W >> 1, this.H >> 1);
    this.spans = [...sheet.querySelectorAll(".gh")];
    this.ghosts = [];
    this.boxes = this.spans.map((sp) => {
      const b = sp.getBoundingClientRect();
      return { x: (b.left - r.left) / 2, y: (b.top - r.top) / 2, w: b.width / 2, h: b.height / 2, dose: 0, span: sp };
    });
    this.revealed = !this.spans.length;
    this.kick();
  }

  /** Brings every ghost out at once (or puts the room back to candlelight). */
  revealAll(on = true) {
    this.all = on;
    this.paper.classList.toggle("all", on);
    if (on && this.heatB) for (const c of [this.heatA, this.heatB]) { const x = c.getContext("2d"); x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); }
    this.dirty = true;
    this.kick();
  }

  /** Moves the flame along points (fractions of the paper) over `dur` seconds; the pointer takes over at once. */
  play(points, dur = 6, loop = false) {
    this.path = { points, start: performance.now(), dur: dur * 1000, loop };
    this.lit = true;
    this.kick();
  }

  /** Puts the flame at a point now, for scroll-driven scenes. */
  set(fx, fy) {
    this.target = { x: fx, y: fy };
    this.lit = true;
    this.kick();
  }

  /** Points that walk the flame under every ghost on the page, left to right, then rest below the first. */
  pathOverGhosts() {
    if (!this.ghosts.length) return [[0.2, 0.2], [0.6, 0.45], [0.4, 0.7]];
    const pts = [[0.12, 0.08]];
    for (const g of this.ghosts) {
      const y = (g.y + g.h + 26 * SCALE) / this.H;
      pts.push([g.x / this.W + 0.02, y], [(g.x + g.w * 0.5) / this.W, y + 0.004], [Math.min(0.9, (g.x + g.w) / this.W), y]);
    }
    const f = this.ghosts[0];
    pts.push([(f.x + f.w * 0.45) / this.W, (f.y + f.h + 40 * SCALE) / this.H]);
    return pts;
  }

  kick() {
    if (this.raf || !this.visible) return;
    this.last = performance.now();
    this.raf = requestAnimationFrame((t) => this.frame(t));
  }

  heat(fx, fy, r, dt) {
    if (!this.heatA) return;
    const W = this.heatA.width, H = this.heatA.height;
    const x = fx * W, y = fy * H - r * W * 0.42, rad = r * W;
    for (const [c, rate] of [[this.heatA, 2.6], [this.heatB, 0.9]]) {
      const ctx = c.getContext("2d");
      ctx.globalCompositeOperation = "lighter";
      const jx = (Math.random() - 0.5) * rad * 0.2, jy = (Math.random() - 0.5) * rad * 0.2;
      const g = ctx.createRadialGradient(x + jx, y + jy, 0, x + jx, y + jy, rad);
      g.addColorStop(0, `rgba(255,255,255,${Math.min(1, rate * dt)})`);
      g.addColorStop(0.55, `rgba(255,255,255,${Math.min(1, rate * dt * 0.45)})`);
      g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g;
      ctx.fillRect(x - rad, y - rad, rad * 2, rad * 2);
    }
    this.dirty = true;
    // Keep count of the heat each hidden line has had, in arithmetic rather than by reading pixels back
    // from the canvas, which would stall weak graphics every frame.
    for (const b of this.boxes || []) {
      const dx = Math.max(b.x - x, 0, x - (b.x + b.w)), dy = Math.max(b.y - y, 0, y - (b.y + b.h));
      const near = Math.max(0, 1 - Math.hypot(dx, dy) / rad);
      if (near) b.dose = Math.min(2, (b.dose || 0) + 0.9 * dt * near);
    }
  }

  /** Has the first hidden line had enough heat to read? Fires onRevealed once. */
  checkRevealed() {
    if (this.revealed || !this.boxes?.length || !this.onRevealed) return;
    if (this.boxes[0].dose > 0.55) { this.revealed = true; this.onRevealed(); }
  }

  compose() {
    if (this.mode !== "pdf" || !this.dirty) return;
    this.dirty = false;
    const { cctx, W, H } = this;
    cctx.clearRect(0, 0, W, H);
    // The paper toasts a little where it was heated.
    cctx.globalAlpha = 0.1;
    cctx.globalCompositeOperation = "source-over";
    cctx.filter = "sepia(1) saturate(3) brightness(.75)";
    cctx.drawImage(this.heatB, 0, 0, W, H);
    cctx.filter = "none";
    cctx.globalAlpha = 1;
    const sctx = this.scratch.getContext("2d");
    for (const [ink, heat] of [[this.amber, this.heatA], [this.brown, this.heatB]]) {
      sctx.globalCompositeOperation = "source-over";
      sctx.clearRect(0, 0, W, H);
      sctx.drawImage(ink, 0, 0);
      sctx.globalCompositeOperation = "destination-in";
      sctx.drawImage(heat, 0, 0, W, H);
      cctx.drawImage(this.scratch, 0, 0);
    }
  }

  frame(now) {
    this.raf = 0;
    try { this.draw(now); } catch (err) {
      // A frame can land while a new page is being set up; skip it rather than stop the candle.
      if (!this.warned) { this.warned = true; console.warn("stage frame skipped:", err.message); }
    }
    if (!reduce) this.kick();
  }

  draw(now) {
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    const t = (now - this.t0) / 1000;
    const pr = this.paper.getBoundingClientRect(), fr = this.fig.getBoundingClientRect();
    if (!pr.width) return;

    if (this.path && !reduce) {
      const { points, start, dur, loop } = this.path;
      let k = (now - start) / dur;
      if (loop) k %= 1;
      if (k >= 1) { this.path = null; k = 1; }
      const e = k * (points.length - 1), i = Math.min(points.length - 2, Math.floor(e)), f = e - i;
      const a = points[i], b = points[i + 1] || a, s = f * f * (3 - 2 * f);
      this.target = { x: a[0] + (b[0] - a[0]) * s, y: a[1] + (b[1] - a[1]) * s };
    }
    // Ease toward the target, like a hand; the flame leans away from the motion.
    const tx = pr.left - fr.left + this.target.x * pr.width, ty = pr.top - fr.top + this.target.y * pr.height;
    if (this.pos.x < -100) this.pos = { x: tx, y: ty };
    const k = 1 - Math.pow(0.0009, dt);
    const nx = this.pos.x + (tx - this.pos.x) * k, ny = this.pos.y + (ty - this.pos.y) * k;
    const vx = (nx - this.pos.x) / Math.max(dt, 1e-3);
    this.vel = Math.hypot(vx, (ny - this.pos.y) / Math.max(dt, 1e-3));
    this.lean += (Math.max(-1, Math.min(1, -vx / 600)) - this.lean) * Math.min(1, dt * 6);
    this.pos = { x: nx, y: ny };

    // The candle keeps its size relative to the paper, so a phone gets a smaller one.
    const sc = this.s * Math.max(0.45, Math.min(1, pr.width / 560));
    // Heat where the flame is over the paper.
    const fx = (nx - (pr.left - fr.left)) / pr.width, fy = (ny - (pr.top - fr.top)) / pr.height;
    // Heat soaks in while the flame moves and for a moment after it stops; a resting candle costs little.
    if (this.vel > 4) this.movedAt = now;
    const soaking = now - (this.movedAt || 0) < 1500;
    if (this.lit && soaking && fx > -0.1 && fx < 1.1 && fy > -0.1 && fy < 1.2) this.heat(fx, fy, 0.13, dt);
    if (((this._n = (this._n || 0) + 1) & 1) === 0) this.compose(); // the ink catches up every other frame
    this.checkRevealed();
    if (this.mode === "sheet" && this.boxes?.length && this._n % 4 === 0) this.sheetHeat();

    // The room: dark, except where the flame lights it.
    const ctx = this.lctx, d = this.dpr, W = this.light.width, H = this.light.height;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.setTransform(d, 0, 0, d, 0, 0);
    if (this.lit) {
      const R = Math.max(240, pr.width * 0.62) * (1 + flicker(t, 2) * 0.035);
      ctx.fillStyle = this.all ? "rgba(14, 11, 8, 0.12)" : "rgba(16, 11, 7, 0.82)";
      ctx.fillRect(pr.left - fr.left, pr.top - fr.top, pr.width, pr.height);
      ctx.globalCompositeOperation = "destination-out";
      const g = ctx.createRadialGradient(nx, ny - 20, 0, nx, ny - 20, R);
      g.addColorStop(0, "rgba(0,0,0,1)");
      g.addColorStop(0.45, "rgba(0,0,0,.75)");
      g.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, fr.width, fr.height);
      ctx.globalCompositeOperation = "source-over";
      // Candlelight is warm: tint what it lights.
      const w = ctx.createRadialGradient(nx, ny - 20, 0, nx, ny - 20, R * 0.8);
      w.addColorStop(0, "rgba(255, 176, 96, 0.16)");
      w.addColorStop(1, "rgba(255, 150, 70, 0)");
      ctx.fillStyle = w;
      ctx.fillRect(pr.left - fr.left, pr.top - fr.top, pr.width, pr.height);
      drawGlow(ctx, nx, ny, sc, t);
      if (this.vel > 260 && !reduce) this.smoke.emit(nx + 2, ny - 30 * sc, 1);
      this.smoke.step(dt);
      this.smoke.draw(ctx);
      drawCandle(ctx, nx, ny, sc, t, this.lean, 0);
    }
  }

  sheetHeat() {
    for (const b of this.boxes) {
      const o = Math.min(1, (b.dose || 0) * 1.6);
      if (o !== b.o) { b.o = o; b.span.style.setProperty("--o", o.toFixed(3)); }
    }
  }

}
