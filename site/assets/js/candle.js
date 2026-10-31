// The candle, painted in code. Physical light, so it keeps its own colours (flame, wax, smoke); the page
// palette is for everything around it.

const TAU = Math.PI * 2;

/** Smooth value noise in one dimension: a few sines at unrelated rates, so the flicker never repeats. */
export function flicker(t, seed = 0) {
  return (
    Math.sin(t * 7.3 + seed) * 0.5 +
    Math.sin(t * 13.1 + seed * 2.1) * 0.28 +
    Math.sin(t * 23.7 + seed * 3.7) * 0.14 +
    Math.sin(t * 2.1 + seed * 0.7) * 0.6
  ) / 1.52;
}

/** Smoke wisps that rise and curl from the wick when the candle moves fast, then fade. */
export class Smoke {
  constructor() { this.p = []; }
  emit(x, y, n = 1) {
    for (let i = 0; i < n; i++) this.p.push({ x, y, vx: (Math.random() - 0.5) * 6, vy: -18 - Math.random() * 14, life: 0, max: 1.6 + Math.random() * 1.2, r: 2 + Math.random() * 2, seed: Math.random() * 10 });
    if (this.p.length > 120) this.p.splice(0, this.p.length - 120);
  }
  step(dt) {
    for (const q of this.p) {
      q.life += dt;
      q.vx += Math.sin(q.life * 3 + q.seed) * 12 * dt;
      q.x += q.vx * dt; q.y += q.vy * dt;
      q.r += 7 * dt;
    }
    this.p = this.p.filter((q) => q.life < q.max);
  }
  draw(ctx) {
    if (!this.p.length) return;
    ctx.save();
    ctx.filter = "blur(3px)";
    for (const q of this.p) {
      const a = 0.16 * (1 - q.life / q.max) * Math.min(1, q.life * 4);
      const g = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, q.r);
      g.addColorStop(0, `rgba(196, 188, 176, ${a})`);
      g.addColorStop(1, "rgba(196, 188, 176, 0)");
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(q.x, q.y, q.r, 0, TAU); ctx.fill();
    }
    ctx.restore();
  }
}

