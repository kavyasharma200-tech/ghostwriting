# -*- coding: utf-8 -*-
"""Build the ghost-classifier dataset: one row per hidden-looking run found by census/crawl.py's scan().

    python dataset.py                    # full build: cache/rows.jsonl (+ review.jsonl, coverage.json)
    python dataset.py --refresh-census   # re-read the growing census only, reuse cached eval/synthetic rows

Sources (every row keeps `doc`, so evaluation can split by document):
  clean    eval/clean/*.pdf scanned as-is; every run is innocent (label 0).
  census   census/results.jsonl lines that carry `runs` (the crawler's newer format, with span measurements).
           Innocent (0) unless the text looks like a real instruction to an AI: those go to cache/review.jsonl
           with label None and are kept OUT of training, for a human to read.
  real     eval/real/*.pdf: runs matching the manifest's hidden text are 1, anything else 0.
  planted  eval/planted/*.pdf: runs matching the hidden text are 1 (zero_width_chars and controls skipped).
  synth    copies of clean pages (in memory; eval files are never written) with text injected by PyMuPDF:
           positives = instructions from wordings.py hidden with a technique; negatives = innocent look-alikes
           (tiny figure labels naming models, axis ticks, legends, white titles on dark bands, OCR-style invisible
           text, margin stamps, maths, prompt templates printed in figures).
           Each injection goes onto a one-page copy, scan() runs on it, and the run containing the injected text is
           kept with page/page_index set back to the original page. Injections scan() does not see are counted
           in cache/coverage.json (they cannot reach the classifier).

Document split: every third clean paper (sorted) is a TEST document: its synthetic rows use the held-out wordings and
are never trained on. Census papers are split 60/40 by a hash of the arXiv id.
"""
import glob
import json
import os
import random
import re
import sys
import textwrap
import zlib
from multiprocessing import Pool

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import CACHE, CENSUS, EVAL, load_crawl  # noqa: E402
import wordings  # noqa: E402

FONT_DIR = "C:/Windows/Fonts"
CLEAN = sorted(glob.glob(os.path.join(EVAL, "clean", "*.pdf")))
TEST_CLEAN = {os.path.basename(p)[:-4] for i, p in enumerate(CLEAN) if i % 3 == 1}
# Synthetic wordings that copy the real 2025 papers' text: excluded in the strict version of the real-paper test.
REAL_LIKE = {"review_kw00", "review_kw01", "review_kw03", "review_kw17", "review_kw19"}
TEXT_CAP, SPAN_CAP = 300, 12  # the crawler stores census runs capped like this; every source is capped the same way


def norm(s):
    s = "".join(chr(ord(c) - 0xE0000) if 0xE0000 <= ord(c) <= 0xE007F else c for c in s)
    return re.sub(r"\s+", "", s).lower()


def matches(inj, run_text):
    a, b = norm(inj), norm(run_text)
    return bool(a) and (a[:20] in b or b[:20] in a)


def census_split(arxiv_id):
    return "test" if zlib.crc32(arxiv_id.encode()) % 5 < 2 else "train"


def cap(run):
    return dict(run, text=run["text"][:TEXT_CAP], spans=run.get("spans", [])[:SPAN_CAP])


# ------------------------------------------------------------------ injection
def pick_font(text, rng):
    if re.search(r"[\u0900-\u097F]", text):
        return dict(fontname="nirm", fontfile=f"{FONT_DIR}/Nirmala.ttc")
    if re.search(r"[\u3000-\u9FFF\uFF00-\uFFEF]", text):
        return dict(fontname="china-s", fontfile=None)
    if any(ord(c) > 255 for c in text):
        return dict(fontname="arial", fontfile=f"{FONT_DIR}/arial.ttf")
    f = rng.choice(["helv", "tiro", "cour", "arial"])
    return dict(fontname="arial", fontfile=f"{FONT_DIR}/arial.ttf") if f == "arial" else dict(fontname=f, fontfile=None)


