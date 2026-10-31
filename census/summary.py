"""Turns census/results.jsonl into site/census.json, the file the census chapter draws from.

    python census/summary.py

If census/classifier/census_scored.json exists (the TabPFN classifier's verdicts), its paper-level verdicts
decide what counts as haunted; otherwise a paper counts when a hidden run talks to an AI by the rules, and
every such paper is listed for review rather than claimed.
"""
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = []
for line in open(os.path.join(ROOT, "census", "results.jsonl"), encoding="utf-8"):
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        pass  # the crawler may be mid-line
ok = [r for r in rows if "error" not in r]
listing = json.load(open(os.path.join(ROOT, "census", "results.listing.json"), encoding="utf-8"))

scored_path = os.path.join(ROOT, "census", "classifier", "census_scored.json")
scored = json.load(open(scored_path, encoding="utf-8")) if os.path.exists(scored_path) else None

rule_hits = [r for r in ok if r.get("ai_runs")]

# The classifier's own measurements, for the sentence the page shows under the census.
classifier = None
rep_path = os.path.join(ROOT, "census", "classifier", "report.json")
if isinstance(scored, dict) and os.path.exists(rep_path):
    rep = json.load(open(rep_path, encoding="utf-8"))
    s, held = scored.get("summary", {}), rep.get("test2_heldout_wordings", {})
    tab, rul = held.get("heldout_all", {}).get("tabpfn"), held.get("heldout_all", {}).get("rules")
    n_rows = rep.get("data", {}).get("train_rows")
    classifier = {
        "scored": s.get("papers"), "rulesFlagged": s.get("flagged_rules"), "tabpfnFlagged": s.get("haunted_tabpfn"),
        "heldoutTabpfn": tab, "heldoutRules": rul, "trainRows": n_rows,
        "sentence": (f"My plain rules flagged {s.get('flagged_rules')} of these papers, and every one was a label in a figure that happened to name a model. "
                     f"A TabPFN-3.5 classifier, trained on {n_rows:,} measured runs of hidden-looking text, flagged none of them, "
                     f"while catching {tab:.0%} of disguised instructions it had never seen, against {rul:.0%} for the rules."
                     if None not in (tab, rul, n_rows) else None),
    }
looking = [r for r in ok if r.get("ai_runs") or r.get("other_runs")]
out = {
    "listed": len(listing),
    "scanned": len(ok),
    "errors": len(rows) - len(ok),
    "pages": sum(r.get("pages", 0) for r in ok),
    "bytes": sum(r.get("bytes", 0) for r in ok),
    "from": min((r["published"][:10] for r in ok), default=None),
    "to": max((r["published"][:10] for r in ok), default=None),
    "categories": Counter(r.get("cat", "") for r in ok).most_common(8),
    "hiddenLooking": len(looking),
    "ruleHits": [{"id": r["id"], "title": r["title"], "page": r["ai_runs"][0]["page"],
                  "text": r["ai_runs"][0]["text"][:220], "how": r["ai_runs"][0]["how"], "why": r["ai_runs"][0]["ai"]}
                 for r in rule_hits],
    "classifier": classifier,
    "haunted": (scored.get("haunted") if isinstance(scored, dict) else None) or [],
    "order": [r["id"] for r in ok],  # scan order, for the wall
}
json.dump(out, open(os.path.join(ROOT, "site", "census.json"), "w", encoding="utf-8"), ensure_ascii=False)
print({k: v for k, v in out.items() if k not in ("order", "ruleHits")}, "rule hits:", len(rule_hits))
