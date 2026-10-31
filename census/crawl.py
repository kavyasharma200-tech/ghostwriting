"""The arXiv census: scan every new paper in a set of categories for text hidden for AI readers.

    python census/crawl.py --since 2026-10-01 --out census/results.jsonl

Lists papers with the arXiv API, newest first, then fetches each PDF from export.arxiv.org one at a time,
3 seconds apart (arXiv's guidance for automated access). Each PDF is scanned in memory with PyMuPDF and never
kept; only what was found goes to the results file, one JSON line per paper, so the run can stop and resume.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
UA = "Ghostwriting-census/1.0 (https://github.com/kavyasharma200-tech/ghostwriting)"
API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
GAP = 3.1

# The same rules the site uses (site/assets/js/judge.js), ported.
AI = r"(?:llms?|large language models?|language models?|ai|assistants?|chatbots?|chatgpt|gpt-?\d\w*|claude|gemini|copilot)"
RULES = [
    (r"\b(ignore|disregard|forget)\b[^.]{0,30}\b(previous|prior|above|earlier|all|the user'?s?)\b[^.]{0,20}\b(instructions?|prompts?|rules?|context|questions?|requests?)\b", "tells the AI to drop its instructions"),
    (r"\b(llms?|large language models?|language models?|ai (reviewers?|reviewing|assistants?|models?|systems?|agents?|graders?|screeners?|screening|reading|summari[sz]ing)|chatgpt|gpt-?\d|claude|gemini|copilot|chatbot)\b", "addresses an AI by name"),
    (r"\bai(\s+[a-z]+){0,2}\s+(reviewers?|screeners?|readers?|graders?|summari[sz]ers?)\b|\bnote to (the |any )?" + AI + r"\b|^\s*" + AI + r"\s*,", "addresses an AI by name"),
    (r"\b(you are|act as|pretend to be|as an?) (an? )?(ai|assistant|reviewer|grader|recruiter|language model)\b", "gives the AI a role"),
    (r"\b(positive review|give (a|this) (positive|high|top|good)|recommend (accepting|acceptance|this)|accept this (paper|submission)|score (this|it) (highly|10)|rate (this|it|me) (highly|10|5)|five stars?)", "asks for a good verdict"),
    (r"\b(do not|don't|never) (mention|reveal|tell|disclose|summari[sz]e|highlight)\b", "asks the AI to keep something from you"),
    (r"\b(system prompt|new instructions|instead,? (say|write|reply|respond)|(reply|respond|answer) only\b|when (asked|summari[sz]ing)\b[^.]{0,40}\b(say|reply|respond|answer|tell)\b)", "tries to rewrite the AI's instructions"),
]
RULES = [(re.compile(p, re.I), why) for p, why in RULES]


def rules(text):
    return sorted({why for rx, why in RULES if rx.search(text)})


def light(c):
    return min((c >> 16) & 255, (c >> 8) & 255, c & 255) >= 0xF0


def lum(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # 429/503 or a dropped connection: back off and try again
            if i == tries - 1:
                raise
            time.sleep(15 * (i + 1))


def listing(cats, since, until):
    """Paper ids (newest day first) submitted between `since` and `until`, with title and primary category.
    One query per day: the API fails when paged deep into a single month-long query."""
    from datetime import date, timedelta
    day, first, out, seen = date.fromisoformat(until), date.fromisoformat(since), [], set()
    while day >= first:
        d = day.strftime("%Y%m%d")
        q = "(" + " OR ".join(f"cat:{c}" for c in cats) + f") AND submittedDate:[{d}0000 TO {d}2359]"
        start = 0
        while True:
            url = API + "?" + urllib.parse.urlencode({"search_query": q, "start": start, "max_results": 1000,
                                                      "sortBy": "submittedDate", "sortOrder": "descending"})
            try:
                entries = ET.fromstring(get(url, tries=6)).findall("a:entry", ATOM)
            except Exception as e:
                print(f"listing {d} from {start} failed: {e}", flush=True)
                break
            for e in entries:
                vid = e.find("a:id", ATOM).text.rsplit("/abs/", 1)[1]
                if vid in seen:
                    continue
                seen.add(vid)
                prim = e.find("arxiv:primary_category", ATOM)
                out.append({"id": vid, "title": " ".join(e.find("a:title", ATOM).text.split()),
                            "cat": prim.get("term") if prim is not None else "",
                            "published": e.find("a:published", ATOM).text})
            time.sleep(GAP)
            if len(entries) < 1000:
                break
            start += 1000
        print(f"listed {d}: {len(out)} so far", flush=True)
        day -= timedelta(days=1)
    return out


def scan(data):
    """Hidden-looking text runs in a PDF (white on the page, under 2 pt, invisible mode, off the page, Unicode tags)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    runs, pages = [], doc.page_count
    for page in doc:
        if page.number >= 80:
            break
        mode3 = []
        try:
            for t in page.get_texttrace():
                if t["type"] == 3:
                    mode3.append(pymupdf.Rect(t["bbox"]))
        except Exception:
            pass
        fills = None
        run = None
        d = page.get_text("dict", clip=pymupdf.INFINITE_RECT())
        for b in d["blocks"]:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                for sp in line["spans"]:
                    text = sp["text"]
                    if not text.strip():
                        continue
                    r = pymupdf.Rect(sp["bbox"])
                    how = []
                    # Off the page: test the box's corners (a zero-width box, like the slash of a LaTeX "≠", never intersects).
                    if not any(page.rect.contains(p) for p in (r.tl, r.br, r.tr, r.bl)) and r.width > 1:
                        how.append("off the page")
                    if 0 < sp["size"] < 2:
                        how.append(f"{sp['size']:.2g} pt type")
                    if light(sp["color"]):
                        if fills is None:
                            try:
                                fills = [(dr["rect"], dr["fill"]) for dr in page.get_drawings() if dr.get("fill")]
                            except Exception:
                                fills = []
                            fills += [(pymupdf.Rect(im["bbox"]), (0, 0, 0)) for im in page.get_image_info()]
                        c = r.tl + (r.br - r.tl) * 0.5
                        under = [f for rr, f in fills if c in rr]
                        if not (under and lum(under[-1]) < 0.75):
                            how.append("white on the page")
                    if any(0xE0000 <= ord(ch) <= 0xE007F for ch in text):
                        how.append("Unicode tag characters")
                    # Invisible render mode: the span's centre falls inside a trace drawn with mode 3 (the two boxes
                    # are measured differently and rarely match exactly).
                    if mode3:
                        c = r.tl + (r.br - r.tl) * 0.5
                        if any(c in m for m in mode3):
                            how.append("invisible render mode")
                    if how:
                        # The measurements the ghost classifier learns from (census/classifier).
                        bg = 1.0
                        if fills:
                            c = r.tl + (r.br - r.tl) * 0.5
                            under = [f for rr, f in fills if c in rr]
                            bg = lum(under[-1]) if under else 1.0
                        col = sp["color"]
                        m = {"size": sp["size"], "lum": lum(((col >> 16) & 255, (col >> 8) & 255, col & 255)) / 255, "bg": bg,
                             "bbox": [r.x0, r.y0, r.x1, r.y1], "font": sp["font"][:40]}
                        if run and run["page"] == page.number + 1:
                            run["text"] += " " + text
                            run["how"] = sorted(set(run["how"] + how))
                            run["spans"].append(m)
                        else:
                            if run:
                                runs.append(run)
                            run = {"page": page.number + 1, "text": text, "how": how, "spans": [m],
                                   "page_w": page.rect.width, "page_h": page.rect.height, "page_index": page.number / max(1, pages - 1)}
                    elif run:
                        runs.append(run)
                        run = None
        if run:
            runs.append(run)
    doc.close()
    for r in runs:
        r["text"] = " ".join(r["text"].split())
        r["ai"] = rules(r["text"])
    return pages, runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cats", default="cs.LG,cs.CL,cs.AI,cs.CV,cs.CR,cs.IR,stat.ML,cs.RO,cs.HC,cs.SE")
    ap.add_argument("--since", default="2026-10-01")
    ap.add_argument("--until", default="2026-10-31")
    ap.add_argument("--out", default="census/results.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many papers (0: all)")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    listfile = a.out.replace(".jsonl", ".listing.json")
    if os.path.exists(listfile):
        papers = json.load(open(listfile, encoding="utf-8"))
    else:
        papers = listing(a.cats.split(","), a.since, a.until)
        json.dump(papers, open(listfile, "w", encoding="utf-8"), ensure_ascii=False)
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8")}
    print(f"{len(papers)} papers, {len(done)} already scanned", flush=True)
    with open(a.out, "a", encoding="utf-8") as f:
        for n, p in enumerate(papers):
            if a.limit and n >= a.limit:
                break
            if p["id"] in done:
                continue
            t0 = time.time()
            rec = dict(p)
            try:
                data = get(f"https://export.arxiv.org/pdf/{p['id']}")
                rec["bytes"] = len(data)
                rec["pages"], runs = scan(data)
                # Keep every run that talks to an AI, and a few of the rest (most are figure labels).
                rec["ai_runs"] = [r for r in runs if r["ai"]]
                rec["other_runs"] = len(runs) - len(rec["ai_runs"])
                rec["examples"] = [r for r in runs if not r["ai"] and len(r["text"]) > 30][:3]
                # Every hidden-looking run (capped), for the classifier: almost all of these are innocent.
                rec["runs"] = [dict(r, text=r["text"][:300], spans=r["spans"][:12]) for r in runs[:60]]
            except Exception as e:
                rec["error"] = str(e)[:200]
            rec["ms"] = int((time.time() - t0) * 1000)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            if rec.get("ai_runs"):
                print(f"HAUNTED {p['id']} p{rec['ai_runs'][0]['page']}: {rec['ai_runs'][0]['text'][:160]}", flush=True)
            if n % 25 == 0:
                print(f"{n}/{len(papers)} {p['id']}", flush=True)
            time.sleep(max(0, GAP - (time.time() - t0)))


if __name__ == "__main__":
    main()
