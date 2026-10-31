"""Shared helpers for the ghost classifier: paths, the crawler's scan/rules, and the TabPFN client setup."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))          # ghostwriting/
EVAL = os.path.join(ROOT, "eval")
CENSUS = os.path.join(ROOT, "census", "results.jsonl")
CACHE = os.path.join(HERE, "cache")
MODEL_VERSION = "v3.5"


def load_crawl():
    """census/crawl.py as a module (for scan() and rules()), without running its main()."""
    spec = importlib.util.spec_from_file_location("ghost_crawl", os.path.join(ROOT, "census", "crawl.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _token():
    """TABPFN_TOKEN from ghostwriting/.env (never printed or written anywhere)."""
    tok = os.environ.get("TABPFN_TOKEN")
    if tok:
        return tok.strip()
    with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("TABPFN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("TABPFN_TOKEN not found in ghostwriting/.env")


def tabpfn_classifier(**kw):
    """A hosted TabPFN classifier pinned to the newest model version the client offers (v3.5)."""
    import tabpfn_client
    from tabpfn_client import TabPFNClassifier
    tabpfn_client.set_access_token(_token())
    return TabPFNClassifier.create_default_for_version(MODEL_VERSION, **kw)
