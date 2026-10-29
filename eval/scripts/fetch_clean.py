import sys, os, re, time, json, urllib.request

EVAL = sys.argv[1]
OUT = os.path.join(EVAL, "clean")
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "ghostwriting-eval/0.1 (hackathon research; polite single requests)"}
PLAN = [("cs.CL", 10), ("cs.LG", 10), ("cs.CV", 10), ("cs.AI", 5), ("cs.CR", 5)]
REAL = {r["id"] for r in json.load(open(os.path.join(EVAL, "real", "manifest.json"), encoding="utf-8"))}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()


entries, seen = [], set()
for cat, n in PLAN:
    x = get(f"https://export.arxiv.org/api/query?search_query=cat:{cat}&sortBy=submittedDate&sortOrder=descending&max_results={n + 8}").decode("utf-8")
    time.sleep(3)
    got = 0
    for e in x.split("<entry>")[1:]:
        full = re.search(r"<id>http://arxiv.org/abs/([^<]+)</id>", e).group(1)
        pid, ver = re.match(r"(.+?)(v\d+)$", full).groups()
        if pid in seen or pid in REAL:
            continue
        title = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", e, re.S).group(1)).strip()
        pub = re.search(r"<published>(.*?)</published>", e).group(1)
        prim = re.search(r'<arxiv:primary_category[^>]*term="([^"]+)"', e)
        seen.add(pid)
        entries.append({"id": pid, "version": ver, "url": f"https://arxiv.org/pdf/{full}", "title": title,
                        "query_category": cat, "primary_category": prim.group(1) if prim else None,
                        "published": pub, "file": f"clean/{full}.pdf"})
        got += 1
        if got >= n:
            break

ok = []
for r in entries:
    p = os.path.join(EVAL, r["file"])
    if not (os.path.exists(p) and os.path.getsize(p) > 10000):
        try:
            data = get(r["url"])
            if data[:4] != b"%PDF":
                print("NOT PDF", r["id"]); time.sleep(3); continue
            open(p, "wb").write(data)
            print("ok", r["id"], len(data), flush=True)
        except Exception as ex:
            print("FAIL", r["id"], ex, flush=True); time.sleep(3); continue
        time.sleep(3)
    ok.append(r)
json.dump(ok, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print(len(ok), "clean PDFs")
