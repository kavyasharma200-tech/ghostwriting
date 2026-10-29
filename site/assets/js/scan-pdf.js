// PDFs: compare what the text layer says with what the pixels show.
// A person reads the pixels; an AI reads the text layer. Text with no ink under it is a ghost.

import * as pdfjs from "../vendor/pdf.min.mjs";
import { scanText, stripInvisible } from "./scan-text.js";

pdfjs.GlobalWorkerOptions.workerSrc = new URL("../vendor/pdf.worker.min.mjs", import.meta.url).href;

const SCALE = 2; // render at 2x so thin type still leaves measurable ink
const INK = 48; // luminance step that counts as ink against the paper
const FAINT = 4; // a step this small is visible to a sensor, not to a reader
const TINY_PT = 2.5;

const lum = (d, i) => 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];

const letters = (s) => s.normalize("NFKC").toLowerCase().replace(/[^a-z]/g, ""); // NFKC: the "ﬁ" ligature becomes "fi"
const TAG = /[\u{E0000}-\u{E007F}]/u;
const SHOW = new Set([pdfjs.OPS.showText, pdfjs.OPS.showSpacedText, pdfjs.OPS.nextLineShowText, pdfjs.OPS.nextLineSetSpacingShowText]);

/**
 * pdf.js leaves some drawn text out of its text layer: words placed outside the page, and lines made of
 * characters it treats as unprintable (Unicode tag characters). Other extractors, the kind AI tools use,
 * still read them. So read the page's drawing instructions and keep any run the text layer doesn't have.
 */
async function unlisted(page, items) {
  const listed = letters(items.map((i) => i.str).join(""));
  const ops = await page.getOperatorList();
  const runs = [];
  let run = "";
  for (let k = 0; k < ops.fnArray.length; k++) {
    if (!SHOW.has(ops.fnArray[k])) continue;
    const args = ops.argsArray[k];
    const glyphs = args[args.length - 1];
    if (!Array.isArray(glyphs)) continue;
    let str = "";
    for (const g of glyphs) {
      if (typeof g === "number") { if (g < -180) str += " "; }
      else if (g) str += g.unicode ?? "";
    }
    const l = letters(str);
    if (TAG.test(str) || (l.length >= 3 && !listed.includes(l))) run += (run ? " " : "") + str;
    else if (str.trim()) { if (run) runs.push(run); run = ""; }
  }
  if (run) runs.push(run);
  return runs.filter((r) => TAG.test(r) || letters(r).length >= 12);
}

/** How much ink sits inside a box of the rendered page. */
function inkIn(img, W, H, x, y, w, h) {
  const x0 = Math.max(0, Math.floor(x)), y0 = Math.max(0, Math.floor(y));
  const x1 = Math.min(W, Math.ceil(x + w)), y1 = Math.min(H, Math.ceil(y + h));
  if (x1 - x0 < 2 || y1 - y0 < 2) return { area: 0, ink: 0, faint: 0 };
  const hist = new Uint32Array(64);
  const vals = [];
  for (let yy = y0; yy < y1; yy++) {
    for (let xx = x0; xx < x1; xx++) {
      const L = lum(img, (yy * W + xx) * 4);
      vals.push(L);
      hist[L >> 2]++;
    }
  }
  let mode = 0;
  for (let b = 1; b < 64; b++) if (hist[b] > hist[mode]) mode = b;
  const paper = mode * 4 + 2;
  let ink = 0, faint = 0;
  for (const L of vals) {
    const d = Math.abs(L - paper);
    if (d > INK) ink++;
    else if (d > FAINT) faint++;
  }
  return { area: vals.length, ink: ink / vals.length, faint: faint / vals.length };
}

/**
 * Scans a PDF. Returns pages (with a canvas of what a person sees), ghosts, and two texts:
 * everything an AI reads, and the same text with the ghosts taken out.
 */
