# -*- coding: utf-8 -*-
"""Score hidden-looking runs with the ghost classifier (hosted TabPFN v3.5, in-context on the training rows).

    from score import score_runs
    probs = score_runs(runs)          # runs from census/crawl.py scan(); returns P(deliberate instruction to an AI)

    python score.py                   # re-scores census/results.jsonl -> census/classifier/census_scored.json

The training set is every labelled row in cache/rows.jsonl (synthetic, clean, planted, real, census with the same
per-paper cap and stratified subsample as evaluate.py); rows set aside for human review are never trained on.
Runs that carry span measurements use the full feature set. Census lines written before the crawler stored spans
(only `ai_runs`/`examples`) are scored by a second fit on the features that do not need spans, and are marked
`partial_features` in the output.
"""
import argparse
import json
import os
import random
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CACHE, CENSUS, MODEL_VERSION, load_crawl, tabpfn_classifier  # noqa: E402
import features as F  # noqa: E402

SPAN_FEATURES = {"size_min", "size_mean", "size_max", "size_lt_05", "size_lt_2", "lum_min", "lum_mean", "lum_max",
                 "bg_min", "bg_mean", "contrast_min", "contrast_mean", "x0", "y0", "x1", "y1", "w", "h", "area",
                 "outside", "n_spans", "n_fonts", "aspect", "sym_font"}
NOSPAN_IDX = [i for i, k in enumerate(F.FEATURES) if k not in SPAN_FEATURES]
DEFAULT_THRESHOLD = 0.5
# The production model uses the numeric features only (it beat the raw-text-column variant on the real papers, see
# REPORT.md, and only numbers leave the machine). GHOST_TEXT=1 adds the run's raw text as a string column, which
# TabPFN v3.5 embeds natively on the server.
USE_TEXT = os.environ.get("GHOST_TEXT") == "1"
_fit = {}


def threshold():
    try:
        rep = "report_text.json" if USE_TEXT else "report.json"
        return float(json.load(open(os.path.join(HERE, rep), encoding="utf-8"))["cv"]["threshold"])
    except Exception:
        return DEFAULT_THRESHOLD


def design(runs, cols):
    X = F.matrix(runs)[:, cols]
    if not USE_TEXT:
        return X
    import pandas as pd
    d = pd.DataFrame(X, columns=[F.FEATURES[i] for i in cols])
    d["text"] = [F.detag(r.get("text") or "") for r in runs]
    return d


def training_rows(seed=7):
    from evaluate import subsample_census
    rows = [json.loads(l) for l in open(os.path.join(CACHE, "rows.jsonl"), encoding="utf-8")]
    lab = [r for r in rows if r["label"] is not None]
    census = [r for r in lab if r["source"] == "census"]
    return [r for r in lab if r["source"] != "census"] + subsample_census(census, random.Random(seed))


def _model(view):
    if view not in _fit:
        tr = training_rows()
        y = np.array([r["label"] for r in tr])
        X = design(tr, NOSPAN_IDX if view == "nospan" else list(range(len(F.FEATURES))))
        clf = tabpfn_classifier(random_state=7)
        clf.fit(X, y)
        _fit[view] = (clf, len(tr), int(y.sum()))
    return _fit[view][0]


def score_runs(runs):
    """P(run is a deliberately hidden instruction for an AI) for each run, in order."""
    if not runs:
        return []
    has = np.array([bool(r.get("spans")) for r in runs])
    out = np.zeros(len(runs))
    full = [r for r, h in zip(runs, has) if h]
    part = [r for r, h in zip(runs, has) if not h]
    if full:
        out[has] = _model("full").predict_proba(design(full, list(range(len(F.FEATURES)))))[:, 1]
    if part:
        out[~has] = _model("nospan").predict_proba(design(part, NOSPAN_IDX))[:, 1]
    return [float(p) for p in out]


def read_census(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:  # the crawler may be mid-write on the last line
                continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", default=CENSUS)
    ap.add_argument("--out", default=os.path.join(HERE, "census_scored.json"))
    ap.add_argument("--top", type=int, default=3)
    a = ap.parse_args()
    crawl = load_crawl()
    thr = threshold()
    t0 = time.time()
    papers, flat = [], []
    train_docs = {r["doc"] for r in training_rows() if r["source"] == "census"}
    for rec in read_census(a.census):
        if "error" in rec:
            papers.append(dict(id=rec["id"], title=rec.get("title"), error=rec["error"]))
            continue
        partial = "runs" not in rec
        runs = rec["runs"] if not partial else (rec.get("ai_runs", []) + rec.get("examples", []))
        p = dict(id=rec["id"], title=rec.get("title"), cat=rec.get("cat"), pages=rec.get("pages"),
                 n_runs=len(runs) if not partial else rec.get("other_runs", 0) + len(rec.get("ai_runs", [])),
                 partial_features=partial, in_training=f"census:{rec['id']}" in train_docs)
        papers.append(p)
        for r in runs:
            flat.append((p, r))
    print(f"{len(papers)} papers, {len(flat)} runs to score", flush=True)
    probs = score_runs([r for _, r in flat])
    for (p, r), pr in zip(flat, probs):
        p.setdefault("_runs", []).append(dict(page=r.get("page"), text=r["text"][:300], how=r.get("how"),
                                              rules=crawl.rules(r["text"]), p=round(pr, 4)))
    n = dict(papers=len(papers), errors=0, with_runs=0, haunted_tabpfn=0, flagged_rules=0, rules_only=0, tabpfn_only=0)
    for p in papers:
        if "error" in p:
            n["errors"] += 1
            continue
        rs = sorted(p.pop("_runs", []), key=lambda d: -d["p"])
        p["max_p"] = rs[0]["p"] if rs else 0.0
        p["rules_flag"] = any(d["rules"] for d in rs)
        p["verdict"] = "haunted" if p["max_p"] >= thr else ("hidden-looking, innocent" if rs else "clean")
        p["top_runs"] = rs[:a.top]
        n["with_runs"] += bool(rs)
        n["haunted_tabpfn"] += p["verdict"] == "haunted"
        n["flagged_rules"] += p["rules_flag"]
        n["rules_only"] += p["rules_flag"] and p["verdict"] != "haunted"
        n["tabpfn_only"] += p["verdict"] == "haunted" and not p["rules_flag"]
    papers.sort(key=lambda p: -(p.get("max_p") or 0))
    out = dict(model=dict(name="TabPFN (hosted)" + (" + raw text column" if USE_TEXT else ""), version=MODEL_VERSION,
                          threshold=thr,
                          trained_rows=_fit.get("full", _fit.get("nospan", (None, None)))[1]),
               generated=time.strftime("%Y-%m-%d %H:%M:%S"), seconds=round(time.time() - t0), summary=n,
               haunted=[p for p in papers if p.get("verdict") == "haunted"],
               rules_only=[p for p in papers if p.get("rules_flag") and p.get("verdict") != "haunted"],
               papers=papers,
               notes=["verdict 'haunted' = at least one run with P >= threshold",
                      "partial_features: census line written before spans were stored; scored on text/how/page only",
                      "in_training: this paper's runs were in-context negatives for the model (its score is biased low);"
                      " runs set aside for human review never are"])
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(n), "->", a.out)


if __name__ == "__main__":
    main()
