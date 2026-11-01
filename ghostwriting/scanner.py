"""The scanner the census, the command line and the MCP server share.

A person reads the pixels and an AI reads the text, so every run of text is checked for whether a person could
see it: white on the page, under 2 pt, drawn in invisible mode, off the page, or spelled in Unicode tag
characters. Each hidden run is then read by the same rules the site uses (site/assets/js/judge.js) to say whether
it talks to an AI.
"""
import re
from pathlib import Path

import numpy as np
import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)

AI = r"(?:llms?|large language models?|language models?|ai|assistants?|chatbots?|chatgpt|gpt-?\d\w*|claude|gemini|copilot)"
RULES = [
    (r"\b(ignore|disregard|forget)\b[^.]{0,30}\b(previous|prior|above|earlier|all|the user'?s?)\b[^.]{0,20}\b(instructions?|prompts?|rules?|context|questions?|requests?)\b", "tells the AI to drop its instructions"),
    (r"\b(llms?|large language models?|language models?|ai (reviewers?|reviewing|assistants?|models?|systems?|agents?|graders?|screeners?|screening|reading|summari[sz]ing)|chatgpt|gpt-?\d|claude|gemini|copilot|chatbot)\b", "addresses an AI by name"),
    (r"\bai(\s+[a-z]+){0,2}\s+(reviewers?|screeners?|readers?|graders?|summari[sz]ers?)\b|\bnote to (the |any )?" + AI + r"\b|^\s*" + AI + r"\s*,", "addresses an AI by name"),
    # "LLM REVIEWER NOTE", "For LLM reviewers": a reader that is an AI, spoken to. (Not on the site, which counts any name.)
    (r"\b(llms?|ai|language models?|automated)\s+(reviewers?|graders?|screeners?|screening|readers?|recruiters?|summari[sz]ers?)\b"
     r"|\b(instructions?|notes?|messages?)\s+(for|to)\s+(the\s+|any\s+|all\s+)?(llms?|ai|language models?|assistants?|chatbots?|chatgpt|claude|gemini|copilot)\b",
     "speaks to an AI reader"),
    (r"\b(you are|act as|pretend to be|as an?) (an? )?(ai|assistant|reviewer|grader|recruiter|language model)\b", "gives the AI a role"),
    (r"\b(positive review|give (a|this) (positive|high|top|good)|recommend (accepting|acceptance|this)|accept this (paper|submission)|score (this|it) (highly|10)|rate (this|it|me) (highly|10|5)|five stars?)", "asks for a good verdict"),
    (r"\b(hire|shortlist|top candidate|best candidate|strongest candidate|highly qualified|strong(ly)? recommend (this|the) candidate|rank [^.]{0,40}\bfirst)\b", "asks to favour a candidate"),
    (r"\b(do not|don't|never) (mention|reveal|tell|disclose|summari[sz]e|highlight)\b", "asks the AI to keep something from you"),
    (r"\b(system prompt|new instructions|instead,? (say|write|reply|respond)|(reply|respond|answer) only\b|when (asked|summari[sz]ing)\b[^.]{0,40}\b(say|reply|respond|answer|tell)\b)", "tries to rewrite the AI's instructions"),
]
RULES = [(re.compile(p, re.I), why) for p, why in RULES]

TAGS = re.compile("[\U000E0000-\U000E007F]+")
ZERO_WIDTH = re.compile("[​-‏⁠-⁤﻿᠎]")
BIDI = re.compile("[‪-‮⁦-⁩]")
TEXT_SUFFIXES = {".txt", ".md", ".eml", ".csv", ".json"}


def rules(text):
    """What a hidden run is asking of an AI, as plain reasons (empty when it says nothing to one)."""
    return sorted({why for rx, why in RULES if rx.search(text)})


def talks_to_ai(hits):
    """Whether a hidden run's rule hits make it a ghost. Naming a model isn't talking to it: a hidden chart legend
    listing "GPT, Claude, Gemini" only names them, while every real ghost also asks for something."""
    return bool(set(hits) - {"addresses an AI by name"})


def minor(text):
    """A figure label, a maths symbol or the arXiv stamp: hidden, but under five real words and saying nothing to an AI."""
    if rules(text):
        return False
    if re.match(r"arXiv:\d", text.strip(), re.I):
        return True
    return len(re.findall(r"[A-Za-z]{3,}", text)) < 5


def strip_invisible(text):
    return BIDI.sub("", ZERO_WIDTH.sub("", TAGS.sub("", text)))


