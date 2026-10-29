import sys, time, os, urllib.request

EVAL = sys.argv[1]
IDS = """2408.13940v3 2403.08142v2 2501.13461v1 2212.08983v2 2501.08667v1 2506.00418v1 2505.15075v1
2406.17241v3 2502.19918v2 2506.03074v1 2505.11718v1 2407.16803v3 2506.13901v1 2506.01324v1
2505.22998v1 2406.17253v2 2506.11111v1 2505.16211v1""".split()
UA = {"User-Agent": "ghostwriting-eval/0.1 (hackathon research; polite single requests)"}
out = os.path.join(EVAL, "real")
os.makedirs(out, exist_ok=True)
for i in IDS:
    p = os.path.join(out, i + ".pdf")
    if os.path.exists(p) and os.path.getsize(p) > 10000:
        continue
    try:
        req = urllib.request.Request("https://arxiv.org/pdf/" + i, headers=UA)
        data = urllib.request.urlopen(req, timeout=60).read()
        if data[:4] != b"%PDF":
            print("NOT PDF", i, data[:80]); continue
        open(p, "wb").write(data)
        print("ok", i, len(data))
    except Exception as e:
        print("FAIL", i, e)
    time.sleep(3)
