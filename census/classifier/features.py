# -*- coding: utf-8 -*-
"""Numeric features for one hidden-looking run (a dict from census/crawl.py's scan()).

Every feature is a float; NaN when the run has no span measurements (census lines written before the crawler
stored spans), which TabPFN handles natively. FEATURES lists the columns in order; `featurize(run)` returns them.

Geometry / appearance (from run["spans"], each {"size","lum","bg","bbox","font"}; page_w/page_h from the run)
  size_min, size_mean, size_max      font size in pt
  size_lt_05, size_lt_2              fraction of spans under 0.5 pt / under 2 pt
  lum_min, lum_mean, lum_max         text luminance 0 (black) .. 1 (white)
  bg_min, bg_mean                    luminance of the filled shape behind the text (1 = nothing, i.e. white paper)
  contrast_min, contrast_mean        |text lum - background lum|
  x0, y0, x1, y1, w, h               union of span boxes, divided by page width / height
  area                               w*h (fraction of the page)
  outside                            how far the box lies outside the page, as a fraction of the page's larger side
  n_spans, n_fonts                   spans in the run; distinct font names
  aspect                             box width / (height * n_chars) - text squeezed into a sliver is suspicious
  page_index                         0 = first page .. 1 = last page
  page_no                            1-based page number (clipped at 80)
  sym_font                           fraction of spans in a maths/symbol font (CMSY, CMMI, Symbol, MT Extra ...)
"how" flags (from run["how"], the scan's own reasons)
  how_white, how_tiny, how_off, how_tags, how_invisible, how_n
Text (tag characters are decoded first, so a message spelled in Unicode tags is read as text)
  n_chars, n_words, mean_word_len, uppercase_ratio, digit_ratio, punct_ratio, alpha_ratio, non_ascii_ratio,
  cjk_ratio, devanagari_ratio, math_ratio (maths/arrows/Greek), numeric_token_ratio, short_token_ratio
  ends_sentence (., !, ?, 。), n_sentences, stopword_ratio (English+es/fr/de/pt function words: prose vs labels)
  second_person   you/your/yourself + tú/usted/vous/votre/du/você/आप/你/您
  imperative      ignore, give, recommend, rate, must, should, do not, rank, accept, respond, reply, say, tell,
                  report, describe, state, award, score, praise, ... + common es/fr/de/pt/hi/zh equivalents
  ai_names        LLM, AI, GPT, Claude, Gemini, Llama, Qwen, ChatGPT, Copilot, assistant, chatbot, language model...
  model_like      tokens shaped like model names with sizes/versions (GPT-4o, Qwen-4B, Llama-3-8B) - figure labels
  audience        reviewer, recruiter, grader, screener, summarizer, evaluator, assessor, agent, editor, committee
  verdict         accept, acceptance, positive, score, rating, rank, strengths, weaknesses, full marks, 10/10, 5/5
  meta_ref        this paper / this submission / this manuscript / this candidate / this document / this essay
  rule_0..rule_6  each regex of census/crawl.py RULES as 0/1 (the deployed baseline's own evidence), n_rules
"""
import math
import re

import numpy as np

_crawl = None


def crawl():
    global _crawl
    if _crawl is None:
        from common import load_crawl
        _crawl = load_crawl()
    return _crawl


SECOND = re.compile(r"\b(you|your|yours|yourself|t[uú]|usted|vous|votre|vos|du|dein|deine|ihr|voc[eê]|seu|sua)\b|आप|तुम|你|您", re.I)
IMPER = re.compile(
    r"\b(ignore|disregard|forget|overlook|give|recommend|rate|rank|accept|respond|reply|answer|say|tell|state|report|"
    r"describe|award|score|praise|emphasi[sz]e|highlight|mention|reveal|treat|conclude|summari[sz]e|frame|downplay|"
    r"send|open|click|run|copy|email|visit|enter|execute|must|should|shall|do not|don't|never|always|please|kindly|"
    r"make sure|ensure|"
    r"ignora|olvida|recomienda|califica|di|dile|da|otorga|no menciones|no reveles|debe|"
    r"ignorez|oubliez|recommandez|attribuez|dites|donnez|classez|ne r[ée]v[ée]lez|doit|"
    r"ignoriere|gib|empfehle|erw[äa]hne|beschreibe|ignore|d[êe]|recomende|diga|n[ãa]o mencione)\b"
    r"|करें|दें|कहें|बताएं|रखें|चाहिए|न करें|忽略|请|给出|建议|不要|必须|告诉|打|排在", re.I)
