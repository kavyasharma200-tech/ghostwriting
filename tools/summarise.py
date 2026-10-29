"""Turns the evaluation runner's log into site/eval-results.json, the file the evidence section reads.

    python tools/summarise.py eval/run-detect.txt [eval/run-gemma.txt]

Summaries (the sentences under each table) live in eval/summaries.json, written by hand after reading the numbers.
"""
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The zero-width case is a sentence printed in plain sight (visible to a person), so it is reported in the
# summary rather than scored as a hidden-text miss.
LABELS = OrderedDict([
    ("white_text", "White text on a white page"),
    ("same_color_box", "Text the colour of the box behind it"),
    ("near_white_f8", "Grey one shade off white"),
    ("tiny_1pt", "1 pt type"),
    ("render_mode_3", "Drawn in invisible mode"),
    ("covered_by_rect", "Covered by a shape"),
    ("off_page", "Placed off the page"),
    ("unicode_tags", "Unicode tag characters"),
])


def report(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith('"{'):
            return json.loads(json.loads(line))
    raise SystemExit(f"no report in {path}")


def how(entry):
    o = (entry.get("occurrences") or [{}])[0]
    colour = "white" if o.get("color", "").upper() in ("#FFFFFF", "#FEFEFE") else o.get("color", "")
    size = o.get("size")
    return f"{colour}, {size:g} pt" if size and size < 2 else f"{colour}, normal size"


def main():
    r = report(sys.argv[1])
    summaries = json.loads((ROOT / "eval" / "summaries.json").read_text(encoding="utf-8")) if (ROOT / "eval" / "summaries.json").exists() else {}
    manifest = {e["id"] + e["version"]: e for e in json.loads((ROOT / "eval" / "real" / "manifest.json").read_text(encoding="utf-8"))}

    real = [{"id": x["id"], "how": how(manifest[x["id"]]), "found": x["found"] and x["ai"], "otherFlags": x["otherFlags"]} for x in r["real"]]

    planted = []
    for tech, label in LABELS.items():
        rows = [p for p in r["planted"] if p["technique"] == tech and p["format"] == "pdf"]
        planted.append({"label": label, "n": len(rows), "found": sum(all(i["found"] and i["ai"] for i in p["items"]) for p in rows)})
    html_items = [i for p in r["planted"] if p["format"] == "html" for i in p["items"]]
    planted.append({"label": "Hidden in web pages (CSS, comments, off-screen)", "n": len(html_items), "found": sum(i["found"] for i in html_items)})
    controls = [p for p in r["planted"] if p["technique"] == "control"]

    clean = r["clean"]
    out = {
        "when": r["when"],
        "real": {"items": real, "summary": summaries.get("real", "")},
        "planted": {"items": planted, "controls": len(controls), "controlFlags": sum(p["flagged"] for p in controls), "summary": summaries.get("planted", "")},
        "clean": {"n": len(clean), "flagged": sum(1 for c in clean if c["flagged"]), "aiFlagged": sum(1 for c in clean if c["aiFlagged"]),
                  "minorPapers": sum(1 for c in clean if c.get("minor")), "summary": summaries.get("clean", "")},
    }
    if len(sys.argv) > 2:
        g = report(sys.argv[2]).get("gemma") or []
        out["gemma"] = {"items": [{"doc": x["id"], "clean": x["clean"], "haunted": x["haunted"], "kept": x["kept"]} for x in g],
                        "samples": report(sys.argv[2]).get("samples") or [], "summary": summaries.get("gemma", "")}
    dest = ROOT / "site" / "eval-results.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "items"} if isinstance(v, dict) else v for k, v in out.items()}, indent=1))
    print("real found", sum(x["found"] for x in real), "/", len(real))
    for p in planted:
        print(f'  {p["label"]}: {p["found"]}/{p["n"]}')


if __name__ == "__main__":
    main()