def position(rng, W, H, where=None):
    where = where or rng.choice(["body", "body", "bottom", "top", "left", "figure"])
    if where == "body":
        return rng.uniform(.1, .55) * W, rng.uniform(.15, .9) * H
    if where == "bottom":
        return rng.uniform(.1, .5) * W, rng.uniform(.93, .985) * H
    if where == "top":
        return rng.uniform(.1, .5) * W, rng.uniform(.02, .07) * H
    if where == "left":
        return rng.uniform(.005, .06) * W, rng.uniform(.1, .9) * H
    return rng.uniform(.15, .7) * W, rng.uniform(.2, .8) * H  # "figure"


def wrap(text, size, W, rng, single=False):
    if single or size < 3:
        return text
    width = int(max(30, min(130, (W * rng.uniform(.45, .8)) / (size * .5))))
    return "\n".join(textwrap.wrap(text, width)) if not re.search(r"[\u3000-\u9FFF]", text) else text


def inject(page, spec, rng):
    import pymupdf
    W, H = page.rect.width, page.rect.height
    t, text = spec["technique"], spec["text"]
    font = pick_font(text, rng)
    size, color, mode = rng.uniform(5, 11), (0, 0, 0), 0
    x, y = position(rng, W, H)
    single = False
    if t == "white":
        color = (1, 1, 1)
    elif t == "near_white":
        v = rng.choice([0xF0, 0xF4, 0xF8, 0xFA, 0xFD]) / 255
        color = (v, v, v)
    elif t in ("tiny", "white_tiny"):
        size = spec.get("size") or rng.choice([0.1, 0.1, 0.01, 0.25, 0.5, 1.0, rng.uniform(.1, 1.5)])
        color = (1, 1, 1) if t == "white_tiny" else rng.choice([(0, 0, 0), (.2, .2, .2), (.1, .1, .4)])
        single = True
    elif t == "tiny_label":  # innocent figure text: small but not microscopic
        size = rng.choice([rng.uniform(.8, 1.95), rng.uniform(1.2, 1.95), rng.uniform(1.5, 1.99)])
        color = rng.choice([(0, 0, 0), (.3, .3, .3), (.12, .3, .6), (.7, .1, .1)])
        x, y = position(rng, W, H, "figure")
        single = rng.random() < .7
    elif t == "off_page":
        side = rng.choice(["right", "right", "left", "below", "above"])
        if side == "right":
            x, y = W + rng.uniform(5, 150), rng.uniform(.05, .95) * H
        elif side == "left":
            x, y = -rng.uniform(250, 600), rng.uniform(.05, .95) * H
        elif side == "below":
            x, y = rng.uniform(.1, .5) * W, H + rng.uniform(15, 200)
        else:
            x, y = rng.uniform(.1, .5) * W, -rng.uniform(20, 200)
        single = rng.random() < .5
    elif t == "render3":
        mode = 3
        color = rng.choice([(0, 0, 0), (1, 1, 1)]) if spec["label"] else (0, 0, 0)
    elif t == "light_box":
        v = rng.uniform(.94, .99)
        color = (v, v, v)
        page.draw_rect(pymupdf.Rect(x - 4, y - size * 1.5, min(W - 5, x + W * .8), y + size * 4 + 4), color=None, fill=color)
    elif t == "dark_box_same":
        c = rng.choice([(.1, .1, .3), (.2, .2, .2), (.0, .3, .3)])
        color = c
        page.draw_rect(pymupdf.Rect(x - 4, y - size * 1.5, min(W - 5, x + W * .8), y + size * 4 + 4), color=None, fill=c)
    elif t == "white_on_band":  # dark band painted as a thick stroke (no fill): the scan cannot see it behind the text
        color = (1, 1, 1)
        size = rng.uniform(6, 10)
        single = True
        band = rng.choice([(.1, .1, .3), (.2, .2, .2), (.0, .3, .5), (.5, .1, .1)])
        page.draw_line((x - 4, y - size * .35), (min(W - 5, x + W * .6), y - size * .35), color=band, width=size * 1.7)
    elif t == "watermark":
        v = rng.uniform(.94, .98)
        color, size, single = (v, v, v), rng.uniform(18, 44), True
        x, y = rng.uniform(.05, .3) * W, rng.uniform(.3, .7) * H
    elif t == "white_label":  # innocent white text on white (spacing hacks, hidden anchors, empty-cell placeholders)
        color = (1, 1, 1)
        size = rng.uniform(4, 10)
        single = True
    text_w = wrap(text, size, W, rng, single)
    try:
        page.insert_text((x, y), text_w, fontsize=size, color=color, render_mode=mode, **font)
    except Exception:
        page.insert_text((x, y), text_w, fontsize=size, color=color, render_mode=mode, fontname="arial",
                         fontfile=f"{FONT_DIR}/arial.ttf")
    if t == "under_rect":
        bb = pymupdf.Rect(x - 2, y - size * 1.3, min(W - 2, x + W * .85), y + size * (text_w.count("\n") + 1) * 1.3)
        page.draw_rect(bb, color=None, fill=(1, 1, 1))


