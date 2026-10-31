"""Adds one day of Ghost Watch results to site/census-daily.json (the last 60 days are kept).

    python census/daily.py census/day.jsonl 2026-10-31

Run by .github/workflows/ghost-watch.yml after census/crawl.py has read that day's papers.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src, day = sys.argv[1], sys.argv[2]
rows = []
for line in open(src, encoding="utf-8"):
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        pass
ok = [r for r in rows if "error" not in r]
entry = {
    "day": day,
    "read": len(ok),
    "pages": sum(r.get("pages", 0) for r in ok),
    "errors": len(rows) - len(ok),
    # Papers where a hidden run talks to an AI by the rules: listed for a human to check, not claimed.
    "flagged": [{"id": r["id"], "title": r["title"], "page": r["ai_runs"][0]["page"], "text": r["ai_runs"][0]["text"][:220],
                 "how": r["ai_runs"][0]["how"]} for r in ok if r.get("ai_runs")],
}
path = os.path.join(ROOT, "site", "census-daily.json")
days = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
days = [d for d in days if d["day"] != day] + [entry]
days = sorted(days, key=lambda d: d["day"])[-60:]
json.dump(days, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(entry["day"], entry["read"], "papers,", len(entry["flagged"]), "flagged")
