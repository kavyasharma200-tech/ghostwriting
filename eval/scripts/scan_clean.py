"""Scan clean PDFs for text that LOOKS hidden (white/near-white, <2pt, render mode 3, off-page,
zero-width / tag chars) and add a `hidden_looking` summary to clean/manifest.json."""
import sys, os, re, json
import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
EVAL = sys.argv[1]
MAN = os.path.join(EVAL, "clean", "manifest.json")
man = json.load(open(MAN, encoding="utf-8"))
KEYS = re.compile(r"IGNORE (ALL )?PREVIOUS|POSITIVE REVIEW|LLM REVIEWER|as a language model, you should", re.I)


def light(c):
    return min((c >> 16) & 255, (c >> 8) & 255, c & 255) >= 0xF0


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


for r in man:
    doc = pymupdf.open(os.path.join(EVAL, r["file"]))
    s = {"white_on_background": 0, "white_on_fill_or_image": 0, "tiny_lt2pt": 0, "render_mode_3_chars": 0,
         "off_page_spans": 0, "zero_width_chars": 0, "tag_chars": 0, "injection_keywords": 0, "examples": []}
    for page in doc:
        if page.number >= 60:
            break
        try:
            for t in page.get_texttrace():
                if t["type"] == 3:
                    s["render_mode_3_chars"] += len(t["chars"])
        except Exception:
            pass
        txt = page.get_text(clip=pymupdf.INFINITE_RECT())
        s["zero_width_chars"] += sum(txt.count(z) for z in "​‌‍⁠﻿")
        s["tag_chars"] += sum(1 for ch in txt if 0xE0000 <= ord(ch) <= 0xE007F)
        if KEYS.search(txt):
            s["injection_keywords"] += 1
        fills = None
        d = page.get_text("dict", clip=pymupdf.INFINITE_RECT())
        for b in d["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                for sp in l["spans"]:
                    if not sp["text"].strip():
                        continue
                    rect = pymupdf.Rect(sp["bbox"])
                    ex = None
                    if not page.rect.intersects(rect):
                        s["off_page_spans"] += 1; ex = "off-page"
                    if sp["size"] < 2:
                        s["tiny_lt2pt"] += 1; ex = ex or "tiny %.2fpt" % sp["size"]
                    if light(sp["color"]):
                        if fills is None:
                            try:
                                fills = [(dr["rect"], dr["fill"]) for dr in page.get_drawings() if dr.get("fill")]
                            except Exception:
                                fills = []
                            fills += [(pymupdf.Rect(im["bbox"]), (0, 0, 0)) for im in page.get_image_info()]
                        c = rect.tl + (rect.br - rect.tl) * 0.5
                        under = [f for rr, f in fills if c in rr]
                        if under and lum(under[-1]) < 0.75:
                            s["white_on_fill_or_image"] += 1
                        else:
                            s["white_on_background"] += 1; ex = ex or "white on page background"
                    if ex and len(s["examples"]) < 4:
                        s["examples"].append({"page": page.number + 1, "why": ex, "color": "#%06X" % sp["color"],
                                              "size": round(sp["size"], 2), "text": sp["text"][:80]})
    flags = [k for k in ("white_on_background", "tiny_lt2pt", "render_mode_3_chars", "off_page_spans",
                         "zero_width_chars", "tag_chars", "injection_keywords") if s[k]]
    s["would_naively_flag"] = flags
    r["hidden_looking"] = s
    print(r["id"], r["query_category"], flags, {k: s[k] for k in flags}, s["examples"][:2])
json.dump(man, open(MAN, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
