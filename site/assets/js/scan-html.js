// Web pages: lay the page out for real (scripts off) and ask, for every piece of text,
// whether a person could see it. An AI reading the page source sees all of it.

import { scanText, stripInvisible } from "./scan-text.js";

function parseColor(c) {
  const m = c.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const [r, g, b, a = 1] = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
  return { r, g, b, a };
}
const rel = ({ r, g, b }) => {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
};
const contrast = (a, b) => { const x = rel(a), y = rel(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

function backgroundOf(el, win) {
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const c = parseColor(win.getComputedStyle(n).backgroundColor);
    if (c && c.a > 0.5) return c;
  }
  return { r: 255, g: 255, b: 255, a: 1 };
}

/** Scans an HTML string. Returns the ghosts plus the machine text and the visible text. */
export async function scanHtml(html, { width = 1280 } = {}) {
  const frame = document.createElement("iframe");
  frame.setAttribute("sandbox", "allow-same-origin"); // no scripts run inside
  frame.style.cssText = `position:fixed;left:-20000px;top:0;width:${width}px;height:900px;visibility:hidden`;
  document.body.appendChild(frame);
  await new Promise((res) => { frame.onload = res; frame.srcdoc = html.replace(/<script[\s\S]*?<\/script>/gi, ""); });
  const win = frame.contentWindow, doc = frame.contentDocument;
  const ghosts = [];
  const sequence = []; // visible text and ghosts in reading order, for drawing the page
  let machine = "", clean = "";
  const walker = doc.createTreeWalker(doc.body || doc.documentElement, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_COMMENT);
  const W = doc.documentElement.scrollWidth, H = doc.documentElement.scrollHeight;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.nodeValue.replace(/\s+/g, " ").trim();
    if (!text) continue;
    if (node.nodeType === Node.COMMENT_NODE) {
      if (text.length > 8) { ghosts.push({ source: "html", text, how: ["HTML comment"] }); sequence.push({ ghost: ghosts.length - 1 }); }
      machine += text + "\n";
      continue;
    }
    const el = node.parentElement;
    if (!el || /^(STYLE|NOSCRIPT|TEMPLATE|TITLE)$/.test(el.tagName)) continue;
    machine += text + " ";
    const st = win.getComputedStyle(el);
    const how = [];
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) how.push("hidden with CSS");
    const fs = parseFloat(st.fontSize);
    if (fs < 3) how.push(`${fs}px type`);
    const col = parseColor(st.color);
    if (col && col.a < 0.1) how.push("transparent text");
    else if (col && contrast(col, backgroundOf(el, win)) < 1.2) how.push("same colour as its background");
    const r = el.getBoundingClientRect();
    if (r.right < 0 || r.bottom < 0 || r.left > W || r.top > H + 2000) how.push("off the page");
    else if (r.width <= 2 && r.height <= 2 && st.overflow !== "visible") how.push("squeezed into one pixel");
    const block = /^(P|H[1-6]|LI|DIV|SECTION|ARTICLE|TD|BLOCKQUOTE)$/.test(el.tagName) ? el.tagName.toLowerCase() : "span";
    if (how.length) {
      ghosts.push({ source: "html", text, how, tag: el.tagName.toLowerCase(), screenReader: how.length === 1 && how[0] === "squeezed into one pixel" });
      sequence.push({ ghost: ghosts.length - 1 });
    } else {
      clean += text + " ";
      const last = sequence[sequence.length - 1];
      if (last && last.text != null && last.el === el) last.text += " " + text;
      else sequence.push({ text, block, el });
    }
  }
  for (const g of scanText(machine, { source: "html" })) { ghosts.push(g); sequence.push({ ghost: ghosts.length - 1 }); }
  for (const s of sequence) delete s.el;
  const title = doc.title || "";
  frame.remove();
  return { kind: "html", pages: [], ghosts, sequence, title, machine: machine.trim(), clean: stripInvisible(clean).trim() };
}