def _light(c):
    return min((c >> 16) & 255, (c >> 8) & 255, c & 255) >= 0xF0


def _lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


INK_ZOOM, INK_RANGE = 2, 18


def _no_ink(pix, page, r):
    """Whether a span's box on the drawn page is one flat colour: white on white, a word under a shape, text the
    colour of its box. A person reads the pixels, so if the pixels don't change, there's nothing for them to read."""
    q = (r * page.rotation_matrix * pymupdf.Matrix(INK_ZOOM, INK_ZOOM)).irect & pymupdf.IRect(0, 0, pix.shape[1], pix.shape[0])
    if q.is_empty or q.width < 2 or q.height < 2:
        return False
    box = pix[q.y0:q.y1, q.x0:q.x1]
    return int(box.max()) - int(box.min()) < INK_RANGE


def _spans(doc, max_pages=80, ink=False):
    """Every span of text in the document with the reasons a person couldn't see it (empty when they can).
    With `ink`, each page is also drawn and every span checked for ink, as the site does (slower, catches more)."""
    for page in doc:
        if page.number >= max_pages:
            break
        pix = None
        if ink:
            pm = page.get_pixmap(matrix=pymupdf.Matrix(INK_ZOOM, INK_ZOOM), colorspace=pymupdf.csGRAY, alpha=False)
            pix = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.stride)[:, :pm.width]
        trace = []
        try:
            trace = page.get_texttrace()
        except Exception:
            pass
        mode3 = [pymupdf.Rect(t["bbox"]) for t in trace if t["type"] == 3]
        fills = None
        for b in page.get_text("dict", clip=pymupdf.INFINITE_RECT())["blocks"]:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                for sp in line["spans"]:
                    if not sp["text"].strip():
                        # Spaces are their own spans in many PDFs: the clean text needs them, the scan doesn't.
                        yield page, b, line, sp, pymupdf.Rect(sp["bbox"]), None, 1.0
                        continue
                    r = pymupdf.Rect(sp["bbox"])
                    c = r.tl + (r.br - r.tl) * 0.5
                    how, bg = [], 1.0
                    # Off the page: test the box's corners (a zero-width box, like the slash of a LaTeX "≠", never intersects).
                    if not any(page.rect.contains(p) for p in (r.tl, r.br, r.tr, r.bl)) and r.width > 1:
                        how.append("off the page")
                    if 0 < sp["size"] < 2:
                        how.append(f"{sp['size']:.2g} pt type")
                    if _light(sp["color"]):
                        if fills is None:
                            try:
                                fills = [(dr["rect"], dr["fill"]) for dr in page.get_drawings() if dr.get("fill")]
                            except Exception:
                                fills = []
                            fills += [(pymupdf.Rect(im["bbox"]), (0, 0, 0)) for im in page.get_image_info()]
                        under = [f for rr, f in fills if c in rr]
                        bg = _lum(under[-1]) if under else 1.0
                        if not (under and bg < 0.75):
                            how.append("white on the page")
                    if TAGS.search(sp["text"]):
                        how.append("Unicode tag characters")
                    # Invisible render mode: the span's centre falls inside a trace drawn with mode 3 (the two boxes
                    # are measured differently and rarely match exactly).
                    if mode3 and any(c in m for m in mode3):
                        how.append("invisible render mode")
                    if pix is not None and not how and _no_ink(pix, page, r):
                        how.append("no ink on the page")
                    yield page, b, line, sp, r, how, bg
        # Text drawn wholly outside the page never reaches the extracted text above, but an AI pipeline that uses
        # another extractor reads it, so it is taken from the page's drawing trace instead.
        for t in trace:
            r = pymupdf.Rect(t["bbox"])
            text = "".join(chr(ch[0]) for ch in t["chars"] if ch[0] > 0)
            if text.strip() and r.width > 1 and not r.intersects(page.rect):
                col = t.get("color") or (0, 0, 0)
                sp = {"text": text, "size": t["size"], "font": t.get("font", ""),
                      "color": (round(col[0] * 255) << 16) | (round(col[1] * 255) << 8) | round(col[2] * 255) if len(col) == 3 else 0}
                yield page, None, None, sp, r, ["off the page"], 1.0