POS_TECH = [("white", 18), ("near_white", 10), ("tiny", 14), ("white_tiny", 20), ("off_page", 12), ("render3", 10),
            ("light_box", 8), ("dark_box_same", 4), ("under_rect", 4)]
NEG_PLAN = [  # (technique, [kinds])
    ("tiny_label", ["model_labels", "model_labels", "model_labels", "axis", "legend", "math", "intl", "prompt", "title"]),
    ("white_on_band", ["title", "title", "model_labels", "legend", "intl"]),
    ("render3", ["prose", "prose", "title"]),
    ("off_page", ["stamp", "title", "prose", "axis", "legend"]),
    ("white_label", ["title", "stamp", "legend", "math", "prose", "model_labels"]),
    ("watermark", ["stamp"]),
    ("tiny", ["prose", "stamp"]),  # tiny dark prose: e.g. footnote-sized OCR remnants, microprint stamps
    ("tiny_label", ["long"]),  # long figure text: prompt templates, tables, paragraphs (added after run 1)
    ("white_label", ["long"]),
    ("off_page", ["long"]),
]
NEG_W = [34, 18, 14, 14, 12, 3, 5, 9, 3, 3]
LONG_SHARE = .15  # share of positives that are long structured instructions (added after run 1)


def weighted(rng, items):
    tot = sum(w for _, w in items)
    r = rng.uniform(0, tot)
    for v, w in items:
        r -= w
        if r <= 0:
            return v
    return items[-1][0]


def page_sentences(page):
    txt = " ".join(page.get_text().split())
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", txt) if 40 <= len(s.strip()) <= 220][:60]


