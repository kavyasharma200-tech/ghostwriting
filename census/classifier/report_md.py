# -*- coding: utf-8 -*-
"""Render report.json (+ census_scored.json when present) as REPORT.md. Discussion text lives in DISCUSSION below."""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
DISCUSSION_FILE = os.path.join(HERE, "discussion.md")


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def f3(x):
    return "n/a" if x is None else f"{x:.3f}"


def prf_row(name, d):
    return f"| {name} | {d['tp']} | {d['fp']} | {d['fn']} | {d['tn']} | {f3(d['precision'])} | {f3(d['recall'])} | {f3(d['f1'])} |"


def esc(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def cf(t3, who):
    c = t3.get("census_crossfit")
    return f"{c['flagged_' + who]} of {c['papers']}" if c else "not run"


def headline(reports):
    """One table: the three key numbers for the rules and each TabPFN variant."""
    L = ["## Headline (measured)", "",
         "| | real papers: paper recall | real papers: run recall | held-out wordings: recall | held-out keyword-free: recall "
         "| hard negatives: false-positive rate | unseen test papers flagged | census, cross-fitted: papers flagged "
         "| ATLAS-Bench flagged |",
         "|---|---|---|---|---|---|---|---|---|"]
    first = True
    for name, R in reports:
        t1, t2, t3 = R["test1_real_papers"], R["test2_heldout_wordings"], R["test3_false_alarms"]
        at = t3["atlas_bench_2610.39438v1"]
        if first:
            L.append(f"| regex rules (deployed) | {pct(t1['paper_recall_rules'])} | {pct(t1['rules']['recall'])} | "
                     f"{pct(t2['heldout_all']['rules'])} | {pct(t2['heldout_keyword_free']['rules'])} | "
                     f"{pct(t2['hard_negative_fpr']['rules'])} | {t3['flagged_rules']} of {t3['papers']} | "
                     f"{cf(t3, 'rules')} | {'yes' if at['paper_flagged_rules'] else 'no'} |")
            first = False
        L.append(f"| {name} (threshold {R['model']['threshold']}) | {pct(t1['paper_recall_tabpfn'])} | "
                 f"{pct(t1['tabpfn']['recall'])} | {pct(t2['heldout_all']['tabpfn'])} | "
                 f"{pct(t2['heldout_keyword_free']['tabpfn'])} | {pct(t2['hard_negative_fpr']['tabpfn'])} | "
                 f"{t3['flagged_tabpfn']} of {t3['papers']} | {cf(t3, 'tabpfn')} | "
                 f"{'yes' if at['paper_flagged_tabpfn'] else 'no'} |")
    R = reports[0][1]
    t1, t2, t3 = R["test1_real_papers"], R["test2_heldout_wordings"], R["test3_false_alarms"]
    L.append(f"| GBM reference, same numeric features (threshold {R['cv']['gbm_reference']['threshold']}) | n/a | "
             f"{pct(t1['gbm_reference']['recall'])} | {pct(t2['heldout_all']['gbm_reference'])} | "
             f"{pct(t2['heldout_keyword_free']['gbm_reference'])} | {pct(t2['hard_negative_fpr']['gbm_reference'])} | "
             f"{t3['flagged_gbm_reference']} of {t3['papers']} | | |")
    run1 = os.path.join(HERE, "cache", "report_run1.json")
    if os.path.exists(run1):
        R1 = json.load(open(run1, encoding="utf-8"))
        a, b = R1["test1_real_papers"], R1["test2_heldout_wordings"]
        L.append(f"| run 1 (numeric, before long-form synthetic instructions were added; threshold "
                 f"{R1['model']['threshold']}) | {pct(a['paper_recall_tabpfn'])} | {pct(a['tabpfn']['recall'])} | "
                 f"{pct(b['heldout_all']['tabpfn'])} | {pct(b['heldout_keyword_free']['tabpfn'])} | "
                 f"{pct(b['hard_negative_fpr']['tabpfn'])} | {R1['test3_false_alarms']['flagged_tabpfn']} of "
                 f"{R1['test3_false_alarms']['papers']} | not run | "
                 f"{'yes' if R1['test3_false_alarms']['atlas_bench_2610.39438v1']['paper_flagged_tabpfn'] else 'no'} |")
    return L + [""]


def main():
    reports = []
    for name, fn in [("TabPFN v3.5, numeric features", "report.json"),
                     ("TabPFN v3.5, numeric features + raw text column", "report_text.json")]:
        if os.path.exists(os.path.join(HERE, fn)):
            reports.append((name, json.load(open(os.path.join(HERE, fn), encoding="utf-8"))))
    R = reports[0][1]  # details below are for the production model: numeric features (what score.py uses)
    L = []
    m = R["model"]
    L += ["# Ghost classifier: report", "",
          f"Model: **{m['name']}**, version **{m['version']}** (`{m['model_path']}`), {m['n_features']} numeric "
          f"features, threshold **{m['threshold']}** (best F1 on 4-fold out-of-fold predictions, folds grouped by "
          f"document). Baseline: the deployed regex rules (`rules()` in census/crawl.py): a run is flagged when any "
          f"rule hits. A gradient-boosting model on the same features is shown as a reference only.", "",
          "All numbers below are **measured** by `evaluate.py` on this snapshot of the data unless marked otherwise.", ""]
    L += headline(reports)
    if os.path.exists(DISCUSSION_FILE):
        L += [open(DISCUSSION_FILE, encoding="utf-8").read().strip(), ""]
    L += [f"Sections below are for: **{m['name']}**.", ""]
    d = R["data"]
    L += ["## Data", "", "| source:label | rows |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in d["rows_by_source_label"].items()]
    L += ["", f"Training rows: {d['train_rows']} ({d['train_pos']} positive, {d['train_neg']} negative). "
              f"Census negatives in training: {d['census_train_negatives_used']} of "
              f"{d['census_train_negatives_before_subsample']} ({d['subsample']}).", "",
          "Scan coverage of synthetic injections (an injection the scan does not report never reaches the classifier):",
          "", "| injection | found by scan | missed |", "|---|---|---|"]
    L += [f"| {k} | {v['found']} | {v['missed']} |" for k, v in sorted(d["coverage"].items())]
    cv = R["cv"]
    L += ["", "## Cross-validation on the training rows (grouped by document)", "",
          "| model | TP | FP | FN | TN | precision | recall | F1 |", "|---|---|---|---|---|---|---|---|",
          prf_row(f"TabPFN @ {cv['threshold']}", cv["tabpfn"]), prf_row("TabPFN @ 0.5", cv["tabpfn_at_05"]),
          prf_row("rules", cv["rules"]), prf_row(f"GBM reference @ {cv['gbm_reference']['threshold']}", cv["gbm_reference"]),
          "", f"AUC: TabPFN {f3(cv['tabpfn_auc'])}, GBM reference {f3(cv['gbm_auc'])}.", ""]
    t1 = R["test1_real_papers"]
    L += ["## Test 1: the 16 real 2025 papers, held out entirely", "",
          "| model | TP | FP | FN | TN | precision | recall | F1 |", "|---|---|---|---|---|---|---|---|",
          prf_row("TabPFN", t1["tabpfn"]), prf_row("rules", t1["rules"]), prf_row("GBM reference", t1["gbm_reference"]), "",
          f"Paper-level recall: TabPFN **{pct(t1['paper_recall_tabpfn'])}**, rules **{pct(t1['paper_recall_rules'])}** "
          f"({t1['papers']} papers).", "",
          f"Strict variant (also dropping the {t1['strict_no_real_like_wordings']['dropped_training_rows']} synthetic rows "
          f"whose wording copies the real papers): run recall "
          f"{pct(t1['strict_no_real_like_wordings']['run']['recall'])}, paper recall "
          f"{pct(t1['strict_no_real_like_wordings']['paper_recall'])}.", ""]
    L += ["| paper | TabPFN | rules | max P |", "|---|---|---|---|"]
    L += [f"| {k} | {'yes' if v['tabpfn'] else 'no'} | {'yes' if v['rules'] else 'no'} | {v['max_p']} |"
          for k, v in t1["per_paper"].items()]
    t2 = R["test2_heldout_wordings"]

    def rec_row(name, x):
        return f"| {name} | {x['n']} | {pct(x['tabpfn'])} | {pct(x['rules'])} | {pct(x['gbm_reference'])} |"

    L += ["", "## Test 2: held-out wordings injected into held-out documents", "",
          "Recall (share of hidden instructions flagged):", "",
          "| slice | n | TabPFN | rules | GBM ref |", "|---|---|---|---|---|",
          rec_row("all held-out wordings", t2["heldout_all"]),
          rec_row("held-out, keyword-free (no regex hits)", t2["heldout_keyword_free"]),
          rec_row("held-out, with regex keywords", t2["heldout_with_keywords"]),
          rec_row("training wordings on held-out docs", t2["seen_wordings_on_test_docs"])]
    L += [rec_row(f"lang = {k}", v) for k, v in t2["heldout_by_lang"].items()]
    L += [rec_row(f"group = {k}", v) for k, v in t2["heldout_by_group"].items()]
    L += [rec_row(f"technique = {k}", v) for k, v in t2["heldout_by_technique"].items()]
    L += ["", "False-positive rate on synthetic hard negatives in held-out documents (lower is better):", "",
          "| kind | n | TabPFN | rules | GBM ref |", "|---|---|---|---|---|", rec_row("all", t2["hard_negative_fpr"])]
    L += [rec_row(k, v) for k, v in t2["hard_negative_fpr_by_kind"].items()]
    a = t2["all_test_doc_rows"]
    L += ["", "All runs in held-out documents (synthetic + natural):", "",
          "| model | TP | FP | FN | TN | precision | recall | F1 |", "|---|---|---|---|---|---|---|---|",
          prf_row("TabPFN", a["tabpfn"]), prf_row("rules", a["rules"]), prf_row("GBM reference", a["gbm_reference"])]
    t3 = R["test3_false_alarms"]
    L += ["", "## Test 3: paper-level false alarms on papers never used in training", "",
          f"{t3['papers']} papers ({t3['clean_papers']} clean eval papers + {t3['census_papers']} census papers); "
          f"{t3['papers_with_any_hidden_looking_run']} have at least one hidden-looking run.", "",
          "| | papers flagged | runs flagged |", "|---|---|---|",
          f"| TabPFN | {t3['flagged_tabpfn']} | {t3['runs']['tabpfn_flagged']} of {t3['runs']['n']} |",
          f"| rules | {t3['flagged_rules']} | {t3['runs']['rules_flagged']} of {t3['runs']['n']} |",
          f"| GBM reference | {t3['flagged_gbm_reference']} | |", "",
          f"Flagged by TabPFN: {', '.join(t3['flagged_tabpfn_ids']) or 'none'}. "
          f"Flagged by rules: {', '.join(t3['flagged_rules_ids']) or 'none'}.", ""]
    if "census_crossfit" in t3:
        c = t3["census_crossfit"]
        L += [f"Cross-fitted over the whole census so far (5 folds by paper; each paper scored by a model that never saw "
              f"its runs): {c['papers']} papers with span data, {c['papers_with_any_hidden_looking_run']} with at least "
              f"one hidden-looking run ({c['runs']} runs). Papers flagged: TabPFN **{c['flagged_tabpfn']}**, rules "
              f"**{c['flagged_rules']}** (runs: {c['runs_flagged_tabpfn']} vs {c['runs_flagged_rules']}).", ""]
        rows_ = c["flagged"] or c["top"]
        L += ["Flagged runs:" if c["flagged"] else "Highest-scoring census runs (none flagged):", "",
              "| paper | page | P | rules | how | text |", "|---|---|---|---|---|---|"]
        L += [f"| {r['doc'].split(':', 1)[1]} | {r['page']} | {r['p']} | {', '.join(r['rules'])} | {', '.join(r['how'] or [])} | "
              f"{esc(r['text'][:100])} |" for r in rows_[:12]]
        L += [""]
    if "old_format_census" in t3:
        o = t3["old_format_census"]
        L += [f"Older census lines without span measurements ({o['papers']} papers, never trained on; only rule hits "
              f"and up to 3 longer examples per paper were stored, {o['runs']} runs in {o['papers_with_listed_runs']} "
              f"papers), scored by the {o['model']}: TabPFN flags **{o['flagged_tabpfn']}** papers, rules flag "
              f"**{o['flagged_rules']}**.", ""]
        if o["flagged"]:
            L += ["| paper | page | P | rules | text |", "|---|---|---|---|---|"]
            L += [f"| {r['doc'].split(':', 1)[1]} | {r['page']} | {r['p']} | {', '.join(r['rules'])} | {esc(r['text'][:110])} |"
                  for r in o["flagged"][:12]]
            L += [""]
    at = t3["atlas_bench_2610.39438v1"]
    L += ["### The live false alarm: ATLAS-Bench (2610.39438v1, not in training)", "",
          f"{at['runs']} hidden-looking runs; rules flag {at['rules_flagged_runs']} (paper flagged: "
          f"{at['paper_flagged_rules']}); TabPFN flags {at['tabpfn_flagged_runs']} (paper flagged: "
          f"{at['paper_flagged_tabpfn']}).", "", "| page | P | rules | text |", "|---|---|---|---|"]
    L += [f"| {r['page']} | {r['p']} | {', '.join(r['rules'])} | {esc(r['text'][:120])} |" for r in at["rule_hit_runs"]]
    ex = R["examples"]
    L += ["", "## Examples", "",
          f"Across all labelled test rows: TabPFN right where rules were wrong **{ex['n_wins']}** times; rules right "
          f"where TabPFN was wrong **{ex['n_losses']}** times; both wrong **{ex['n_both_wrong']}** times.", "",
          "### Wins (TabPFN right, rules wrong)", "", "| label | P | source | technique/kind | text |", "|---|---|---|---|---|"]
    L += [f"| {r['label']} | {r['p']} | {r['source']} | {r.get('technique', '')}/{r.get('kind', r.get('lang', ''))} | "
          f"{esc(r['text'][:110])} |" for r in ex["wins"][:15]]
    L += ["", "### Losses (rules right, TabPFN wrong)", "", "| label | P | source | technique/kind | text |",
          "|---|---|---|---|---|"]
    L += [f"| {r['label']} | {r['p']} | {r['source']} | {r.get('technique', '')}/{r.get('kind', r.get('lang', ''))} | "
          f"{esc(r['text'][:110])} |" for r in ex["losses"][:15]]
    L += ["", "### Both wrong", "", "| label | P | source | technique/kind | text |", "|---|---|---|---|---|"]
    L += [f"| {r['label']} | {r['p']} | {r['source']} | {r.get('technique', '')}/{r.get('kind', r.get('lang', ''))} | "
          f"{esc(r['text'][:110])} |" for r in ex["both_wrong"][:10]]
    L += ["", "## Census runs set aside for human review (never trained on)", "",
          "Census text that the rules or an imperative/second-person heuristic say might be a real instruction.", "",
          "| paper | page | P | TabPFN flag | rules | text |", "|---|---|---|---|---|---|"]
    L += [f"| {r['doc'].split(':', 1)[1]} | {r['page']} | {r['p']} | {r['flagged_tabpfn']} | {', '.join(r['rules'])} | "
          f"{esc(r['text'][:120])} |" for r in R["review_rows"][:40]]
    sc = os.path.join(HERE, "census_scored.json")
    if os.path.exists(sc):
        S = json.load(open(sc, encoding="utf-8"))
        L += ["", "## Census re-scored (score.py)", "", f"Generated {S['generated']}: `{json.dumps(S['summary'])}`", "",
              "| paper | max P | rules | in training | top run (page: text) |", "|---|---|---|---|---|"]
        for p in (S["haunted"] + S["rules_only"])[:30]:
            tr = p["top_runs"][0] if p["top_runs"] else {}
            L.append(f"| {p['id']} | {p['max_p']} | {p['rules_flag']} | {p['in_training']} | "
                     f"p{tr.get('page')}: {esc(tr.get('text', '')[:110])} |")
    L += ["", "## Files and how to re-run", "",
          "Python: `~/.venvs/ghosteval` (pymupdf, tabpfn-client 0.7.0, scikit-learn); token from "
          "`ghostwriting/.env` (`TABPFN_TOKEN`). Re-run: `python -I dataset.py --refresh-census`, `python -I evaluate.py` "
          "(and `--text`), `python -I score.py`, `python -I report_md.py`. A full rebuild (`dataset.py` without the flag) "
          "re-synthesises everything in about 15 minutes.", "",
          "- `common.py`: paths, loading census/crawl.py's `scan`/`rules`, the hosted TabPFN client (v3.5) with the token",
          "- `dataset.py`: builds `cache/rows.jsonl` (+ `review.jsonl`, `coverage.json`, `census_papers.json`)",
          "- `wordings.py`: the hand-written instructions (146, a quarter held out) and innocent look-alike templates",
          "- `features.py`: the numeric features, documented", "- `evaluate.py`: tests 1-3 -> `report.json`",
          "- `score.py`: `score_runs(runs)` and the census re-scorer -> `census_scored.json`",
          "- `report_md.py`: renders this file; `discussion.md` holds the hand-written discussion", ""]
    open(os.path.join(HERE, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L))
    print("wrote REPORT.md")


if __name__ == "__main__":
    main()
