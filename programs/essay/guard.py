"""모델 첨삭에서 위험한 수정을 걸러낸다 (모델이 지시를 안 따라도 막는 마지막 안전장치).

문장 단위로 되돌리는 것 (그 문장에 걸친 수정을 모두 원문으로):
  - negation: 문장 안 부정어(not, no, never, n't, cannot ...) 개수가 달라짐 -> 주장이 뒤집힐 수 있다
      "should not be able to be erased" -> "should be erased", "if we don't erase" -> don't 삭제
      어순 교정("be not erased" -> "not be erased"), "isn't" -> "is not"은 개수가 같아서 통과
  - added_words: 원문 문장에 없던 내용어(기능어·철자 고친 단어 제외)를 한 곳에 2개 이상 덧붙이거나, [ ] ( ) 설명을 넣음
      ("...was clear", "Claudia from The Baby-Sitters Club", "[to act violently]", "some may not be treated equally")
  - deleted_words: 문장에서 내용어가 3개 이상 아예 사라짐 (반복된 말 지우기·어순 바꾸기는 통과)
      ("And you can see every day!" 통째 삭제, 문장 끝 잘라 먹기)
  - added_words(절): 원문 문장에 없던 접속사(if, because, when ...)와 함께 3단어 이상 새 절을 붙임
      ("...not understand the homework" -> "... if they are tired")
  - name: 원문의 한글 단어(반 이름 등)를 지우거나 바꿈 ("in 티카 AT" -> "in Class AT")
  - name: 문장 중간의 대문자 단어 중 흔한 단어(common_words.txt)가 아닌 것을 철자가 많이 다른 말로 바꾸거나 지움
      ("Gunham-do" -> "Dokdo", 사람 이름을 다른 이름으로, 이름 삭제). 철자 고치기(Japen -> Japan, GSP -> GPS)는 통과.
      문장째 되돌리는 이유: 모델이 "지우기 + 넣기" 두 덩어리로 바꾼 경우 하나만 되돌리면 글이 중복된다.
수정 하나만 되돌리는 것 (같은 문장의 다른 교정은 살린다):
  - quote: 따로 떨어진 따옴표만 바꾸거나 넣고 뺌 ("..." -> '...', 닫는 따옴표 지움, 문장 앞에 ' 하나 끼워 넣기).
      소유격 아포스트로피(students')와 축약형(it's)은 따옴표로 보지 않는다.
2026-11-24 300편 비교 검토에서 실제로 나온 실수들이 기준이다.
되돌린 내용은 reverted 목록으로 돌려줘서 선생님이 확인할 수 있게 한다.
"""
import re
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel

NEGATIONS = {"not", "no", "never", "cannot", "nor", "none", "nobody", "nothing", "neither", "nowhere", "without",
             # 아이들이 아포스트로피 없이 쓴 축약형 ("dont" -> "don't" 교정을 부정어 추가로 오판하지 않게)
             "dont", "doesnt", "didnt", "isnt", "arent", "wasnt", "werent", "cant", "couldnt", "wouldnt",
             "shouldnt", "wont", "havent", "hasnt", "hadnt", "aint", "mustnt", "neednt"}
# 한글은 한 덩어리로 (반 이름 "티카", "샘물1M" 등. 글자마다 쪼개지면 이름 보호가 안 된다)
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’`´][A-Za-z]+)*|[가-힣]+|[^\sA-Za-z0-9]")
_HANGUL = re.compile(r"[가-힣]")
# 원문 문장에 없던 접속사로 절을 새로 붙이면 내용을 지어낸 것 ("... the homework" -> "... the homework if they are tired")
CLAUSE_CONJ = {"if", "because", "when", "while", "although", "though", "unless", "since", "whereas"}
MIN_CLAUSE = 3  # 접속사 포함 이만큼 늘어나면 새 절로 본다
_SENT_END = {".", "!", "?"}


class RevertedEdit(BaseModel):
    original: str   # 원문 문장
    corrected: str  # 모델이 고치려던 문장 (적용 안 됨)
    reason: str     # negation, added_words, deleted_words, quote, name (여러 개면 쉼표로)


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


_QUOTES = set("\"'“”‘’`´")
# name도 문장째: 모델이 "지우기 + 넣기" 두 덩어리로 바꾼 경우 하나만 되돌리면 글이 중복된다
SENTENCE_RULES = ("negation", "added_words", "deleted_words", "name")
MAX_ADDED = 1    # 문장에 없던 내용어 2개 이상 덧붙이면 되돌림 ("the difference was clear")
MAX_DELETED = 2  # 문장에서 내용어 3개 이상 사라지면 되돌림
# 내용어 개수에서 빼는 기능어 (관사·전치사·대명사·조동사 등은 문법 교정으로 넣고 빼는 게 정상)
_FUNCTION = set("""a an the this that these those it its they them their he him his she her we us our you your
i me my mine to of in on at for with by from about as into onto than then so and or but if because when
while is are was were be been being am do does did have has had will would can could should may might must
not no also there here what which who whom whose how why where very too just more most much many some any
all each other another one ones such own same up out over""".split())


