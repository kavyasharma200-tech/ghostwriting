"""Turns census/classifier/report.json into site/classifier.json for the evidence section.

    python tools/classifier_site.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "census" / "classifier" / "report.json").read_text(encoding="utf-8"))
h = r["test2_heldout_wordings"]
langs = {"hi": "Hindi", "zh": "Chinese", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese"}
rows = [
    {"label": "Disguised instructions it never saw", "n": h["heldout_all"]["n"], "tabpfn": h["heldout_all"]["tabpfn"], "rules": h["heldout_all"]["rules"]},
    {"label": "…of which use none of the usual keywords", "n": h["heldout_keyword_free"]["n"], "tabpfn": h["heldout_keyword_free"]["tabpfn"], "rules": h["heldout_keyword_free"]["rules"]},
]
other = [(k, v) for k, v in h.get("heldout_by_lang", {}).items() if k != "en"]
if other:
    n = sum(v["n"] for _, v in other)
    rows.append({"label": "…written in " + ", ".join(langs.get(k, k) for k, _ in other), "n": n,
                 "tabpfn": sum(v["tabpfn"] * v["n"] for _, v in other) / n, "rules": sum(v["rules"] * v["n"] for _, v in other) / n})
real = r.get("test1_real_papers", {})
# The first run was blind to the real papers; keep its result next to the final one.
blind_path = ROOT / "census" / "classifier" / "cache" / "report_run1.json"
blind = json.loads(blind_path.read_text(encoding="utf-8"))["test1_real_papers"] if blind_path.exists() else {}
hn = h.get("hard_negative_fpr", {})
out = {
    "model": f'TabPFN-{r["model"]["version"].lstrip("v")}',
    "trainRows": r["data"]["train_rows"],
    "rows": rows,
    "real": {"papers": real.get("papers"), "recall": real.get("paper_recall_tabpfn"),
             "blindRecall": blind.get("paper_recall_tabpfn")},
    "hardNegativeRules": hn.get("rules") if isinstance(hn, dict) else None,
    "hardNegativeFpr": h.get("hard_negative_fpr_at_0.5", {}).get("tabpfn"),
    "hardNegatives": h.get("hard_negative_fpr_at_0.5", {}).get("n"),
}
(ROOT / "site" / "classifier.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
