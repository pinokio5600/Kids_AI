"""선생님 첨삭 HTML을 통일된 구조로 변환.

선생님마다 표시 방식이 달라서 (500건 분석 결과) 아래처럼 해석한다.
  - 빨강/파랑 계열 글씨            -> ins  (추가·수정)
  - <s>, <strike>, line-through    -> del  (삭제)
  - 초록 글씨, 괄호로 감싼 빨간 글 -> note (선생님 메모)
  - 노란 형광펜, 밑줄              -> 문제 표시 (글자는 그대로 유지)
  - 회색/검정 등                   -> 일반 본문
본문이 끝난 뒤 남는 줄은 총평/점수 영역으로 본다.
원문은 HTML에서 복원하지 않고 DB의 essay 필드를 그대로 쓴다
(선생님이 대문자 등을 취소선 없이 색만 바꾸는 경우가 있어서).
"""
import html
import re
from difflib import SequenceMatcher
from html.parser import HTMLParser

from programs.essay.clean import strip_scaffolding

BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}
DEL_TAGS = {"s", "strike", "del"}
NAMED = {
    "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0),
    "black": (0, 0, 0), "white": (255, 255, 255), "gray": (128, 128, 128),
    "grey": (128, 128, 128), "yellow": (255, 255, 0),
}


def parse_color(value: str) -> tuple[int, int, int] | None:
    v = value.strip().lower().replace("!important", "").strip()
    if v in NAMED:
        return NAMED[v]
    m = re.fullmatch(r"#([0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = re.fullmatch(r"#([0-9a-f]{3})", v)
    if m:
        return tuple(int(c * 2, 16) for c in m.group(1))
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+).*\)", v)
    if m:
        return tuple(int(x) for x in m.groups())
    return None


def color_kind(rgb: tuple[int, int, int] | None) -> str | None:
    """글자색 -> ins / note / None(일반 본문)"""
    if rgb is None:
        return None
    r, g, b = rgb
    if max(rgb) - min(rgb) < 40:          # 회색·검정·흰색 계열
        return None
    if g > r and g > b:                   # 초록 계열 = 메모
        return "note"
    return "ins"                          # 빨강·파랑·분홍 계열 = 수정


def parse_style(style: str) -> dict[str, str]:
    out = {}
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip().lower()
    return out


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[list[list]] = [[]]   # 줄 -> [kind, text, highlight]
        self.stack: list[dict] = []

    def _newline(self):
        if self.lines[-1]:
            self.lines.append([])

    def _state(self):
        kind, hl = "eq", False
        for st in self.stack:
            if st.get("del"):
                kind = "del"
            elif st.get("color") and kind != "del":
                kind = st["color"]
            if st.get("hl"):
                hl = True
        return kind, hl

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self._newline()
            return
        if tag in BLOCK_TAGS:
            self._newline()
        a = dict(attrs)
        st = {}
        style = parse_style(a.get("style") or "")
        if tag in DEL_TAGS or "line-through" in style.get("text-decoration", "") \
                or "line-through" in style.get("text-decoration-line", ""):
            st["del"] = True
        color = style.get("color") or a.get("color")
        if color:
            st["color"] = color_kind(parse_color(color))
        bg = parse_color(style.get("background-color") or style.get("background") or "")
        if tag == "u" or "underline" in style.get("text-decoration", "") \
                or "underline" in style.get("text-decoration-line", "") \
                or (bg is not None and bg != (255, 255, 255)):
            st["hl"] = True
        self.stack.append(st)

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._newline()

    def handle_endtag(self, tag):
        if tag == "br":
            return
        if self.stack:
            self.stack.pop()
        if tag in BLOCK_TAGS:
            self._newline()

    def handle_data(self, data):
        text = data.replace("\xa0", " ").replace("\r", "")
        if not text:
            return
        kind, hl = self._state()
        parts = text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                # HTML 소스 안의 줄바꿈은 공백 취급
                part = " " + part
            if part:
                line = self.lines[-1]
                if line and line[-1][0] == kind and line[-1][2] == hl:
                    line[-1][1] += part
                else:
                    line.append([kind, part, hl])


TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*|[^\sA-Za-z0-9]")


def tokens(text: str) -> list[str]:
    return [t.lower().replace("’", "'") for t in TOKEN_RE.findall(text)]


def _is_paren_note(text: str) -> bool:
    t = text.strip()
    return len(t) > 3 and t.startswith("(") and t.endswith(")") and " " in t or t in ("(?)",)


