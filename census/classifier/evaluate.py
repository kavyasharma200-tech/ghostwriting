# -*- coding: utf-8 -*-
"""Evaluate the ghost classifier (hosted TabPFN v3.5) against the deployed regex rules.

    python evaluate.py        # needs cache/rows.jsonl from dataset.py; writes report.json and REPORT.md

Splits are by DOCUMENT: a clean paper's synthetic rows are either all train or all test; census papers are split by a
hash of their id; the 16 real papers are never trained on in tests 1-3.

  threshold  4-fold GroupKFold (by document) on the training rows -> out-of-fold probabilities -> the threshold with
             the best F1. That threshold is then used everywhere.
  test 1     real 2025 papers held out: run- and paper-level recall (and a strict variant that also drops the
             synthetic wordings copied from those papers).
  test 2     test-document injections with HELD-OUT wordings (incl. keyword-free English and 7 languages): recall,
             TabPFN vs rules; and the false-positive rate on test-document hard negatives.
  test 3     paper-level false alarms on clean + census papers never used in training (+ the ATLAS-Bench paper that
             the live census flagged for model names in 1.2 pt figure labels); plus a cross-fitted pass over every census
             paper with span data (5 folds by paper) and the older census lines without spans (scored by a no-span fit).
  flags      --text adds the raw text as a TabPFN string column; --seed N re-runs with another random_state.
A gradient-boosting model on the same features is reported as a reference, clearly labelled.
"""
import json
import os
import random
import sys
import time
import zlib
from collections import Counter, defaultdict

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CACHE, MODEL_VERSION, load_crawl, tabpfn_classifier  # noqa: E402
import features as F  # noqa: E402

crawl = load_crawl()
SEED = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
# --text: also hand TabPFN the run's raw text as a column (TabPFN v3.5 embeds text features natively on the server).
TEXT = "--text" in sys.argv
OUT = ("report_text" if TEXT else "report") + (f"_seed{SEED}" if SEED != 7 else "") + ".json"
if SEED != 7:
    OUT = os.path.join("cache", OUT)  # robustness re-runs stay out of the way


def design(rs):
    """The model's input: the numeric features, plus the decoded text as a string column in --text mode."""
    X = F.matrix(rs)
    if not TEXT:
        return X
    import pandas as pd
    d = pd.DataFrame(X, columns=F.FEATURES)
    d["text"] = [F.detag(r["text"]) for r in rs]
    return d


def take(X, idx):
    return X.iloc[idx].reset_index(drop=True) if hasattr(X, "iloc") else X[idx]
CENSUS_NEG_CAP_PER_PAPER = 15
CENSUS_NEG_MAX = 2500


def load_rows():
    rows = [json.loads(l) for l in open(os.path.join(CACHE, "rows.jsonl"), encoding="utf-8")]
    atlas = json.load(open(os.path.join(CACHE, "atlas_runs.json"), encoding="utf-8"))
    for r in atlas["runs"]:
        rows.append(dict(r, source="atlas", doc=f"census:{atlas['id']}", split="atlas", label=0, n_pages=atlas["pages"]))
    return rows


def old_census():
    """Census lines written before the crawler stored spans: only `ai_runs` (rule hits) and up to 3 `examples` per
    paper survive, without span measurements. Never used in training. Returns (rows, n_papers)."""
    from dataset import read_census
    rows, n = [], 0
    for rec in read_census():
        if "runs" in rec or "error" in rec:
            continue
        n += 1
        for r in rec.get("ai_runs", []) + rec.get("examples", []):
            rows.append(dict(r, spans=[], source="census_old", doc=f"census:{rec['id']}", split="old", label=0))
    return rows, n


def rules_flag(r):
    """The deployed baseline: a run 'talks to an AI' when any regex rule hits its text (as the census stores it)."""
    return bool(crawl.rules(r["text"]))


