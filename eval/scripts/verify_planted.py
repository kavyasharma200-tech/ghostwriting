import sys, os, json, re
import pymupdf

sys.stdout.reconfigure(encoding="utf-8")
P = os.path.join(sys.argv[1], "planted")
man = json.load(open(os.path.join(P, "manifest.json"), encoding="utf-8"))


def norm(s):
    s = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) < 0xE007F else c for c in s)
    s = s.replace("​", "").replace("‌", "")
    return re.sub(r"\s+", " ", s).strip()


def pix(path):
    d = pymupdf.open(path)
    return d[0].get_pixmap(dpi=100).samples


ctrl = {k: pix(os.path.join(P, f"{k}__control.pdf")) for k in ("abstract", "resume", "essay")}
bad = 0
for m in man:
    if m["format"] != "pdf":
        continue
    path = os.path.join(P, m["file"])
    d = pymupdf.open(path)
    pg = d[0]
    raw = pg.get_text(clip=pymupdf.INFINITE_RECT())
    txt = norm(raw)
    if m["hidden_text"] is None:
        ok_text = not re.search(r"IGNORE|AI |LLM|language model|ChatGPT", txt)
    else:
        ok_text = norm(m["hidden_text"]) in txt
    px = pix(path)
    a = ctrl[m["kind"]]
    diff = sum(1 for i in range(0, len(px), 3) if px[i:i + 3] != a[i:i + 3])
    has_zw = "​" in raw
    has_tag = any(0xE0000 <= ord(c) <= 0xE007F for c in raw)
    flag = "OK " if ok_text else "BAD"
    if not ok_text:
        bad += 1
    print(f"{flag} {m['file']:<34} text_found={ok_text} diff_px_vs_control={diff:<6} zw={has_zw} tag={has_tag}")
print("bad:", bad)
