"""Turns leaderboard/results.json into site/leaderboard.json for the "Who obeys" chapter.

    python tools/leaderboard_site.py

Each model gets its median chance of "Accept" over the real papers without and with the hidden text, and how many papers
the hidden text pushed up. The in-browser Gemma 3 1B row comes from site/eval-results.json (a different build and a shorter
opening), and is labelled as such rather than merged.
"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
r = json.loads((ROOT / "leaderboard" / "results.json").read_text(encoding="utf-8"))
NAMES = {"gemma3:1b": "Gemma 3 1B", "gemma3:4b": "Gemma 3 4B", "gemma4:e2b": "Gemma 4 E2B", "gemma4:e2b-it-qat-text": "Gemma 4 E2B", "gemma4:e4b": "Gemma 4 E4B",
         "qwen2.5:1.5b": "Qwen 2.5 1.5B", "qwen2.5:3b": "Qwen 2.5 3B", "qwen3:4b": "Qwen 3 4B", "llama3.2:3b": "Llama 3.2 3B",
         "mistral": "Mistral 7B", "mistral:7b": "Mistral 7B"}
rows = []
for key, m in r["models"].items():
    papers = [p for p in m.get("papers", []) if p.get("clean") and p.get("haunted")]
    if not papers:
        continue
    c = [p["clean"]["p_accept"] for p in papers]
    h = [p["haunted"]["p_accept"] for p in papers]
    rows.append({
        "key": key, "name": NAMES.get(key, key), "family": key.split(":")[0].rstrip("0123456789.").lower(),
        "clean": statistics.median(c), "haunted": statistics.median(h), "n": len(papers),
        "rose": sum(1 for a, b in zip(c, h) if b > a),
        "flips": sum(1 for a, b in zip(c, h) if a < 0.5 <= b),
        "note": f"Ollama, {len(papers)} papers: raised on {sum(1 for a, b in zip(c, h) if b > a)}, Reject turned to Accept on {sum(1 for a, b in zip(c, h) if a < 0.5 <= b)}",
    })
ev = json.loads((ROOT / "site" / "eval-results.json").read_text(encoding="utf-8"))
g = ev.get("gemma", {}).get("items", [])
if g:
    c = [x["clean"] for x in g]; h = [x["haunted"] for x in g]
    rows.insert(0, {"key": "browser", "name": "Gemma 3 1B", "family": "gemma", "clean": statistics.median(c), "haunted": statistics.median(h),
                    "n": len(g), "rose": sum(1 for a, b in zip(c, h) if b > a), "flips": sum(1 for a, b in zip(c, h) if a < 0.5 <= b),
                    "note": f"in the browser, {len(g)} papers: raised on {sum(1 for a, b in zip(c, h) if b > a)}, Reject turned to Accept on {sum(1 for a, b in zip(c, h) if a < 0.5 <= b)}"})
rows.sort(key=lambda x: (x["family"] != "gemma", -x["haunted"]))
out = {"models": rows, "method": r.get("method"), "prompt": r.get("prompt"),
       "lede": "I gave the sixteen real papers to open models as a reviewer, once the way an AI receives them and once with the hidden text taken out, and read each model's own chance of answering “Accept”. The in-browser run reads about the first thousand characters; the Ollama runs read 2,500, and the small models there already accept almost everything without help."}
(ROOT / "site" / "leaderboard.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
for x in rows:
    print(f'{x["name"]:16} {x["note"]:45} {x["clean"]:.3f} -> {x["haunted"]:.3f}')