def how_bucket(r):
    h = " ".join(r.get("how", []))
    return ("tiny" if " pt type" in h else "") + ("white" if "white" in h else "") + ("off" if "off the" in h else "") \
        + ("inv" if "invisible" in h else "") + ("tag" if "tag" in h else "")


def subsample_census(rows, rng):
    """Stratified cap on census negatives: at most N runs per paper (one paper can hold 60 near-identical labels),
    then at most CENSUS_NEG_MAX overall, sampled proportionally within each 'how' bucket."""
    by_paper = defaultdict(list)
    for r in rows:
        by_paper[r["doc"]].append(r)
    kept = []
    for doc, rs in by_paper.items():
        rng.shuffle(rs)
        kept += rs[:CENSUS_NEG_CAP_PER_PAPER]
    if len(kept) <= CENSUS_NEG_MAX:
        return kept
    buckets = defaultdict(list)
    for r in kept:
        buckets[how_bucket(r)].append(r)
    out = []
    for b, rs in buckets.items():
        k = max(1, round(len(rs) * CENSUS_NEG_MAX / len(kept)))
        out += rng.sample(rs, min(k, len(rs)))
    return out


def prf(y, p):
    y, p = np.asarray(y, bool), np.asarray(p, bool)
    tp, fp, fn, tn = int((y & p).sum()), int((~y & p).sum()), int((y & ~p).sum()), int((~y & ~p).sum())
    pr = tp / (tp + fp) if tp + fp else None
    rc = tp / (tp + fn) if tp + fn else None
    f1 = 2 * pr * rc / (pr + rc) if pr and rc else (0.0 if pr is not None and rc is not None else None)
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=pr, recall=rc, f1=f1, n=len(y))


def fit_predict(Xtr, ytr, Xte, tries=3):
    last = None
    for i in range(tries):
        try:
            clf = tabpfn_classifier(random_state=SEED)
            clf.fit(Xtr, ytr)
            return clf.predict_proba(Xte)[:, 1]
        except Exception as e:  # network / quota: retry, then fail loudly
            last = e
            print(f"TabPFN call failed ({type(e).__name__}: {str(e)[:200]}), retry {i + 1}", flush=True)
            time.sleep(10 * (i + 1))
    raise last


def gbm_predict(Xtr, ytr, Xte):
    from sklearn.ensemble import HistGradientBoostingClassifier
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=.05, random_state=SEED)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def snippet(r, p=None):
    d = dict(source=r["source"], doc=r["doc"], page=r.get("page"), how=r.get("how"), text=r["text"][:160])
    for k in ("technique", "kind", "group", "lang", "wid"):
        if r.get(k) is not None:
            d[k] = r[k]
    if p is not None:
        d["p"] = round(float(p), 3)
    d["rules"] = crawl.rules(r["text"])
    return d