_COMMON = {w for w in (Path(__file__).with_name("common_words.txt").read_text(encoding="utf-8").split())
           if not w.startswith("#")}
_TEMPLATE = set("([<{")
# 아포스트로피 없이 쓴 축약형 (Im -> I'm)
_NO_APOS = {"im", "ive", "id", "ill", "youre", "theyre", "hes", "shes", "thats", "whats", "lets", "its"} | NEGATIONS


def _quote_tokens(toks, text) -> list[int]:
    """따옴표 토큰 위치. 소유격 아포스트로피(students' / patients')는 뺀다"""
    out = []
    for k, (t, pos) in enumerate(toks):
        if t and all(ch in _QUOTES for ch in t):
            if t == "'" and k > 0 and toks[k - 1][0].lower().endswith("s") and \
                    toks[k - 1][1] + len(toks[k - 1][0]) == pos:
                continue
            out.append(k)
    return out


def _close(a: str, b: str) -> bool:
    """철자 고치기 정도로 비슷한가 (Japen -> Japan, Tje -> The, Space X -> SpaceX)"""
    a, b = a.lower(), b.lower()
    if SequenceMatcher(None, a, b).ratio() >= 0.75 or sorted(a) == sorted(b):
        return True  # 철자, 글자 순서(GSP -> GPS)
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) <= 1


_CLASS_CODE = re.compile(r"^\d*[A-Z]{1,3}\d*$")  # 반 코드: 1M, AT, M, 5M


def _name_slot(ow: list[str], k: int) -> bool:
    """ow[k]가 자기소개 이름이나 반 이름 자리인가"""
    prev = [w.lower() for w in ow[max(0, k - 3):k]]
    nxt = ow[k + 1] if k + 1 < len(ow) else ""
    if _CLASS_CODE.match(nxt):                     # 여울1M, 티카 AT, 샘물 M
        return True
    if prev[-1:] in (["i'm"], ["im"]) or prev[-2:] == ["i", "am"]:
        return True                                # I'm 시연 / I am 시연
    return prev[-2:] == ["name", "is"] or prev[-1:] == ["called"]  # my name is 정아


def _content(words) -> list[str]:
    return [w.lower() for w in words if w[:1].isalpha() and w.lower() not in _FUNCTION]


