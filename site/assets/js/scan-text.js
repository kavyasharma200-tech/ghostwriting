// Invisible characters: text an AI reads but no font draws.

const ZERO_WIDTH = /[​-‏⁠-⁤﻿᠎]/gu;
const BIDI = /[‪-‮⁦-⁩]/gu;
const TAGS = /[\u{E0000}-\u{E007F}]+/gu;
// Variation selectors carry no picture of their own; long runs of them can smuggle bytes.
const VS_RUN = /[︀-️\u{E0100}-\u{E01EF}]{4,}/gu;

function vsByte(ch) {
  const cp = ch.codePointAt(0);
  if (cp >= 0xfe00 && cp <= 0xfe0f) return cp - 0xfe00;
  return cp - 0xe0100 + 16;
}

/** Finds invisible characters in a string and decodes any message hidden in them. */
export function scanText(text, where = {}) {
  const ghosts = [];
  for (const m of text.matchAll(TAGS)) {
    const decoded = Array.from(m[0], (c) => String.fromCodePoint(c.codePointAt(0) - 0xe0000)).join("").replace(/[\u0000-\u001f]/g, "");
    if (decoded.trim()) ghosts.push({ ...where, text: decoded.trim(), how: ["Unicode tag characters"], index: m.index, raw: m[0].length });
  }
  for (const m of text.matchAll(VS_RUN)) {
    try {
      const bytes = Uint8Array.from(Array.from(m[0], vsByte));
      const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      if (/[a-z]{3}/i.test(decoded)) ghosts.push({ ...where, text: decoded.trim(), how: ["variation selectors"], index: m.index, raw: m[0].length });
    } catch { /* not text, just unusual emoji */ }
  }
  const zw = text.match(ZERO_WIDTH) || [];
  if (zw.length >= 3) {
    ghosts.push({ ...where, text: `${zw.length} zero-width characters woven into the text`, how: ["zero-width characters"], count: zw.length, quiet: true });
  }
  const bidi = text.match(BIDI) || [];
  if (bidi.length) ghosts.push({ ...where, text: `${bidi.length} direction-override characters (text can display in a different order than it's read)`, how: ["direction overrides"], count: bidi.length, quiet: true });
  return ghosts;
}

/** The text with every invisible character removed. */
export function stripInvisible(text) {
  return text.replace(TAGS, "").replace(VS_RUN, "").replace(ZERO_WIDTH, "").replace(BIDI, "");
}
