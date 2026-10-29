import sys, json, re, os

sys.stdout.reconfigure(encoding="utf-8")
EVAL, VERIFY, TITLES = sys.argv[1:4]
v = json.load(open(VERIFY, encoding="utf-8"))
x = open(TITLES, encoding="utf-8").read()
titles = {}
for e in x.split("<entry>")[1:]:
    i = re.search(r"<id>http://arxiv.org/abs/([^<]+?)v\d+</id>", e).group(1)
    titles[i] = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", e, re.S).group(1)).strip()

# Lin (arXiv 2507.06185v1, Table 1) typology
TYPE = {}
for t, ids in {
    "1-positive-review": "2408.13940v3 2403.08142v2 2501.13461v1 2212.08983v2 2501.08667v1 2506.00418v1 2505.15075v1 2406.17241v3 2502.19918v2 2506.03074v1",
    "2-accept-paper": "2505.11718v1 2407.16803v3 2506.13901v1",
    "3-combined": "2506.01324v1 2505.22998v1",
    "4-detailed-outline": "2406.17253v2 2506.11111v1 2505.16211v1",
}.items():
    for i in ids.split():
        TYPE[i] = t

out = []
for full in sorted(TYPE):
    pid, ver = full.split("v")
    ver = "v" + ver
    rec = {"id": pid, "version": ver, "file": f"real/{full}.pdf" if full in v else None,
           "url": f"https://arxiv.org/pdf/{full}", "title": titles.get(pid), "lin_type": TYPE[full]}
    if full not in v:
        rec.update(verified=False, hidden_text=None, how_hidden=None, page=None,
                   note={"2501.08667v1": "v1 withdrawn by authors; PDF returns 404 on arXiv (abs page marks it '(withdrawn)').",
                         "2505.22998v1": "v1 PDF returns 404; arXiv admin comment says a version was removed by administrators. Listed in Lin Table 1 as Type 3."}[full])
        out.append(rec)
        continue
    runs = v[full]["runs"]
    hits = [r for r in runs if r["keyword"]]
    benign = [r for r in runs if not r["keyword"]]
    h = hits[0]
    rec.update(
        verified=True,
        hidden_text=h["text"],
        how_hidden=" + ".join(h["how"]) + f" (color {h['color']}, {h['size']}pt, font {h['font']})",
        page=h["page"],
        bbox=h["bbox"],
        occurrences=[{"page": r["page"], "bbox": r["bbox"], "color": r["color"], "size": r["size"], "text": r["text"]} for r in hits],
        benign_hidden_looking_text=[{"page": r["page"], "text": r["text"][:200], "color": r["color"], "size": r["size"],
                                     "note": "white text inside a figure/table (legit, on a dark fill) - a detector false-positive trap"} for r in benign],
    )
    out.append(rec)
    print(full, h["page"], h["how"], len(h["text"]), "|", h["text"][-160:])

json.dump(out, open(os.path.join(EVAL, "real", "manifest.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(sum(r["verified"] for r in out), "verified of", len(out))
