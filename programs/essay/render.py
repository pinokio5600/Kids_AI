"""원문과 고친 글을 비교해서 아이들이 보는 첨삭 HTML을 만든다.

모델은 HTML을 직접 쓰지 않고, 서버가 여기서 항상 같은 규칙으로 만든다.
  - 지운 부분: 빨간 취소선
  - 추가·수정한 부분: 빨간 굵은 글씨
  - 선생님 메모: 초록 괄호
  - 끝부분: 총평 + 항목별 점수 + 등급
아이들 화면에서 CSS 파일 없이도 보이도록 인라인 style만 쓴다.
"""
import html
import re
from difflib import SequenceMatcher

STYLE_DEL = "color: rgb(255, 0, 0); text-decoration: line-through;"
STYLE_INS = "color: rgb(255, 0, 0); font-weight: bold;"
STYLE_NOTE = "color: rgb(0, 176, 80);"
STYLE_FEEDBACK = "margin-top: 16px; padding-top: 8px; border-top: 1px solid rgb(200, 200, 200);"

# 단어(축약형 포함), 숫자, 그 밖의 기호 하나씩 + 뒤따르는 공백
_TOKEN = re.compile(r"([A-Za-z0-9]+(?:['’][A-Za-z]+)*|[^\sA-Za-z0-9])(\s*)")


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    """(토큰, 뒤 공백, 시작 위치) 목록. 앞쪽 공백은 버린다."""
    return [(m.group(1), m.group(2), m.start()) for m in _TOKEN.finditer(text)]


def _norm(tok: str) -> str:
    return tok.replace("’", "'")


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _ws(space: str) -> str:
    """공백을 HTML로: 빈 줄은 문단 구분, 줄바꿈은 <br>"""
    if "\n" not in space:
        return " " if space else ""
    return "<br><br>" if space.count("\n") >= 2 else "<br>"


def _note_positions(corrected: str, notes: list[dict]) -> dict[int, list[str]]:
    """메모를 붙일 위치(고친 글 기준 문자 위치) -> 메모 목록"""
    pos: dict[int, list[str]] = {}
    for n in notes or []:
        anchor = (n.get("after") or n.get("quote") or "").strip()
        i = corrected.find(anchor) if anchor else -1
        at = i + len(anchor) if i >= 0 else len(corrected)
        pos.setdefault(at, []).append(n["text"])
    return pos


def render_body(original: str, corrected: str, notes: list[dict] | None = None) -> str:
    a = _tokenize(original.strip())
    b = _tokenize(corrected.strip())
    corrected = corrected.strip()
    note_at = _note_positions(corrected, notes or [])
    pending = sorted(note_at)

    out: list[str] = []

    def emit_notes(upto: int):
        while pending and pending[0] <= upto:
            for text in note_at.pop(pending.pop(0)):
                out.append(f' <span style="{STYLE_NOTE}">({_esc(text)})</span>')

    sm = SequenceMatcher(None, [_norm(t[0]) for t in a], [_norm(t[0]) for t in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("delete", "replace"):
            deleted = re.sub(r"\s+", " ", "".join(t + s for t, s, _ in a[i1:i2])).strip()
            is_word = deleted[:1].isalnum()
            last = next((piece for piece in reversed(out) if piece), "")
            if not is_word and last == " ":
                # 지운 게 쉼표 같은 기호면 앞 단어에 붙여서 보여준다: "water,̶ and"
                out[len(out) - 1 - out[::-1].index(" ")] = ""
                lead, trail = "", " "
            else:
                # 지운 단어는 앞뒤 단어와 띄어서 보여준다: "Today ~~i~~ I", "~~Becase~~ I"
                lead = " " if is_word and last and not last.endswith((" ", "<br>")) else ""
                trail = " " if op == "replace" or (is_word and j1 < len(b)) else ""
            out.append(f'{lead}<span style="{STYLE_DEL}">{_esc(deleted)}</span>{trail}')
        for k in range(j1, j2):
            tok, space, start = b[k]
            if op == "equal":
                out.append(_esc(tok))
                # 모델이 줄바꿈을 빼먹거나 빈 줄을 더 넣어도(지시 위반) 바뀌지 않은 단어 뒤에서는 원문 줄 모양을 지킨다
                orig_space = a[i1 + k - j1][1]
                if "\n" in orig_space or "\n" in space:
                    space = orig_space
            else:
                out.append(f'<span style="{STYLE_INS}">{_esc(tok)}</span>')
                # 고친 부분이 줄 끝에 걸쳐 있으면, 고친 마지막 단어 뒤에 원문 줄바꿈을 붙인다
                if k == j2 - 1 and i2 > i1 and "\n" in a[i2 - 1][1] and "\n" not in space:
                    space = a[i2 - 1][1]
            emit_notes(start + len(tok))
            out.append(_ws(space))
    emit_notes(len(corrected) + 1)
    body = "".join(out)
    # 같은 스타일 span이 연달아 있으면 합친다 (공백 포함)
    for style in (STYLE_INS, STYLE_DEL):
        prev = None
        while prev != body:
            prev = body
            body = re.sub(
                rf'(<span style="{re.escape(style)}">[^<]*)</span>(\s?)<span style="{re.escape(style)}">',
                r"\1\2", body)
    return body


def render_feedback(rubric: dict | None, grade: str | None,
                    suggestions: list[str] | None = None) -> str:
    parts = []
    if suggestions:
        parts.append(f"<p><b>Suggestions for Improvement</b>: {_esc(' '.join(suggestions))}</p>")
    if rubric:
        items = []
        for key, label, full in (("grammar", "Grammar", 5), ("structure", "Structure", 5),
                                 ("content", "Content", 10), ("total", "Total", 20)):
            if rubric.get(key) is not None:
                items.append(f"{label} {rubric[key]}/{full}")
        parts.append(f"<p>{' · '.join(items)}</p>")
    if grade:
        parts.append(f"<p><b>Grade: {_esc(grade)}</b></p>")
    if not parts:
        return ""
    return f'<div style="{STYLE_FEEDBACK}">{"".join(parts)}</div>'


def render(original: str, corrected: str, notes: list[dict] | None = None,
           rubric: dict | None = None, grade: str | None = None,
           suggestions: list[str] | None = None) -> str:
    return (f"<div>{render_body(original, corrected, notes)}</div>"
            f"{render_feedback(rubric, grade, suggestions)}")