def _op_reasons(o, c, oq, cq, i1, i2, j1, j2, sent, o_words, c_words) -> list[str]:
    """o_words / c_words: 이 수정이 속한 문장의 원문 / 첨삭 단어 집합 (소문자)"""
    ow, cw = [t for t, _ in o], [t for t, _ in c]
    old, new = ow[i1:i2], cw[j1:j2]
    why = []
    # 덧붙이기: 원문 문장에 없던 내용어를 한 곳에 MAX_ADDED개 넘게, 또는 [ ] ( ) 설명을 새로 넣음
    def is_new(w):  # 철자 고치기(cumputer -> computer), 띄어쓰기(hardwork -> hard work)는 새 내용이 아니다
        return w not in o_words and not any(w in x or _close(w, x) for x in o_words if len(x) > 2)
    added = [w for w in _content(new) if is_new(w)]
    # 한글 단어를 영어로 옮긴 것 (세월호 -> Sewol, 연합뉴스 -> Yonhap News)은 덧붙이기가 아니다:
    # 문장의 한글 단어 수만큼은 새 영어 단어로 치지 않는다
    hangul_n = sum(bool(_HANGUL.match(x)) for x in o_words)
    if any(_HANGUL.match(w) for w in old):
        added = []
    elif hangul_n:
        added = added[2 * hangul_n:]
    # 새 절: 원문 문장에 없던 접속사 + 원문에 없던 내용어. 아이 말을 접속사로 정리하는 교정
    # ("people eat only vegetables then they feel bad" -> "... feel bad when they eat only vegetables")는 통과
    def conj_in_original(w):  # "becauseif"처럼 붙여 쓴 것도 원문에 있는 걸로 본다
        return any(x == w or x.startswith(w) or x.endswith(w) for x in o_words)
    new_clause = (len(new) - len(old) >= MIN_CLAUSE and added and
                  any(w.lower() in CLAUSE_CONJ and not conj_in_original(w.lower()) for w in new))
    if len(added) > MAX_ADDED or new_clause or \
            any(w in ("[", "(") for w in new) and not any(w in ("[", "(") for w in old):
        why.append("added_words")
    # 지우기: 첨삭 문장에서 아예 사라진 내용어가 MAX_DELETED개 넘음 (반복된 말 지우기, 어순 바꾸기는 통과)
    # (한글 단어가 영어로 옮겨져 사라진 것은 삭제로 치지 않는다)
    if len([w for w in _content(old) if not _HANGUL.match(w) and w not in c_words
            and not any(w in x or _close(w, x) for x in c_words if len(x) > 2)]) > MAX_DELETED:
        why.append("deleted_words")
    # 따옴표: 따로 떨어진 따옴표 토큰을 넣거나 빼거나 바꾸고, 나머지 단어는 (대소문자 빼고) 그대로
    q_old = [k for k in range(i1, i2) if k in oq]
    q_new = [k for k in range(j1, j2) if k in cq]
    if q_old or q_new:
        rest_old = [ow[k].lower() for k in range(i1, i2) if k not in oq]
        rest_new = [cw[k].lower() for k in range(j1, j2) if k not in cq]
        if rest_old == rest_new:
            why.append("quote")
    # 자기소개·반 이름 자리의 한글을 지우거나 바꿈 ("in 티카 AT" -> "in Class AT", "in 여울1M" -> "in Navy 1M",
    # "I'm 시연" -> "I'm Siyeon"). 다른 한글 단어(시위, 호날두 ...)는 영어로 바꿔도 된다 (2026-11-26 사용자 결정)
    if any(_HANGUL.match(ow[k]) and ow[k] not in new and _name_slot(ow, k) for k in range(i1, i2)):
        why.append("name")
    # 이름: 문장 중간의 대문자 단어 중 흔한 단어가 아닌 것을, 철자가 비슷하지 않은 말로 바꾸거나 지움
    # (괄호 안 과제 양식 "(Reason)", "[Job]"을 지우는 건 괜찮다)
    if not any(w in _TEMPLATE for w in old):
        for k in range(i1, i2):
            w = ow[k]
            if not w[:1].isupper() or w in ("I", "A") or k == 0 or sent[k - 1] != sent[k]:
                continue
            bare = w.lower().replace("’", "'")
            if bare.split("'")[0] in _COMMON or bare in _NO_APOS or any(ch.isdigit() for ch in w):
                continue  # 흔한 단어(It's, I'm 포함), 숫자 섞인 말(Agust7th)
            if any(_close(w, x) for x in new) or _close("".join(old), "".join(new)):
                continue
            why.append("name")
            break
    return why