/** The halo the flame throws into the room. Drawn with "lighter" so it adds light rather than paint. */
export function drawGlow(ctx, x, y, s, t) {
  const f = 1 + flicker(t, 4) * 0.06;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  let g = ctx.createRadialGradient(x, y - 14 * s, 0, x, y - 14 * s, 150 * s * f);
  g.addColorStop(0, "rgba(255, 196, 120, 0.22)");
  g.addColorStop(0.35, "rgba(255, 160, 80, 0.08)");
  g.addColorStop(1, "rgba(255, 140, 60, 0)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(x, y - 14 * s, 150 * s * f, 0, TAU); ctx.fill();
  g = ctx.createRadialGradient(x, y - 16 * s, 0, x, y - 16 * s, 34 * s * f);
  g.addColorStop(0, "rgba(255, 236, 190, 0.35)");
  g.addColorStop(1, "rgba(255, 200, 140, 0)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(x, y - 16 * s, 34 * s * f, 0, TAU); ctx.fill();
  ctx.restore();
}

function flamePath(ctx, x, y, w, h, lean) {
  // A teardrop: round belly at the wick, a long tip that leans away from the motion.
  const tipX = x + lean * h * 0.5, tipY = y - h;
  ctx.beginPath();
  ctx.moveTo(x, y + w * 0.35);
  ctx.bezierCurveTo(x - w * 1.05, y + w * 0.2, x - w * 0.9, y - h * 0.42, tipX, tipY);
  ctx.bezierCurveTo(x + w * 0.9, y - h * 0.42, x + w * 1.05, y + w * 0.2, x, y + w * 0.35);
  ctx.closePath();
}

/**
 * The whole candle with its flame at (x, y): the point where the flame meets the wick. `s` scales it,
 * `t` is time in seconds, `lean` (-1..1) tilts the flame, `burn` (0..1) shortens the wax as it burns down.
 */
export function drawCandle(ctx, x, y, s, t, lean = 0, burn = 0) {
  const f1 = flicker(t, 1), f2 = flicker(t * 1.3, 7);
  const bodyW = 30 * s, bodyH = (96 - 60 * burn) * s, top = y + 9 * s;

  // Wax: a cylinder lit from its own flame, warmer and brighter near the top.
  ctx.save();
  const bx = x - bodyW / 2;
  let g = ctx.createLinearGradient(bx, 0, bx + bodyW, 0);
  g.addColorStop(0, "#b9ab90");
  g.addColorStop(0.32, "#efe4cb");
  g.addColorStop(0.55, "#fbf4e2");
  g.addColorStop(1, "#a99a7f");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(bx, top + 3 * s);
  ctx.lineTo(bx, top + bodyH - 4 * s);
  ctx.quadraticCurveTo(bx, top + bodyH, bx + 4 * s, top + bodyH);
  ctx.lineTo(bx + bodyW - 4 * s, top + bodyH);
  ctx.quadraticCurveTo(bx + bodyW, top + bodyH, bx + bodyW, top + bodyH - 4 * s);
  ctx.lineTo(bx + bodyW, top + 3 * s);
  ctx.closePath();
  ctx.fill();
  // The flame lights the wax from inside near the top (wax is translucent).
  g = ctx.createRadialGradient(x, top, 0, x, top, bodyW * 0.95);
  g.addColorStop(0, `rgba(255, 190, 110, ${0.55 + f1 * 0.08})`);
  g.addColorStop(1, "rgba(255, 190, 110, 0)");
  ctx.fillStyle = g;
  ctx.fillRect(bx, top, bodyW, bodyW);
  // The melt pool at the rim.
  ctx.fillStyle = "#fff3d6";
  ctx.beginPath(); ctx.ellipse(x, top + 3 * s, bodyW / 2, 4 * s, 0, 0, TAU); ctx.fill();
  g = ctx.createRadialGradient(x, top + 3 * s, 0, x, top + 3 * s, bodyW / 2);
  g.addColorStop(0, "rgba(255, 210, 140, 0.9)");
  g.addColorStop(1, "rgba(255, 230, 190, 0.2)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.ellipse(x, top + 3 * s, bodyW / 2 - 2 * s, 3 * s, 0, 0, TAU); ctx.fill();
  // Two drips down the lit side.
  ctx.fillStyle = "#f6ecd6";
  for (const [dx, len] of [[-0.32, 18], [0.18, 11]]) {
    const px = x + dx * bodyW;
    ctx.beginPath();
    ctx.moveTo(px - 2.6 * s, top + 3 * s);
    ctx.lineTo(px - 2.2 * s, top + (len - 2) * s);
    ctx.arc(px, top + len * s, 2.4 * s, Math.PI, 0, true);
    ctx.lineTo(px + 2.6 * s, top + 3 * s);
    ctx.fill();
  }
  ctx.restore();

  // Wick: a dark curl with an ember at the tip.
  ctx.save();
  ctx.strokeStyle = "#2a1d14";
  ctx.lineWidth = 2.2 * s;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(x, top + 2 * s);
  ctx.quadraticCurveTo(x + 1 * s, y + 4 * s, x + 2 * s + lean * 2 * s, y - 1 * s);
  ctx.stroke();
  ctx.fillStyle = "rgba(255, 120, 40, 0.9)";
  ctx.beginPath(); ctx.arc(x + 2 * s + lean * 2 * s, y - 1 * s, 1.3 * s, 0, TAU); ctx.fill();
  ctx.restore();

  // Flame: an outer amber body, a white-hot core and a blue root, softened like real light.
  const h = (34 + f1 * 3.2 + f2 * 1.6) * s, w = (8.2 + f2 * 0.6) * s, ln = lean * 0.9 + f2 * 0.05;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.filter = `blur(${1.6 * s}px)`;
  flamePath(ctx, x, y, w * 1.25, h * 1.08, ln);
  g = ctx.createLinearGradient(0, y, 0, y - h * 1.1);
  g.addColorStop(0, "rgba(255, 150, 60, 0.0)");
  g.addColorStop(0.18, "rgba(255, 150, 60, 0.75)");
  g.addColorStop(0.7, "rgba(255, 120, 40, 0.45)");
  g.addColorStop(1, "rgba(255, 90, 30, 0)");
  ctx.fillStyle = g; ctx.fill();
  ctx.filter = `blur(${0.8 * s}px)`;
  flamePath(ctx, x, y - h * 0.06, w * 0.72, h * 0.78, ln * 0.85);
  g = ctx.createLinearGradient(0, y, 0, y - h * 0.8);
  g.addColorStop(0, "rgba(255, 255, 245, 0.4)");
  g.addColorStop(0.25, "rgba(255, 250, 225, 0.98)");
  g.addColorStop(1, "rgba(255, 214, 140, 0.25)");
  ctx.fillStyle = g; ctx.fill();
  ctx.filter = `blur(${1.2 * s}px)`;
  g = ctx.createRadialGradient(x, y + 1 * s, 0, x, y + 1 * s, w * 0.8);
  g.addColorStop(0, "rgba(90, 120, 255, 0.55)");
  g.addColorStop(1, "rgba(90, 120, 255, 0)");
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(x, y + 1 * s, w * 0.8, 0, TAU); ctx.fill();
  ctx.restore();
}
