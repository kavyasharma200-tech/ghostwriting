"""ghostwriting: check documents for text hidden for the AI that reads them.

    ghostwriting scan ./applications --out report.csv    a folder of documents, one row each, haunted first
    ghostwriting canary paper.pdf                        a copy carrying a harmless hidden sentence, to test your AI
    ghostwriting mcp                                     the same checks, as tools for an AI agent (stdio)
"""
import argparse
import csv
import json
import sys
from pathlib import Path

from .canary import TRICKS, canary, sentence
from .scanner import TEXT_SUFFIXES, minor, scan, talks_to_ai

SUFFIXES = {".pdf"} | TEXT_SUFFIXES


def documents(paths):
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUFFIXES)
        elif p.is_file():
            yield p
        else:
            print(f"no such file or folder: {p}", file=sys.stderr)


def row(path):
    try:
        pages, runs = scan(path.read_bytes(), ink=True)
    except Exception as e:
        return {"file": str(path), "verdict": "could not read", "ghosts": 0, "other_hidden": 0, "pages": 0,
                "page": "", "how": "", "asks": "", "says": str(e)[:200]}
    ghosts = [r for r in runs if talks_to_ai(r["ai"])]
    other = [r for r in runs if not talks_to_ai(r["ai"]) and not minor(r["text"])]
    first = (ghosts or other or [None])[0]
    return {
        "file": str(path),
        "verdict": "haunted" if ghosts else "hidden text" if other else "clean",
        "ghosts": len(ghosts), "other_hidden": len(other), "pages": pages,
        "page": first["page"] if first else "",
        "how": "; ".join(first["how"]) if first else "",
        "asks": "; ".join(first["ai"]) if first else "",
        "says": first["text"][:300] if first else "",
    }


def cmd_scan(a):
    files = list(documents(a.paths))
    if not files:
        sys.exit("nothing to read: give PDFs, text files or folders")
    rows = []
    for n, f in enumerate(files, 1):
        rows.append(row(f))
        if not a.quiet:
            r = rows[-1]
            mark = {"haunted": "HAUNTED", "hidden text": "hidden ", "clean": "clean  "}.get(r["verdict"], "error  ")
            print(f"[{n}/{len(files)}] {mark} {f}" + (f"  p{r['page']}: {r['says'][:90]}" if r["verdict"] == "haunted" else ""), file=sys.stderr)
    order = {"haunted": 0, "hidden text": 1, "could not read": 2, "clean": 3}
    rows.sort(key=lambda r: (order[r["verdict"]], r["file"]))
    if a.json:
        out = json.dumps(rows, ensure_ascii=False, indent=1)
        Path(a.out).write_text(out, encoding="utf-8") if a.out else print(out)
    else:
        f = open(a.out, "w", newline="", encoding="utf-8") if a.out else sys.stdout
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
        if a.out:
            f.close()
    haunted = sum(r["verdict"] == "haunted" for r in rows)
    print(f"\n{len(rows)} read, {haunted} haunted, {sum(r['verdict'] == 'hidden text' for r in rows)} with other hidden text"
          + (f", report in {a.out}" if a.out else ""), file=sys.stderr)
    sys.exit(1 if haunted and a.fail else 0)


def cmd_canary(a):
    src = Path(a.file)
    out = Path(a.out) if a.out else src.with_name(f"{src.stem}-canary{src.suffix}")
    tricks = a.tricks.split(",")
    out.write_bytes(canary(src.read_bytes(), a.word, tricks))
    # Prove the copy is haunted the way a real one would be: Ghostwriting must find the sentence.
    _, runs = scan(out.read_bytes())
    seen = sorted({h for r in runs if a.word in r["text"] for h in r["how"]})
    print(f"Wrote {out}, hiding: \"{sentence(a.word)}\"")
    print(f"Ghostwriting sees it as: {', '.join(seen) or 'nothing (tell me, that is a bug)'}")
    print(f"Now give {out.name} to your AI the way you normally would and ask for a summary.\n"
          f"If the word \"{a.word}\" turns up in the answer, your pipeline obeys text a person can't see.")


def cmd_mcp(a):
    from .mcp_server import main
    main()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ghostwriting", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="check PDFs and text files, or whole folders of them")
    s.add_argument("paths", nargs="+")
    s.add_argument("--out", help="write the report here (CSV, or JSON with --json) instead of to the screen")
    s.add_argument("--json", action="store_true")
    s.add_argument("--fail", action="store_true", help="exit with 1 when anything is haunted (for CI)")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(fn=cmd_scan)
    c = sub.add_parser("canary", help="make a copy with a harmless hidden sentence, to test your own AI")
    c.add_argument("file")
    c.add_argument("--out")
    c.add_argument("--word", default="pumpkin")
    c.add_argument("--tricks", default=",".join(TRICKS), help=f"which hiding tricks to use (PDF only): {', '.join(TRICKS)}")
    c.set_defaults(fn=cmd_canary)
    m = sub.add_parser("mcp", help="serve check_document and check_folder to an AI agent over stdio")
    m.set_defaults(fn=cmd_mcp)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    a.fn(a)


if __name__ == "__main__":
    main()