def synth_doc(args):
    """Inject positives and negatives into one-page copies of one clean paper; return (rows, coverage)."""
    path, n_pos, n_neg, seed = args
    import pymupdf
    crawl = load_crawl()
    did = os.path.basename(path)[:-4]
    split = "test" if did in TEST_CLEAN else "train"
    rng = random.Random(seed)
    src = pymupdf.open(path)
    N = src.page_count
    pages = sorted(rng.sample(range(min(N, 80)), min(N, 80, 8)))
    page_bytes, sents = {}, {}
    for p in pages:
        one = pymupdf.open()
        one.insert_pdf(src, from_page=p, to_page=p)
        page_bytes[p] = one.tobytes()
        sents[p] = page_sentences(one[0])
        one.close()
    wl = wordings.positive_wordings()
    train_w = [w for w in wl if w[4] == "train"]
    held_w = [w for w in wl if w[4] == "heldout"]
    specs = []
    if split == "train":
        for _ in range(n_pos):
            specs.append(dict(label=1, w=rng.choice(train_w)))
    else:
        for _ in range(n_pos):
            specs.append(dict(label=1, w=rng.choice(held_w)))
        for _ in range(n_pos // 2):
            specs.append(dict(label=1, w=rng.choice(train_w)))
    for _ in range(n_neg):
        tech, kinds = weighted(rng, list(zip(NEG_PLAN, NEG_W)))
        specs.append(dict(label=0, technique=tech, kind=rng.choice(kinds)))
    rows, cov = [], []
    for s in specs:
        p = rng.choice(pages)
        if s["label"]:
            wid, group, lang, text, wsplit = s["w"]
            if rng.random() < LONG_SHARE:
                wsplit = wsplit if split == "test" else "train"
                text = wordings.long_positive(rng, wsplit)
                wid, group, lang = f"long_{wsplit}", "long", "en"
            s.update(technique=weighted(rng, POS_TECH), text=text, wid=wid, group=group, lang=lang, wsplit=wsplit)
        else:
            s["text"] = (wordings.long_negative(rng, sents[p]) if s["kind"] == "long"
                         else wordings.negative_text(s["kind"], rng, sents[p]))
            if s["technique"] == "render3" and s["kind"] == "prose" and sents[p] and rng.random() < .5:
                s["text"] = " ".join(rng.sample(sents[p], min(len(sents[p]), rng.randint(2, 4))))
        doc = pymupdf.open(stream=page_bytes[p], filetype="pdf")
        try:
            inject(doc[0], s, rng)
            data = doc.tobytes()
        except Exception as e:
            cov.append(dict(technique=s["technique"], label=s["label"], found=False, error=str(e)[:80]))
            continue
        finally:
            doc.close()
        _, runs = crawl.scan(data)
        hit = [r for r in runs if matches(s["text"], r["text"])]
        cov.append(dict(technique=s["technique"], label=s["label"], found=bool(hit), lang=s.get("lang")))
        if not hit:
            continue
        r = cap(hit[0])
        r.update(page=p + 1, page_index=p / max(1, N - 1))
        meta = dict(source="synth", doc=f"clean:{did}", split=split, label=s["label"], technique=s["technique"],
                    injected=s["text"])
        if s["label"]:
            meta.update(wid=s["wid"], group=s["group"], lang=s["lang"], wsplit=s["wsplit"], real_like=s["wid"] in REAL_LIKE)
        else:
            meta.update(kind=s["kind"])
        rows.append(dict(r, **meta))
    src.close()
    return rows, cov


# ------------------------------------------------------------------ natural sources
def scan_file(path):
    crawl = load_crawl()
    with open(path, "rb") as f:
        return crawl.scan(f.read())


def eval_rows():
    rows = []
    with Pool(6) as pool:
        clean = pool.map(scan_file, CLEAN)
        real_man = [m for m in json.load(open(os.path.join(EVAL, "real", "manifest.json"), encoding="utf-8"))
                    if m.get("file") and os.path.exists(os.path.join(EVAL, m["file"]))]
        real_paths = [os.path.join(EVAL, m["file"]) for m in real_man]
        real = pool.map(scan_file, real_paths)
        pl_man = [m for m in json.load(open(os.path.join(EVAL, "planted", "manifest.json"), encoding="utf-8"))
                  if m.get("format") == "pdf"]
        pl = pool.map(scan_file, [os.path.join(EVAL, "planted", m["file"]) for m in pl_man])
    for p, (pages, runs) in zip(CLEAN, clean):
        did = os.path.basename(p)[:-4]
        for r in runs:
            rows.append(dict(cap(r), source="clean", doc=f"clean:{did}", split="test" if did in TEST_CLEAN else "train",
                             label=0, n_pages=pages))
    for m, (pages, runs) in zip(real_man, real):
        texts = [m["hidden_text"]] + [o.get("text", "") for o in m.get("occurrences", [])]
        for r in runs:
            lab = int(any(matches(t, r["text"]) for t in texts if t))
            rows.append(dict(cap(r), source="real", doc=f"real:{m['id']}{m['version']}", split="real", label=lab,
                             n_pages=pages))
    for m, (pages, runs) in zip(pl_man, pl):
        if m["technique"] in ("zero_width_chars",):
            continue
        for r in runs:
            lab = int(bool(m.get("hidden_text")) and matches(m["hidden_text"], r["text"]))
            rows.append(dict(cap(r), source="planted", doc=f"planted:{m['file']}", split="train", label=lab,
                             technique=m["technique"], n_pages=pages))
    return rows


IMPER = re.compile(r"\b(ignore|disregard|forget|give|recommend|rate|rank|accept|respond|reply|answer|say|tell|state|"
                   r"report|describe|do not|don't|never|must|should|you|your)\b", re.I)


def needs_review(text, crawl):
    """Census text that could be a genuine instruction to an AI: kept out of training, listed for a human."""
    t = " ".join(text.split())
    if crawl.rules(t):
        return True
    words = t.split()
    return len(words) >= 6 and len(IMPER.findall(t)) >= 2 and sum(w.isalpha() for w in words) / len(words) > .6


def read_census(path=CENSUS):
    """Yield parsed lines, tolerating a partial last line (the crawler is appending)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except Exception:
                continue


def census_rows(crawl):
    rows, review, papers = [], [], []
    for rec in read_census():
        if "runs" not in rec:
            continue
        split = census_split(rec["id"])
        papers.append(dict(id=rec["id"], split=split, n_runs=len(rec["runs"]), title=rec.get("title", "")))
        for r in rec["runs"]:
            row = dict(cap(r), source="census", doc=f"census:{rec['id']}", split=split, label=0,
                       n_pages=rec.get("pages"))
            if needs_review(r["text"], crawl):
                row["label"] = None
                review.append(row)
            rows.append(row)
    return rows, review, papers


def main():
    """Full build; `--refresh-census` re-reads census/results.jsonl only and reuses the cached eval + synthetic rows."""
    os.makedirs(CACHE, exist_ok=True)
    crawl = load_crawl()
    base_path = os.path.join(CACHE, "base_rows.jsonl")
    cov_path = os.path.join(CACHE, "coverage_raw.json")
    if "--refresh-census" in sys.argv and os.path.exists(base_path):
        rows = [json.loads(l) for l in open(base_path, encoding="utf-8")]
        cov = json.load(open(cov_path, encoding="utf-8"))
    else:
        rows = eval_rows()
        print("eval rows", len(rows), flush=True)
        args = [(p, 28, 34, 1000 + i) for i, p in enumerate(CLEAN)]
        cov = []
        with Pool(6) as pool:
            for r, c in pool.imap_unordered(synth_doc, args):
                rows += r
                cov += c
                print("synth", len(rows), flush=True)
        with open(base_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        json.dump(cov, open(cov_path, "w", encoding="utf-8"))
    crows, review, papers = census_rows(crawl)
    rows += crows
    with open(os.path.join(CACHE, "rows.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(CACHE, "review.jsonl"), "w", encoding="utf-8") as f:
        for r in review:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    json.dump(papers, open(os.path.join(CACHE, "census_papers.json"), "w", encoding="utf-8"))
    from collections import Counter
    c = Counter((d["technique"], d["label"], d["found"]) for d in cov)
    covsum = {}
    for (t, lab, found), n in c.items():
        k = f"{'pos' if lab else 'neg'}:{t}"
        covsum.setdefault(k, {"found": 0, "missed": 0})["found" if found else "missed"] += n
    json.dump(covsum, open(os.path.join(CACHE, "coverage.json"), "w"), indent=1, sort_keys=True)
    cnt = Counter((r["source"], r["label"]) for r in rows)
    print(json.dumps({f"{k[0]}:{k[1]}": v for k, v in sorted(cnt.items(), key=str)}, indent=1))
    print("census papers with runs field", len(papers), "review", len(review))
    print(json.dumps(covsum, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