def scan(data, max_pages=80, ink=False):
    """Hidden-looking runs of text in a PDF or a text file. Returns (pages, runs); each run has the page, the text,
    how it was hidden, `ai` (what it asks of an AI, empty when nothing) and the measurements the classifier uses."""
    if not data.startswith(b"%PDF"):
        return 1, scan_text(data.decode("utf-8", "replace"))
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = doc.page_count
    runs, run, seen = [], None, []
    for page, _, _, sp, r, how, bg in _spans(doc, max_pages, ink):
        seen.append(sp["text"])
        if how is None:
            continue
        if how:
            col = sp["color"]
            m = {"size": sp["size"], "lum": _lum(((col >> 16) & 255, (col >> 8) & 255, col & 255)) / 255, "bg": bg,
                 "bbox": [r.x0, r.y0, r.x1, r.y1], "font": sp["font"][:40]}
            if run and run["page"] == page.number + 1:
                run["text"] += " " + sp["text"]
                run["how"] = sorted(set(run["how"] + how))
                run["spans"].append(m)
            else:
                if run:
                    runs.append(run)
                run = {"page": page.number + 1, "text": sp["text"], "how": how, "spans": [m],
                       "page_w": page.rect.width, "page_h": page.rect.height, "page_index": page.number / max(1, pages - 1)}
        elif run:
            runs.append(run)
            run = None
    if run:
        runs.append(run)
    doc.close()
    for r in runs:
        decoded = _decode_tags(r["text"])
        r["text"] = " ".join((decoded or strip_invisible(r["text"])).split())
        r["ai"] = rules(r["text"])
    # Characters no font draws, woven through the visible text.
    runs += [r for r in scan_text("".join(seen)) if r["how"][0] != "Unicode tag characters"]
    return pages, [r for r in runs if r["text"]]


def _decode_tags(text):
    return "".join(chr(ord(ch) - 0xE0000) for m in TAGS.finditer(text) for ch in m.group() if ord(ch) - 0xE0000 >= 0x20).strip()


def scan_text(text):
    """Messages hidden in a plain-text file: Unicode tag characters (decoded), zero-width characters and direction overrides."""
    runs = []
    for m in TAGS.finditer(text):
        decoded = _decode_tags(m.group())
        if decoded:
            runs.append({"page": 1, "text": decoded, "how": ["Unicode tag characters"], "ai": rules(decoded)})
    zw = ZERO_WIDTH.findall(text)
    if len(zw) >= 3:
        runs.append({"page": 1, "text": f"{len(zw)} zero-width characters woven into the text", "how": ["zero-width characters"], "ai": []})
    bidi = BIDI.findall(text)
    if bidi:
        runs.append({"page": 1, "text": f"{len(bidi)} direction-override characters", "how": ["direction overrides"], "ai": []})
    return runs


def exorcise(source, runs=None):
    """The document's text with every hidden run taken out: what is safe to hand to an AI.
    `source` is a path or the file's bytes; `runs` are the hidden runs from scan() (scanned again when left out)."""
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    if not data.startswith(b"%PDF"):
        return strip_invisible(data.decode("utf-8", "replace")).strip()
    if runs is None:
        _, runs = scan(data, ink=True)
    hidden = {(r["page"], tuple(round(v, 1) for v in s["bbox"])) for r in runs for s in r.get("spans", [])}
    doc = pymupdf.open(stream=data, filetype="pdf")
    out, last = [], None
    for page, block, line, sp, r, how, _ in _spans(doc, max_pages=10_000):
        if block is None or how or (page.number + 1, tuple(round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1))) in hidden:
            continue
        where = (page.number, id(block), id(line))
        if last and where[:2] != last[:2]:
            out.append("\n\n" if where[0] != last[0] else "\n")
        elif last and where != last:
            out.append(" ")
        out.append(strip_invisible(sp["text"]))
        last = where
    doc.close()
    return re.sub(r"[ \t]+", " ", "".join(out)).strip()


def check(path):
    """One document, ready for a person or an agent: is it haunted, what is hidden, and the text with the ghosts taken out."""
    path = Path(path)
    data = path.read_bytes()
    pages, runs = scan(data, ink=True)
    public = lambda r: {"page": r["page"], "text": r["text"], "how": r["how"], "asks": r["ai"]}
    return {
        "file": str(path),
        "pages": pages,
        "haunted": any(talks_to_ai(r["ai"]) for r in runs),
        "ghosts": [public(r) for r in runs if talks_to_ai(r["ai"])],
        "other_hidden": [public(r) for r in runs if not talks_to_ai(r["ai"]) and not minor(r["text"])],
        "fragments": sum(1 for r in runs if not talks_to_ai(r["ai"]) and minor(r["text"])),
        "clean_text": exorcise(data, runs),
    }