# 선생님 오타("Grammer", "Sture")도 잡도록 느슨하게
GRAMMAR_W = r"gram+[ae]r"
STRUCTURE_W = r"st\w{0,6}ure"
RUBRIC_PATTERNS = {
    "grammar": rf"\b{GRAMMAR_W}\W{{0,4}}(\d{{1,2}})\s*/\s*5\b",
    "structure": rf"\b{STRUCTURE_W}\W{{0,4}}(\d{{1,2}})\s*/\s*5\b",
    "content": r"\bcontent\W{0,4}(\d{1,2})\s*/\s*10\b",
    "total": r"(\d{1,2})\s*/\s*20\b",
}
FEEDBACK_NOISE = re.compile(
    rf"\b({GRAMMAR_W}|{STRUCTURE_W}|content|total grade|total|grade|score|topic)\b\s*[:(]?\s*(\d{{1,2}}\s*/\s*\d{{1,2}})?\)?"
    r"|\(?\d{1,2}\s*/\s*\d{1,2}\)?|\b[ABC][+-]?\b\s*$|suggestions for improvement\s*:?",
    re.I,
)
STOPWORDS = set("""a an the and or but if so to of in on at by for with from as is are was were be been
am i you he she it we they my your his her its our their me him us them this that these those
do does did not no yes can will would should could have has had there here what which who
how why when where all any some more most very too also just than then thank listening speech""".split())


def _content_words(text: str) -> list[str]:
    return [t for t in tokens(text) if t.isalpha() and t not in STOPWORDS and len(t) > 2]


def _alpha_join(text: str) -> str:
    return " ".join(t for t in tokens(text) if t.isalpha())


def _interlinear_pairs(body: list, essay: str) -> set[int]:
    """'원문 줄 / 바로 밑에 고친 줄' 방식으로 첨삭한 경우, 버릴 원문 줄 번호들.

    이 방식에서는 원문 줄의 빨간색이 '틀린 곳 표시'이고, 다음 줄이 고친 문장이다.
    두 쌍 이상 발견될 때만 이 방식으로 판단한다 (우연한 오탐 방지).
    """
    def raw(t: str) -> str:  # 대소문자·기호까지 그대로 비교 (sammul -> Sammul 같은 수정도 구분)
        return re.sub(r"\s+", " ", t.replace("’", "'")).strip()

    essay_alpha = {_alpha_join(l) for l in essay.splitlines() if l.strip()}
    essay_raw = {raw(l) for l in essay.splitlines() if l.strip()}
    texts = ["".join(s[1] for s in ln if s[0] != "note") for ln in body]
    full = [_alpha_join(t) for t in texts]
    drop = set()
    i = 0
    while i < len(full) - 1:
        a, b = full[i], full[i + 1]
        if a and a in essay_alpha and raw(texts[i + 1]) not in essay_raw \
                and raw(texts[i + 1]) != raw(texts[i]) \
                and SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio() >= 0.5:
            drop.add(i)
            i += 2
        else:
            i += 1
    return drop if len(drop) >= 2 else set()


def _looks_like_essay(line_text: str, essay_vocab: set[str], essay_alpha: str) -> bool:
    """줄의 핵심 단어 대부분이 원문에도 있으면 본문으로 본다 (선생님이 통째로 다시 쓴 줄 포함)"""
    if any(re.search(p, line_text, re.I) for p in RUBRIC_PATTERNS.values()):
        return False
    # "Thank you for listening to my speech!"처럼 원문에 그대로 있는 줄
    alpha = " ".join(t for t in tokens(line_text) if t.isalpha())
    if len(alpha.split()) >= 4 and alpha in essay_alpha:
        return True
    words = _content_words(line_text)
    if len(words) < 3:
        return False
    return sum(w in essay_vocab for w in words) / len(words) >= 0.6