export async function scanPdf(data, { maxPages = 60, onPage } = {}) {
  const doc = await pdfjs.getDocument({ data, isEvalSupported: false }).promise;
  const pages = [];
  const ghosts = [];
  let machine = "", clean = "";
  const n = Math.min(doc.numPages, maxPages);
  for (let p = 1; p <= n; p++) {
    const page = await doc.getPage(p);
    const vp = page.getViewport({ scale: SCALE });
    const canvas = document.createElement("canvas");
    canvas.width = Math.ceil(vp.width);
    canvas.height = Math.ceil(vp.height);
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    await page.render({ canvasContext: ctx, viewport: vp, canvas }).promise;
    const img = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    const tc = await page.getTextContent();

    let run = null;
    const flush = () => {
      if (run && run.text.trim().length > 1) ghosts.push(run);
      run = null;
    };
    for (const item of tc.items) {
      if (typeof item.str !== "string") continue;
      const str = item.str;
      const eol = item.hasEOL ? "\n" : "";
      machine += str + (eol || " ");
      if (!str.trim()) { clean += str + eol; continue; }

      const t = pdfjs.Util.transform(vp.transform, item.transform);
      const fh = Math.hypot(t[2], t[3]); // font height on the canvas
      const pt = Math.hypot(item.transform[2], item.transform[3]); // font height in PDF points
      const w = Math.max(item.width * SCALE, fh * 0.4 * str.length);
      const box = { x: t[4], y: t[5] - fh * 0.85, w, h: fh * 1.05 };
      const how = [];

      const off = box.x + box.w < 0 || box.y + box.h < 0 || box.x > canvas.width || box.y > canvas.height;
      if (off) how.push("off the page");
      else {
        if (pt > 0 && pt < TINY_PT) how.push(`${pt.toFixed(1)} pt type`);
        const m = inkIn(img, canvas.width, canvas.height, box.x, box.y, box.w, box.h);
        if (m.area > 0) {
          if (m.ink < 0.012 && m.faint < 0.03) how.push("no ink on the page");
          else if (m.ink < 0.012) how.push("almost the colour of the paper");
        }
      }

      if (how.length) {
        const rect = { x: box.x / SCALE, y: box.y / SCALE, w: box.w / SCALE, h: box.h / SCALE };
        if (run && run.page === p) {
          run.text += (run.text.endsWith("\n") ? "" : " ") + str + eol;
          run.rects.push(rect);
          for (const h of how) if (!run.how.includes(h)) run.how.push(h);
        } else {
          flush();
          run = { source: "pdf", page: p, text: str + eol, rects: [rect], how: [...how], font: item.fontName, pt: +pt.toFixed(1) };
        }
      } else {
        flush();
        clean += str + (eol || " ");
      }
    }
    flush();
    for (const r of await unlisted(page, tc.items)) {
      machine += r + "\n";
      const coded = scanText(r, { source: "pdf", page: p }).filter((g) => !g.quiet);
      if (coded.length) ghosts.push(...coded);
      else ghosts.push({ source: "pdf", page: p, text: stripInvisible(r), how: ["off the page"], rects: [] });
    }
    // Keep the drawing only where there is something to show: long papers would otherwise hold hundreds of MB.
    const keep = p === 1 || ghosts.some((g) => g.page === p);
    if (!keep) canvas.width = canvas.height = 0;
    pages.push({ number: p, canvas: keep ? canvas : null, width: vp.width / SCALE, height: vp.height / SCALE });
    onPage?.(pages[pages.length - 1], ghosts);
  }

  const known = new Set(ghosts.map((g) => g.text));
  for (const g of scanText(machine, { source: "pdf" })) if (!known.has(g.text)) ghosts.push(g);
  for (const g of ghosts) g.text = g.text.replace(/\s+/g, " ").trim();
  return { kind: "pdf", pages, total: doc.numPages, ghosts, machine: machine.trim(), clean: stripInvisible(clean).trim() };
}