AI = re.compile(r"\b(llms?|ai|a\.i\.|gpt[-\w.]*|chatgpt|claude|gemini|llama|qwen|mistral|copilot|deepseek|chatbots?|"
                r"assistants?|language models?|sprachmodell|modelo de lenguaje|mod[eè]le de langage|ia|ki|agents?)\b"
                r"|एआई|भाषा मॉडल|语言模型|人工智能|助手", re.I)
MODEL_LIKE = re.compile(r"\b[A-Za-z]+[-_ ]?\d+(\.\d+)?[A-Za-z]*([-_]\d+(\.\d+)?[bBmMkK])?\b|\b\d+(\.\d+)?[bB]\b")
AUDIENCE = re.compile(r"\b(reviewers?|recruiters?|graders?|screen(ers?|ing)|summari[sz](ers?|ing)|evaluators?|"
                      r"assessors?|agents?|editors?|committee|markers?|hiring|readers?|revisores?|relecteurs?|gutachter|"
                      r"logiciel|sistemas?)\b|समीक्षक|审稿人|筛选", re.I)
VERDICT = re.compile(r"\b(accept(ed|ing|ance)?|positive|score|rating|rate|rank(ed)?|strengths?|weakness(es)?|full marks|"
                     r"highest|top|best|maximum|flawless|groundbreaking|excellent|outstanding|exceptional|glowing|"
                     r"publish|publication|acceptation|aceptaci[oó]n|aceitação|annahme|nota m[aá]xima|note maximale|"
                     r"h[öo]chstnote)\b|10/10|5/5|सकारात्मक|स्वीकार|अंक|正面|最高分|录用|接收", re.I)
META = re.compile(r"\bth(is|ese) (paper|submission|manuscript|candidate|applicant|document|essay|work|study|report|"
                  r"cv|resume|article|assignment|page)\b|este (art[ií]culo|trabajo|documento|estudio|manuscrito)|"
                  r"cet (article)|ce (travail|document|manuscrit)|cette [ée]tude|diese[rs]? (arbeit|artikel|studie)|"
                  r"इस (शोध|पेपर|दस्तावेज़|काम)|本文|这篇|该候选人|这项研究", re.I)
STOP = set("""the a an of to and in is are be for on with that this it as by at from or not we our their which was were
has have will can may its these those than then so such into also but if when all any each more most other some no
el la los las de del y en que es por con para un una se al lo como más pero sus le du des et les est pour dans une qui
sur pas ne il der die das und ist mit für von zu den nicht ein eine o os as da do e em um uma não para com""".split())
MATHC = re.compile(r"[Ͱ-Ͽ←-⋿∀-⋿⌀-⏿⟀-⟯⨀-⫿]")
SYMFONT = re.compile(r"cmsy|cmmi|cmex|msam|msbm|symbol|mt ?extra|math|stix|euclid|wasy|rsfs", re.I)


def detag(s):
    return "".join(chr(ord(c) - 0xE0000) if 0xE0000 <= ord(c) <= 0xE007F else c for c in s)


def _nan():
    return float("nan")


