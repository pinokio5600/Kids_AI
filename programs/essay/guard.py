"""모델 첨삭에서 뜻을 뒤집는 수정을 걸러낸다 (모델이 지시를 안 따라도 막는 마지막 안전장치).

고학년 150편 검토에서 막아야 했던 사례 (약 50편에 1편):
  - "should not be able to be erased" -> "should be erased"  (not 삭제로 주장이 뒤집힘)
  - "if we don't erase the record" -> don't 삭제
  - not이 들어 있는 반 문장을 통째로 지움

검사: 원문 문장마다, 그 문장 안의 부정어(not, no, never, n't, cannot ...) 개수가
첨삭 후에도 같은지 본다. 달라지면 그 문장의 수정을 모두 되돌린다 (원문 그대로 둠).
문장 단위로 세기 때문에 어순 교정("be not erased" -> "not be erased")이나
"isn't" -> "is not"은 통과한다. (예전에 수정 덩어리 단위로 셌을 때는 이런 정상 교정까지 막았다)
되돌린 문장은 reverted 목록으로 돌려줘서 선생님이 확인할 수 있게 한다.
"""
import re
from difflib import SequenceMatcher

from pydantic import BaseModel

NEGATIONS = {"not", "no", "never", "cannot", "nor", "none", "nobody", "nothing", "neither", "nowhere", "without",
             # 아이들이 아포스트로피 없이 쓴 축약형 ("dont" -> "don't" 교정을 부정어 추가로 오판하지 않게)
             "dont", "doesnt", "didnt", "isnt", "arent", "wasnt", "werent", "cant", "couldnt", "wouldnt",
             "shouldnt", "wont", "havent", "hasnt", "hadnt", "aint", "mustnt", "neednt"}
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’`´][A-Za-z]+)*|[^\sA-Za-z0-9]")
_SENT_END = {".", "!", "?"}


class RevertedEdit(BaseModel):
    original: str   # 원문 문장
    corrected: str  # 모델이 고치려던 문장 (적용 안 됨)
    reason: str     # "negation"


def _tokens(text: str) -> list[tuple[str, int]]:
    return [(re.sub(r"[’`´]", "'", m.group()), m.start()) for m in _TOKEN.finditer(text)]


def _neg(words: list[str]) -> int:
    return sum(w.lower() in NEGATIONS or w.lower().endswith("n't") for w in words)


def _sentence_ids(toks: list[tuple[str, int]], text: str) -> list[int]:
    """토큰마다 몇 번째 문장인지. 마침표류 뒤나 줄바꿈에서 문장이 끝난다"""
    ids, sid = [], 0
    for k, (t, pos) in enumerate(toks):
        if k > 0:
            prev_t, prev_pos = toks[k - 1]
            gap = text[prev_pos + len(prev_t):pos]
            if prev_t in _SENT_END and t not in _SENT_END or "\n" in gap:
                sid += 1
        ids.append(sid)
    return ids


def guard(original: str, corrected: str) -> tuple[str, list[RevertedEdit]]:
    """(안전한 첨삭 글, 되돌린 문장 목록)"""
    o, c = _tokens(original), _tokens(corrected)
    if not o or not c:
        return corrected, []
    ow, cw = [t for t, _ in o], [t for t, _ in c]
    sent = _sentence_ids(o, original)
    ops = [op for op in SequenceMatcher(None, ow, cw, autojunk=False).get_opcodes() if op[0] != "equal"]

    # 문장별 부정어 개수 변화 (수정 덩어리는 시작 위치의 문장에 속한다)
    delta: dict[int, int] = {}
    owner = []
    for _, i1, i2, j1, j2 in ops:
        s = sent[min(i1, len(sent) - 1)]
        owner.append(s)
        delta[s] = delta.get(s, 0) + _neg(cw[j1:j2]) - _neg(ow[i1:i2])
    bad = {s for s, d in delta.items() if d != 0}
    if not bad:
        return corrected, []

    def span(toks, text, i, j):
        """토큰 i..j-1이 차지하는 글자 (뒤따르는 공백 포함, 다음 토큰 직전까지)"""
        if i >= j:
            return ""
        end = toks[j][1] if j < len(toks) else len(text)
        return text[toks[i][1]:end]

    out = [corrected[:c[0][1]]]
    reverted: dict[int, list] = {}
    k = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, ow, cw, autojunk=False).get_opcodes():
        new = span(c, corrected, j1, j2)
        if op == "equal":
            out.append(new)
            continue
        s = owner[k]
        k += 1
        if s in bad:
            old = span(o, original, i1, i2)
            if old and not old[-1].isspace() and new[-1:].isspace():
                old += new[len(new.rstrip()):]
            out.append(old)
            reverted.setdefault(s, [])
        else:
            out.append(new)

    # 선생님 확인용: 되돌린 문장의 원문과 모델이 고치려던 문장
    edits = []
    for s in sorted(reverted):
        idx = [i for i, x in enumerate(sent) if x == s]
        orig_s = original[o[idx[0]][1]:o[idx[-1]][1] + len(o[idx[-1]][0])]
        # 모델 문장: 이 문장 원문 토큰에 대응하는 첨삭 토큰 범위
        js = []
        for op, i1, i2, j1, j2 in SequenceMatcher(None, ow, cw, autojunk=False).get_opcodes():
            if op == "equal":
                lo, hi = max(i1, idx[0]), min(i2, idx[-1] + 1)
                if lo < hi:
                    js += list(range(j1 + lo - i1, j1 + hi - i1))
            elif i1 <= idx[-1] and (i2 > idx[0] or (i1 == i2 and i1 >= idx[0])):
                js += list(range(j1, j2))
        model_s = corrected[c[min(js)][1]:c[max(js)][1] + len(c[max(js)][0])] if js else ""
        edits.append(RevertedEdit(original=orig_s, corrected=model_s, reason="negation"))
    return "".join(out), edits