def parse_teacher(row: dict) -> dict:
    """{id, date, eval, essay, correction} -> 통일된 구조"""
    raw_essay = row["essay"]
    # 과제 양식(Topic 줄, 〈Introduction〉, (이름), 빈칸 밑줄 등)은 아이 실수가 아니므로 먼저 걷어낸다
    row = {**row, "essay": strip_scaffolding(raw_essay)}
    p = _Parser()
    p.feed(row["correction"])
    lines = [ln for ln in p.lines if "".join(s[1] for s in ln).strip()]

    # 각 줄의 '원문 쪽' 토큰(eq+del)을 essay와 맞춰서 본문 범위를 찾는다
    essay_toks = tokens(row["essay"])
    line_of, orig_toks = [], []
    for li, ln in enumerate(lines):
        for kind, text, _ in ln:
            if kind in ("eq", "del"):
                t = tokens(text)
                orig_toks += t
                line_of += [li] * len(t)
    sm = SequenceMatcher(None, orig_toks, essay_toks, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size >= 2]
    matched = sum(b.size for b in blocks)
    if blocks:
        first_line = line_of[blocks[0].a]
        last_line = line_of[blocks[-1].a + blocks[-1].size - 1]
    else:
        first_line, last_line = 0, len(lines) - 1

    # 선생님이 끝부분을 통째로 다시 써서(대부분 빨간 글씨) 원래 글자가 거의 없으면
    # 위 정렬로는 본문 끝을 못 찾는다 -> 단어 겹침으로 본문 줄을 더 확장
    essay_vocab = set(_content_words(row["essay"]))
    essay_alpha = _alpha_join(row["essay"])
    line_texts = ["".join(s[1] for s in ln if s[0] != "note") for ln in lines]
    for li in range(last_line + 1, len(lines)):
        if _looks_like_essay(line_texts[li], essay_vocab, essay_alpha):
            last_line = li
    for li in range(first_line - 1, -1, -1):
        if _looks_like_essay(line_texts[li], essay_vocab, essay_alpha):
            first_line = li

    # 본문의 마지막 줄 뒤에 원문에 없는 내용이 같은 줄에 붙는 경우는 드물어서 줄 단위로 자른다
    body = lines[first_line:last_line + 1]
    header = lines[:first_line]
    tail = lines[last_line + 1:]

    corrected_lines, notes, highlights, n_ins, n_del = [], [], [], 0, 0
    drop = _interlinear_pairs(body, row["essay"])
    for li, ln in enumerate(body):
        if li in drop:
            # 원문 줄의 빨간색 = 틀린 곳 표시 -> 문제 위치 정보로만 보관
            highlights += [t.strip() for k, t, _ in ln if k == "ins" and t.strip()]
            continue
        out = ""
        for kind, text, hl in ln:
            if kind == "ins" and _is_paren_note(text):
                kind = "note"
            if kind == "note":
                notes.append({"after": out.strip()[-40:], "text": text.strip().strip("()").strip()})
                continue
            if kind == "del":
                n_del += bool(text.strip())
                continue
            if kind == "ins":
                n_ins += bool(text.strip())
            if hl and text.strip():
                highlights.append(text.strip())
            out += text
        corrected_lines.append(re.sub(r"[ \t]+", " ", out).strip())
    corrected = strip_scaffolding(re.sub(r"\n{3,}", "\n\n", "\n".join(corrected_lines)))

    tail_text = "\n".join(re.sub(r"\s+", " ", "".join(s[1] for s in ln)).strip() for ln in tail)
    rubric = {}
    for k, pat in RUBRIC_PATTERNS.items():
        m = re.search(pat, tail_text, re.I)
        if m:
            rubric[k] = int(m.group(1))
    if "total" not in rubric and {"grammar", "structure", "content"} <= rubric.keys():
        rubric["total"] = rubric["grammar"] + rubric["structure"] + rubric["content"]
    comment_lines = []
    for ln in tail_text.split("\n"):
        cleaned = FEEDBACK_NOISE.sub("", ln).strip(" :()-·|")
        if len(cleaned) >= 3 and re.search(r"[A-Za-z]{2}", cleaned):
            comment_lines.append(cleaned)
    comment = " ".join(comment_lines).strip()

    flags = ["interlinear"] if drop else []
    coverage = matched / max(1, len(essay_toks))
    if coverage < 0.6:
        flags.append("low_alignment")
    # 표시 없는(=선생님이 안 고친) 본문 글자가 원문에 없다면, essay와 correction이 서로 다른 글
    eq_toks = [t for ln in body for kind, text, _ in ln if kind == "eq" for t in tokens(text)]
    if eq_toks and not drop:
        sm_eq = SequenceMatcher(None, eq_toks, essay_toks, autojunk=False)
        unmatched = 1 - sum(b.size for b in sm_eq.get_matching_blocks()) / len(eq_toks)
        if unmatched > 0.3:
            flags.append("essay_mismatch")
    if re.search(r"\?(?=[A-Za-z])", tail_text + corrected) and not re.search(r"\?(?=[A-Za-z])", row["essay"]):
        flags.append("question_mark_artifact")
    if n_ins + n_del == 0 and SequenceMatcher(None, essay_toks, tokens(corrected), autojunk=False).ratio() > 0.98:
        flags.append("no_corrections")

    return {
        "id": row["id"],
        "homework_id": row.get("homeworkIdx"),
        "topic": row.get("topic"),
        "level": row.get("levelName"),
        "date": row.get("date"),
        "grade": row.get("eval"),
        "essay": row["essay"],          # 양식 정리 후 원문 (채점·비교 기준)
        "essay_raw": raw_essay.strip(),  # 아이가 제출한 그대로
        "corrected": corrected,
        "notes": notes,
        "highlights": highlights,
        "rubric": rubric or None,
        "comment": comment or None,
        "header": "\n".join("".join(s[1] for s in ln).strip() for ln in header) or None,
        "stats": {"ins": n_ins, "del": n_del, "alignment": round(coverage, 3)},
        "flags": flags,
    }