def featurize(run):
    f = {}
    spans = run.get("spans") or []
    W, H = run.get("page_w") or 612.0, run.get("page_h") or 792.0
    text_raw = run.get("text") or ""
    text = " ".join(detag(text_raw).split())
    if spans:
        sz = np.array([s["size"] for s in spans], float)
        lu = np.array([s["lum"] for s in spans], float)
        bg = np.array([s.get("bg", 1.0) for s in spans], float)
        bb = np.array([s["bbox"] for s in spans], float)
        x0, y0, x1, y1 = bb[:, 0].min(), bb[:, 1].min(), bb[:, 2].max(), bb[:, 3].max()
        f.update(size_min=sz.min(), size_mean=sz.mean(), size_max=sz.max(), size_lt_05=(sz < .5).mean(),
                 size_lt_2=(sz < 2).mean(), lum_min=lu.min(), lum_mean=lu.mean(), lum_max=lu.max(),
                 bg_min=bg.min(), bg_mean=bg.mean(), contrast_min=np.abs(lu - bg).min(),
                 contrast_mean=np.abs(lu - bg).mean(),
                 x0=x0 / W, y0=y0 / H, x1=x1 / W, y1=y1 / H, w=(x1 - x0) / W, h=(y1 - y0) / H,
                 area=(x1 - x0) * (y1 - y0) / (W * H),
                 outside=max(0.0, -x0, x1 - W, -y0, y1 - H) / max(W, H),
                 n_spans=len(spans), n_fonts=len({s.get("font", "") for s in spans}),
                 aspect=math.log1p((x1 - x0) / max(1e-3, (y1 - y0)) / max(1, len(text))),
                 sym_font=np.mean([bool(SYMFONT.search(s.get("font", ""))) for s in spans]))
    else:
        for k in ["size_min", "size_mean", "size_max", "size_lt_05", "size_lt_2", "lum_min", "lum_mean", "lum_max",
                  "bg_min", "bg_mean", "contrast_min", "contrast_mean", "x0", "y0", "x1", "y1", "w", "h", "area",
                  "outside", "n_spans", "n_fonts", "aspect", "sym_font"]:
            f[k] = _nan()
    f["page_index"] = run.get("page_index", _nan()) if run.get("page_index") is not None else _nan()
    f["page_no"] = min(80, run.get("page") or 1)
    how = " ".join(run.get("how") or [])
    f.update(how_white=float("white" in how), how_tiny=float(" pt type" in how), how_off=float("off the page" in how),
             how_tags=float("tag" in how), how_invisible=float("invisible" in how), how_n=len(run.get("how") or []))
    n = max(1, len(text))
    words = text.split()
    nw = max(1, len(words))
    letters = [c for c in text if c.isalpha()]
    f.update(
        n_chars=len(text), n_words=len(words),
        mean_word_len=sum(len(w) for w in words) / nw,
        uppercase_ratio=sum(c.isupper() for c in letters) / max(1, len(letters)),
        digit_ratio=sum(c.isdigit() for c in text) / n,
        punct_ratio=sum((not c.isalnum()) and not c.isspace() for c in text) / n,
        alpha_ratio=len(letters) / n,
        non_ascii_ratio=sum(ord(c) > 127 for c in text) / n,
        cjk_ratio=len(re.findall(r"[　-鿿]", text)) / n,
        devanagari_ratio=len(re.findall(r"[ऀ-ॿ]", text)) / n,
        math_ratio=len(MATHC.findall(text)) / n,
        numeric_token_ratio=sum(bool(re.fullmatch(r"[−\-+]?[\d.,%]+", w)) for w in words) / nw,
        short_token_ratio=sum(len(w) <= 2 for w in words) / nw,
        ends_sentence=float(bool(re.search(r"[.!?。！？।]\s*$", text))),
        n_sentences=len(re.findall(r"[.!?。！？।](\s|$)", text)),
        stopword_ratio=sum(w.lower().strip(".,;:!?") in STOP for w in words) / nw,
        second_person=len(SECOND.findall(text)),
        imperative=len(IMPER.findall(text)),
        ai_names=len(AI.findall(text)),
        model_like=len(MODEL_LIKE.findall(text)) / nw,
        audience=len(AUDIENCE.findall(text)),
        verdict=len(VERDICT.findall(text)),
        meta_ref=len(META.findall(text)),
    )
    rules = crawl().RULES
    hits = [float(bool(rx.search(text))) for rx, _ in rules]
    for i, h in enumerate(hits):
        f[f"rule_{i}"] = h
    f["n_rules"] = sum(hits)
    return f


FEATURES = list(featurize({"text": "x", "spans": [{"size": 1, "lum": 0, "bg": 1, "bbox": [0, 0, 1, 1], "font": "f"}],
                           "how": [], "page": 1, "page_index": 0}).keys())


def matrix(runs):
    out = []
    for r in runs:
        f = featurize(r)
        out.append([f[k] for k in FEATURES])
    return np.array(out, dtype=float).reshape(len(out), len(FEATURES))
