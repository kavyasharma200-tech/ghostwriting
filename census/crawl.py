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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ghostwriting.scanner import rules, scan  # the scanner the command line and the MCP server use too  # noqa: F401

sys.stdout.reconfigure(encoding="utf-8")
UA = "Ghostwriting-census/1.0 (https://github.com/kavyasharma200-tech/ghostwriting)"
API = "https://export.arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
GAP = 3.1


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