def paper_level(rows, probs, thr):
    """{doc: (tabpfn_flag, rules_flag, max_p)} - a paper is flagged when any of its runs is."""
    out = {}
    for r, p in zip(rows, probs):
        t, rl, mp = out.get(r["doc"], (False, False, 0.0))
        out[r["doc"]] = (t or p >= thr, rl or rules_flag(r), max(mp, float(p)))
    return out


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    rows = load_rows()
    review = [r for r in rows if r["label"] is None]
    lab = [r for r in rows if r["label"] is not None]
    census_tr = [r for r in lab if r["source"] == "census" and r["split"] == "train"]
    census_tr_s = subsample_census(census_tr, rng)
    train = [r for r in lab if r["split"] == "train" and r["source"] != "census"] + census_tr_s
    real = [r for r in lab if r["source"] == "real"]
    synth_test = [r for r in lab if r["source"] == "synth" and r["split"] == "test"]
    clean_test = [r for r in lab if r["source"] == "clean" and r["split"] == "test"]
    census_te = [r for r in rows if r["source"] == "census" and r["split"] == "test"]  # incl. review rows
    atlas = [r for r in rows if r["source"] == "atlas"]
    print(f"rows {len(rows)} | train {len(train)} ({sum(r['label'] for r in train)} pos) | real {len(real)} | "
          f"synth-test {len(synth_test)} | clean-test {len(clean_test)} | census-test {len(census_te)} | "
          f"review {len(review)}", flush=True)

    Xtr, ytr = F.matrix(train), np.array([r["label"] for r in train])
    Dtr = design(train)
    groups = np.array([r["doc"] for r in train])

    # ---- threshold from out-of-fold predictions (GroupKFold by document)
    from sklearn.model_selection import GroupKFold
    from concurrent.futures import ThreadPoolExecutor
    oof = np.zeros(len(train))
    oof_gbm = np.zeros(len(train))
    folds = list(GroupKFold(n_splits=4).split(Xtr, ytr, groups))
    # The hosted calls are independent: run the 4 folds, the main fit and the strict fit concurrently.
    tests_all = real + synth_test + clean_test + census_te + atlas + review
    strict_tr = [i for i, r in enumerate(train) if not r.get("real_like")]
    with ThreadPoolExecutor(6) as ex:
        fut_folds = [ex.submit(fit_predict, take(Dtr, a), ytr[a], take(Dtr, b)) for a, b in folds]
        fut_main = ex.submit(fit_predict, Dtr, ytr, design(tests_all))
        fut_strict = ex.submit(fit_predict, take(Dtr, strict_tr), ytr[strict_tr], design(real))
        old_rows, old_n = old_census()
        from score import NOSPAN_IDX
        # Cross-fitted census: 5 folds over ALL census papers with span data; each fold's papers are scored by a
        # model trained without any of their runs, so every census paper gets an unseen-paper verdict.
        census_all = [r for r in rows if r["source"] == "census"]
        cpapers = sorted({r["doc"] for r in census_all})
        fold_of = {d: zlib.crc32(d.encode()) % 5 for d in cpapers}
        base_tr = [r for r in train if r["source"] != "census"]
        fut_cf = []
        for k in range(5):
            tr_k = base_tr + subsample_census([r for r in census_all if fold_of[r["doc"]] != k and r["label"] is not None],
                                              random.Random(SEED + k))
            te_k = [r for r in census_all if fold_of[r["doc"]] == k]
            if te_k:
                fut_cf.append((te_k, ex.submit(fit_predict, design(tr_k), np.array([r["label"] for r in tr_k]), design(te_k))))
        fut_old = ex.submit(fit_predict, Xtr[:, NOSPAN_IDX], ytr, F.matrix(old_rows)[:, NOSPAN_IDX]) if old_rows else None
        for (a, b), fu in zip(folds, fut_folds):
            oof[b] = fu.result()
            oof_gbm[b] = gbm_predict(Xtr[a], ytr[a], Xtr[b])
        p_all_main, p_strict_main = fut_main.result(), fut_strict.result()
        p_old = fut_old.result() if fut_old else np.zeros(0)
        cf_rows, cf_p = [], []
        for te_k, fu in fut_cf:
            cf_rows += te_k
            cf_p += list(fu.result())
    print("hosted calls done", flush=True)
    cands = np.round(np.arange(.05, .96, .01), 2)

    def plateau(f1s):
        """Midpoint of the thresholds whose OOF F1 is within 0.002 of the best (the curve is flat near the top)."""
        best = max(f1s)
        ok = [c for c, f in zip(cands, f1s) if f >= best - .002]
        return float(np.round((min(ok) + max(ok)) / 2, 2))
    f1s = [prf(ytr, oof >= c)["f1"] or 0 for c in cands]
    thr = plateau(f1s)
    f1s_g = [prf(ytr, oof_gbm >= c)["f1"] or 0 for c in cands]
    thr_g = plateau(f1s_g)
    rules_tr = np.array([rules_flag(r) for r in train])
    from sklearn.metrics import roc_auc_score
    cv = dict(threshold=thr, tabpfn=prf(ytr, oof >= thr), tabpfn_at_05=prf(ytr, oof >= .5), rules=prf(ytr, rules_tr),
              gbm_reference=dict(prf(ytr, oof_gbm >= thr_g), threshold=thr_g),
              tabpfn_auc=roc_auc_score(ytr, oof), gbm_auc=roc_auc_score(ytr, oof_gbm))
    print("CV", json.dumps(cv, default=str), flush=True)

    # ---- one fit on all training rows, predicted on every test set at once
    tests = tests_all
    Xte = F.matrix(tests)
    p_all = p_all_main
    g_all = gbm_predict(Xtr, ytr, Xte)
    P = {id(r): p for r, p in zip(tests, p_all)}
    G = {id(r): p for r, p in zip(tests, g_all)}

    # ---- test 1: real papers
    def block(rs, name):
        y = [r["label"] for r in rs]
        pt = [P[id(r)] >= thr for r in rs]
        pg = [G[id(r)] >= thr_g for r in rs]
        pr = [rules_flag(r) for r in rs]
        return dict(name=name, tabpfn=prf(y, pt), rules=prf(y, pr), gbm_reference=prf(y, pg))

    t1 = block(real, "real papers, run level")
    pl = paper_level(real, [P[id(r)] for r in real], thr)
    real_docs = sorted(pl)
    t1["papers"] = len(real_docs)
    t1["paper_recall_tabpfn"] = sum(pl[d][0] for d in real_docs) / len(real_docs)
    t1["paper_recall_rules"] = sum(pl[d][1] for d in real_docs) / len(real_docs)
    t1["paper_recall_tabpfn_at_0.5"] = sum(pl[d][2] >= .5 for d in real_docs) / len(real_docs)
    t1["per_paper"] = {d: dict(tabpfn=bool(pl[d][0]), rules=bool(pl[d][1]), max_p=round(pl[d][2], 3)) for d in real_docs}
    # strict: no synthetic wording copied from the real papers in training
    p_strict = p_strict_main
    pls = paper_level(real, p_strict, thr)
    t1["strict_no_real_like_wordings"] = dict(
        run=prf([r["label"] for r in real], p_strict >= thr),
        paper_recall=sum(pls[d][0] for d in real_docs) / len(real_docs),
        dropped_training_rows=len(train) - len(strict_tr))
    print("T1", json.dumps({k: v for k, v in t1.items() if k != "per_paper"}, default=str), flush=True)

    # ---- test 2: held-out wordings on test documents
    held = [r for r in synth_test if r["label"] == 1 and r.get("wsplit") == "heldout"]
    seen = [r for r in synth_test if r["label"] == 1 and r.get("wsplit") == "train"]
    hneg = [r for r in synth_test if r["label"] == 0]

    def recall(rs):
        n = len(rs)
        return dict(n=n, tabpfn=sum(P[id(r)] >= thr for r in rs) / n if n else None,
                    rules=sum(rules_flag(r) for r in rs) / n if n else None,
                    gbm_reference=sum(G[id(r)] >= thr_g for r in rs) / n if n else None)

    t2 = dict(heldout_all=recall(held), seen_wordings_on_test_docs=recall(seen))
    t2["heldout_all_at_0.5"] = dict(n=len(held), tabpfn=sum(P[id(r)] >= .5 for r in held) / max(1, len(held)))
    t2["hard_negative_fpr_at_0.5"] = dict(n=len(hneg), tabpfn=sum(P[id(r)] >= .5 for r in hneg) / max(1, len(hneg)))
    t2["heldout_keyword_free"] = recall([r for r in held if not crawl.rules(r["text"])])
    t2["heldout_with_keywords"] = recall([r for r in held if crawl.rules(r["text"])])
    t2["heldout_by_lang"] = {l: recall([r for r in held if r["lang"] == l]) for l in sorted({r["lang"] for r in held})}
    t2["heldout_by_group"] = {g: recall([r for r in held if r["group"] == g]) for g in sorted({r["group"] for r in held})}
    t2["heldout_by_technique"] = {t: recall([r for r in held if r["technique"] == t])
                                  for t in sorted({r["technique"] for r in held})}

    def fpr(rs):
        n = len(rs)
        return dict(n=n, tabpfn=sum(P[id(r)] >= thr for r in rs) / n if n else None,
                    rules=sum(rules_flag(r) for r in rs) / n if n else None,
                    gbm_reference=sum(G[id(r)] >= thr_g for r in rs) / n if n else None)

    t2["hard_negative_fpr"] = fpr(hneg)
    t2["hard_negative_fpr_by_kind"] = {k: fpr([r for r in hneg if r["kind"] == k]) for k in sorted({r["kind"] for r in hneg})}
    t2["all_test_doc_rows"] = block(synth_test + clean_test, "test documents, all runs")
    print("T2", json.dumps(t2["heldout_all"]), json.dumps(t2["heldout_keyword_free"]), json.dumps(t2["hard_negative_fpr"]), flush=True)

    # ---- test 3: paper-level false alarms on unseen clean + census papers
    papers = json.load(open(os.path.join(CACHE, "census_papers.json"), encoding="utf-8"))
    census_test_ids = [f"census:{p['id']}" for p in papers if p["split"] == "test"]
    clean_test_ids = sorted({r["doc"] for r in lab if r["source"] == "synth" and r["split"] == "test"})
    pool = clean_test + census_te
    plv = paper_level(pool, [P[id(r)] for r in pool], thr)
    plg = paper_level(pool, [G[id(r)] for r in pool], thr_g)
    all_ids = clean_test_ids + census_test_ids
    with_runs = [d for d in all_ids if d in plv]
    flag_t = [d for d in all_ids if plv.get(d, (False,))[0]]
    flag_r = [d for d in all_ids if plv.get(d, (False, False))[1]]
    flag_g = [d for d in all_ids if plg.get(d, (False,))[0]]
    t3 = dict(papers=len(all_ids), clean_papers=len(clean_test_ids), census_papers=len(census_test_ids),
              papers_with_any_hidden_looking_run=len(with_runs),
              flagged_tabpfn=len(flag_t), flagged_rules=len(flag_r), flagged_gbm_reference=len(flag_g),
              flagged_tabpfn_ids=flag_t, flagged_rules_ids=flag_r,
              note="Census review rows (text that might be a real instruction) are included here; any flag on them "
                   "is listed under review_rows for a human to judge, so a 'false alarm' may be a true find.")
    t3["runs"] = dict(n=len(pool), tabpfn_flagged=int(sum(P[id(r)] >= thr for r in pool)),
                      rules_flagged=int(sum(rules_flag(r) for r in pool)))
    pa = paper_level(atlas, [P[id(r)] for r in atlas], thr)
    t3["atlas_bench_2610.39438v1"] = dict(
        runs=len(atlas), rules_flagged_runs=sum(rules_flag(r) for r in atlas),
        tabpfn_flagged_runs=int(sum(P[id(r)] >= thr for r in atlas)),
        paper_flagged_rules=any(v[1] for v in pa.values()), paper_flagged_tabpfn=any(v[0] for v in pa.values()),
        rule_hit_runs=[snippet(r, P[id(r)]) for r in atlas if rules_flag(r)])
    pc = paper_level(cf_rows, cf_p, thr)
    n_census = len(json.load(open(os.path.join(CACHE, "census_papers.json"), encoding="utf-8")))
    t3["census_crossfit"] = dict(
        papers=n_census, papers_with_any_hidden_looking_run=len(pc), runs=len(cf_rows),
        flagged_tabpfn=int(sum(bool(v[0]) for v in pc.values())), flagged_rules=int(sum(bool(v[1]) for v in pc.values())),
        runs_flagged_tabpfn=int(sum(p >= thr for p in cf_p)), runs_flagged_rules=int(sum(rules_flag(r) for r in cf_rows)),
        flagged=[snippet(r, p) for r, p in zip(cf_rows, cf_p) if p >= thr or rules_flag(r)],
        top=[snippet(r, p) for r, p in sorted(zip(cf_rows, cf_p), key=lambda t: -t[1])[:8]])
    po = paper_level(old_rows, p_old, thr)
    t3["old_format_census"] = dict(
        papers=old_n, papers_with_listed_runs=len(po), runs=len(old_rows),
        flagged_tabpfn=int(sum(bool(v[0]) for v in po.values())), flagged_rules=int(sum(bool(v[1]) for v in po.values())),
        model="no-span fit (numeric features that do not need span measurements; text/how/page only)",
        flagged=[snippet(r, p) for r, p in zip(old_rows, p_old) if p >= thr or rules_flag(r)])
    print("T3 crossfit", json.dumps({k: v for k, v in t3["census_crossfit"].items() if k not in ("flagged", "top")}), flush=True)
    print("T3", json.dumps({k: v for k, v in t3.items() if not k.endswith("_ids") and k not in ("atlas_bench_2610.39438v1", "old_format_census", "census_crossfit")}, default=str), flush=True)

    # ---- examples
    test_lab = real + synth_test + clean_test + [r for r in census_te if r["label"] is not None] + atlas
    wins = [r for r in test_lab if (P[id(r)] >= thr) == bool(r["label"]) and rules_flag(r) != bool(r["label"])]
    losses = [r for r in test_lab if (P[id(r)] >= thr) != bool(r["label"]) and rules_flag(r) == bool(r["label"])]
    both_wrong = [r for r in test_lab if (P[id(r)] >= thr) != bool(r["label"]) and rules_flag(r) != bool(r["label"])]
    rng.shuffle(wins)
    wins.sort(key=lambda r: (r["source"] not in ("atlas", "census", "clean", "real"), r["label"]))
    ex = dict(n_wins=len(wins), n_losses=len(losses), n_both_wrong=len(both_wrong),
              wins=[dict(snippet(r, P[id(r)]), label=r["label"]) for r in wins[:25]],
              losses=[dict(snippet(r, P[id(r)]), label=r["label"]) for r in losses[:25]],
              both_wrong=[dict(snippet(r, P[id(r)]), label=r["label"]) for r in both_wrong[:15]])
    rv = sorted(review, key=lambda r: -P[id(r)])
    review_out = [dict(snippet(r, P[id(r)]), flagged_tabpfn=bool(P[id(r)] >= thr), split=r["split"]) for r in rv]

    sizes = Counter(f"{r['source']}:{r['label']}" for r in rows)
    report = dict(
        model=dict(name="TabPFN (hosted, tabpfn-client)" + (" + raw text column" if TEXT else ""), version=MODEL_VERSION,
                   text_column=TEXT, model_path=f"{MODEL_VERSION}_default",
                   n_features=len(F.FEATURES), features=F.FEATURES, threshold=thr, random_state=SEED),
        data=dict(rows_by_source_label=dict(sorted(sizes.items())), train_rows=len(train),
                  train_pos=int(ytr.sum()), train_neg=int(len(ytr) - ytr.sum()),
                  census_train_negatives_before_subsample=len(census_tr), census_train_negatives_used=len(census_tr_s),
                  subsample=f"census negatives: at most {CENSUS_NEG_CAP_PER_PAPER} runs per paper, then at most "
                            f"{CENSUS_NEG_MAX} overall, proportional within each 'how' bucket",
                  coverage=json.load(open(os.path.join(CACHE, "coverage.json")))),
        cv=cv, test1_real_papers=t1, test2_heldout_wordings=t2, test3_false_alarms=t3, examples=ex,
        review_rows=review_out, seconds=round(time.time() - t0))
    json.dump(report, open(os.path.join(HERE, OUT), "w", encoding="utf-8"), indent=1, ensure_ascii=False,
              default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print("wrote", OUT, "in", report["seconds"], "s")


if __name__ == "__main__":
    main()
