"""첨삭 전후를 비교해 이 글에서 실제로 고친 실수 종류를 센다 (개선 제안 호출에 넣는다).

2026-11-27 블라인드 비교 (40편, 제안 320개, 평가자 2명): 9B 모델은 고친 적 없는 실수(대문자, 과거형 ...)를
제안에 자주 썼다. 프로그램이 센 실수 종류를 주고 "목록에 없는 종류는 말하지 마"라고 하니
엉뚱한 제안이 28% -> 14%로 줄었다 (속도 그대로). 분류는 대략이면 된다: 모델에게 주는 힌트다.
"""
import re
from difflib import SequenceMatcher

from programs.essay.align import opcodes

_TOK = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*|[^\sA-Za-z0-9]")
ARTICLES = {"a", "an", "the"}
PREPS = {"in", "on", "at", "for", "to", "of", "about", "with", "from", "by", "into"}
PUNCT = set(".,;:!?")
BE = {"is", "are", "was", "were", "am", "be", "been", "has", "have", "had"}
AGREE = [{"is", "are"}, {"was", "were"}, {"has", "have"}, {"do", "does"}, {"doesn't", "don't"}, {"isn't", "aren't"}]

CAPITALIZATION = "capitalization"
TENSE = "verb forms and tenses"
AGREEMENT = "word endings: plural -s or verb agreement"
SPELLING = "spelling"


def _word_pair(x: str, y: str) -> str:
    if any({x, y} == p for p in AGREE):
        return AGREEMENT
    if x.rstrip("s") == y.rstrip("s") or x + "es" == y or y + "es" == x:
        return AGREEMENT
    if x[:3] == y[:3] and re.search(r"(?:ed|d|ing|en)$", x + " " + y) and SequenceMatcher(None, x, y).ratio() >= 0.6:
        return TENSE
    if {x, y} & BE or x in ("will", "can") or y in ("will", "can"):
        return TENSE
    if min(len(x), len(y)) >= 4 and SequenceMatcher(None, x, y).ratio() >= 0.7:
        return SPELLING
    return "word choice"


def mistake_types(original: str, corrected: str) -> dict[str, list[str]]:
    """{실수 종류: ["원문 -> 고친 말", ...]}"""
    a = [t.replace("’", "'") for t in _TOK.findall(original)]
    b = [t.replace("’", "'") for t in _TOK.findall(corrected)]
    out: dict[str, list[str]] = {}

    def add(k, ex):
        out.setdefault(k, []).append(ex)

    for op, i1, i2, j1, j2 in opcodes([x.lower() for x in a], [x.lower() for x in b]):
        if op == "equal":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                if x != y:
                    add(CAPITALIZATION, f"{x} -> {y}")
            continue
        old, new = a[i1:i2], b[j1:j2]
        ex = f"{' '.join(old) or '(nothing)'} -> {' '.join(new) or '(removed)'}"
        ol, nl = [x.lower() for x in old], [x.lower() for x in new]
        diff = set(ol) ^ set(nl)
        rest_o = [x for x in ol if x not in ARTICLES | PREPS | PUNCT]
        rest_n = [x for x in nl if x not in ARTICLES | PREPS | PUNCT]
        if diff <= PUNCT:
            add("punctuation / sentence boundaries", ex)
            continue
        if diff <= ARTICLES | PUNCT:
            add("articles (a, an, the)", ex)
            continue
        if diff <= PREPS | ARTICLES | PUNCT:
            add("prepositions", ex)
            continue
        if "".join(ol) == "".join(nl):
            add("spacing (words joined or split)", ex)
            continue
        if set(nl) - set(ol) & ARTICLES:
            add("articles (a, an, the)", ex)
        if diff & PREPS:
            add("prepositions", ex)
        if rest_o and len(rest_o) == len(rest_n):
            for x, y in zip(rest_o, rest_n):
                if x != y:
                    add(_word_pair(x, y), f"{x} -> {y}")
            continue
        if rest_o and not rest_n and set(rest_o) <= BE | {"do", "does", "did"}:
            add(TENSE, ex)
            continue
        if not rest_o and rest_n:
            add("missing words", ex)
            continue
        add("sentence structure / word order", ex)
    return out


def mistakes_text(types: dict[str, list[str]]) -> str:
    """제안 호출에 넣을 문장. 고친 실수는 아이가 빨간 글씨로 이미 보므로 문법 항목은 3번 이상 반복된 종류만 1개까지."""
    if not types:
        return "Mistakes the program corrected: none. Write no grammar item."
    top = sorted(types.items(), key=lambda kv: -len(kv[1]))
    lines = ", ".join(f"{k} {len(v)}" for k, v in top)
    return (f"Mistakes the program corrected (already shown in red; type count): {lines}.\n"
            "Only a type with 3 or more may get one grammar item. Do not mention any type not listed.")