def guard(original: str, corrected: str) -> tuple[str, list[RevertedEdit]]:
    """(안전한 첨삭 글, 되돌린 문장 목록)"""
    o, c = _tokens(original), _tokens(corrected)
    if not o or not c:
        return corrected, []
    ow, cw = [t for t, _ in o], [t for t, _ in c]
    sent = _sentence_ids(o, original)
    opcodes = SequenceMatcher(None, ow, cw, autojunk=False).get_opcodes()
    ops = [op for op in opcodes if op[0] != "equal"]

    # 수정 덩어리마다: 속한 문장(시작 위치 기준), 문제 종류
    delta: dict[int, int] = {}
    owner, op_why = [], []
    why_by_sent: dict[int, set] = {}
    oq, cq = set(_quote_tokens(o, original)), set(_quote_tokens(c, corrected))
    # 문장별 단어 집합: 원문은 문장 번호로, 첨삭은 같은 구간(equal)과 그 문장에 속한 수정 덩어리로
    o_words: dict[int, set] = {}
    for k, w in enumerate(ow):
        o_words.setdefault(sent[k], set()).add(w.lower())
    c_words: dict[int, set] = {}
    for op, i1, i2, j1, j2 in opcodes:
        if op == "equal":
            for k in range(i2 - i1):
                c_words.setdefault(sent[i1 + k], set()).add(cw[j1 + k].lower())
        else:
            c_words.setdefault(sent[min(i1, len(sent) - 1)], set()).update(w.lower() for w in cw[j1:j2])
    for _, i1, i2, j1, j2 in ops:
        s = sent[min(i1, len(sent) - 1)]
        owner.append(s)
        delta[s] = delta.get(s, 0) + _neg(cw[j1:j2]) - _neg(ow[i1:i2])
        why = _op_reasons(o, c, oq, cq, i1, i2, j1, j2, sent, o_words.get(s, set()), c_words.get(s, set()))
        op_why.append(why)
        if why:
            why_by_sent.setdefault(s, set()).update(why)
    for s, d in delta.items():
        if d != 0:
            why_by_sent.setdefault(s, set()).add("negation")
    bad_sent = {s for s, w in why_by_sent.items() if w & set(SENTENCE_RULES)}
    if not why_by_sent:
        return corrected, []

    def span(toks, text, i, j):
        """토큰 i..j-1이 차지하는 글자 (뒤따르는 공백 포함, 다음 토큰 직전까지)"""
        if i >= j:
            return ""
        end = toks[j][1] if j < len(toks) else len(text)
        return text[toks[i][1]:end]

    out = [corrected[:c[0][1]]]
    k = 0
    for op, i1, i2, j1, j2 in opcodes:
        new = span(c, corrected, j1, j2)
        if op == "equal":
            out.append(new)
            continue
        s, why = owner[k], op_why[k]
        k += 1
        touches = {sent[min(x, len(sent) - 1)] for x in range(i1, max(i2, i1 + 1))}
        if touches & bad_sent or why:
            old = span(o, original, i1, i2)
            if old and not old[-1].isspace() and new[-1:].isspace():
                old += new[len(new.rstrip()):]
            # 되돌린 자리 앞 띄어쓰기는 원문을 따른다: 단어가 붙거나("speechis") 기호 앞에 공백이 생기지 않게
            if 0 < i1 < len(o) and not old:
                # 끼워 넣기만 한 수정을 되돌림: 원문에서 다음 토큰 앞이 붙어 있으면 앞 공백도 지운다 ("homework ." 방지)
                if not original[o[i1][1] - 1:o[i1][1]].isspace():
                    prev = "".join(out)
                    if prev[-1:] == " ":
                        out[:] = [prev.rstrip(" ")]
            elif 0 < i1 < len(o):
                orig_space = original[o[i1][1] - 1:o[i1][1]].isspace()
                prev = "".join(out)
                if orig_space and prev and not prev[-1].isspace():
                    old = " " + old
                elif not orig_space and old and prev[-1:] == " " and prev.rstrip(" "):
                    out[:] = [prev.rstrip(" ")]  # 줄바꿈은 지우지 않는다
            out.append(old)
        else:
            out.append(new)

    # 선생님 확인용: 되돌린 문장의 원문과 모델이 고치려던 문장
    edits = []
    for s in sorted(why_by_sent):
        idx = [i for i, x in enumerate(sent) if x == s]
        orig_s = original[o[idx[0]][1]:o[idx[-1]][1] + len(o[idx[-1]][0])]
        js = []
        for op, i1, i2, j1, j2 in opcodes:
            if op == "equal":
                lo, hi = max(i1, idx[0]), min(i2, idx[-1] + 1)
                if lo < hi:
                    js += list(range(j1 + lo - i1, j1 + hi - i1))
            elif i1 <= idx[-1] and (i2 > idx[0] or (i1 == i2 and i1 >= idx[0])):
                js += list(range(j1, j2))
        model_s = corrected[c[min(js)][1]:c[max(js)][1] + len(c[max(js)][0])] if js else ""
        reason = ", ".join(r for r in ("negation", "added_words", "deleted_words", "quote", "name") if r in why_by_sent[s])
        edits.append(RevertedEdit(original=orig_s, corrected=model_s, reason=reason))
    return "".join(out), edits
