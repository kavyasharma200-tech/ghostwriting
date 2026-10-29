import sys, os, re, json, glob
import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
EVAL = sys.argv[1]
KEYS = re.compile(r"IGNORE ALL PREVIOUS|POSITIVE REVIEW|LLM REVIEWER|As a language model|recommend accepting|REVIEW REQUIREMENTS", re.I)


def is_light(c):
    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
    return min(r, g, b) >= 0xF0


res = {}
for f in sorted(glob.glob(os.path.join(EVAL, "real", "*.pdf"))):
    pid = os.path.basename(f)[:-4]
    doc = pymupdf.open(f)
    runs_out = []
    for pno, page in enumerate(doc):
        invis_y = set()
        try:
            for t in page.get_texttrace():
                if t["type"] == 3 or (t.get("opacity") is not None and t["opacity"] < 0.05):
                    invis_y.add(round(t["bbox"][1]))
        except Exception:
            pass
        d = page.get_text("dict")
        spans = [s for b in d["blocks"] if b["type"] == 0 for l in b["lines"] for s in l["spans"]]
        run = []

        def flush():
            if run:
                txt = re.sub(r"\s+", " ", " ".join(s["text"] for s in run)).strip()
                if len(txt.split()) >= 3:
                    s0 = run[0]
                    why = []
                    if is_light(s0["color"]): why.append("white/near-white text")
                    if s0["size"] < 2: why.append("tiny font (%.2fpt)" % s0["size"])
                    if round(s0["bbox"][1]) in invis_y: why.append("render mode 3 / zero opacity")
                    if not page.rect.intersects(pymupdf.Rect(s0["bbox"])): why.append("off-page")
                    runs_out.append({"page": pno + 1, "text": txt, "color": "#%06X" % s0["color"],
                                     "size": round(s0["size"], 2), "font": s0["font"],
                                     "bbox": [round(x, 1) for x in s0["bbox"]], "how": why,
                                     "keyword": bool(KEYS.search(txt))})
            run.clear()

        for s in spans:
            r = pymupdf.Rect(s["bbox"])
            susp = is_light(s["color"]) or s["size"] < 2 or round(s["bbox"][1]) in invis_y or not page.rect.intersects(r)
            if susp and s["text"].strip():
                run.append(s)
            elif s["text"].strip():
                flush()
        flush()
    # plain keyword search too (catches hiding methods not covered above)
    kw_pages = [p.number + 1 for p in doc if KEYS.search(p.get_text())]
    res[pid] = {"runs": runs_out, "keyword_pages": kw_pages, "pages": len(doc)}
    print("==", pid, len(doc), "pages; keyword pages:", kw_pages, "; suspicious runs:", len(runs_out))
    for h in runs_out:
        if h["keyword"] or len(runs_out) < 6:
            print("   ", json.dumps(h, ensure_ascii=False)[:900])
json.dump(res, open(sys.argv[2], "w", encoding="utf-8"), indent=1, ensure_ascii=False)
