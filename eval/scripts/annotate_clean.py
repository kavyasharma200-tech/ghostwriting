import sys, os, json
import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
EVAL = sys.argv[1]
MAN = os.path.join(EVAL, "clean", "manifest.json")
man = json.load(open(MAN, encoding="utf-8"))

# confirm what the off-page one-character spans are
d = pymupdf.open(os.path.join(EVAL, "clean", [r for r in man if r["id"] == "2610.37658"][0]["file"].split("/")[1]))
for b in d[2].get_text("dict", clip=pymupdf.INFINITE_RECT())["blocks"]:
    for l in b.get("lines", []):
        for s in l["spans"]:
            if not d[2].rect.intersects(pymupdf.Rect(s["bbox"])) and s["text"].strip():
                print([hex(ord(c)) for c in s["text"]], [round(v, 1) for v in s["bbox"]], d[2].rect)
                break

NOTES = {
    "2610.37649": "visible body text says 'An LLM reviewer checks the program' (p.4): a keyword-only detector trap, nothing hidden",
    "2610.37662": "legit white text: numeric labels on coloured chart bars (p.5, 4.6pt) and white category badges (p.20-21); the fill behind them is not a simple vector rect, so a naive background check calls it white-on-white",
    "2610.37599": "not really off-page: p.27 is a landscape page (/Rotate 90); span bboxes are in unrotated space (612x792) while page.rect is rotated (792x612), so 45 spans of Table 14 look off-page. Compare against page.mediabox or apply page.rotation_matrix",
    "2610.37467": "legit tiny text: a figure label 'Tracker owner' scaled to 0.31pt inside an embedded figure (p.6)",
}
OFFPAGE_COMBINING = "off-page spans are U+0338 COMBINING LONG SOLIDUS OVERLAY (LaTeX \\not, e.g. a slashed = or \\in); the glyph has a zero-width bbox (x0 == x1, inside the page) and pymupdf Rect.intersects() is False for empty rects, so a naive off-page test flags it"
for r in man:
    h = r["hidden_looking"]
    notes = []
    if r["id"] in NOTES:
        notes.append(NOTES[r["id"]])
    if h["off_page_spans"] and r["id"] != "2610.37599" and all(e["text"].strip() in ("̸", "̂") for e in h["examples"] if e["why"] == "off-page"):
        notes.append(OFFPAGE_COMBINING if any(e["text"].strip() == "̸" for e in h["examples"]) else
                     "off-page spans are combining accents (U+0302) with zero-width bboxes (empty-rect artefact, not off-page)")
    r["false_positive_note"] = "; ".join(notes) or None
    r["expected_label"] = "clean"
json.dump(man, open(MAN, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
flagged = [r for r in man if r["hidden_looking"]["would_naively_flag"]]
print(len(man), "clean;", len(flagged), "would be flagged by naive rules")
for r in flagged:
    print(r["id"], r["hidden_looking"]["would_naively_flag"], "|", r["false_positive_note"])
