"""모델이 돌려준 '고친 부분 목록'을 원문에 적용해 첨삭된 글을 만든다.

모델이 글 전체를 다시 쓰면 답이 길어져 느리다 (답 쓰는 시간이 전체의 90%).
그래서 모델은 틀린 곳만 {"original": 원문 그대로, "corrected": 고친 것} 목록으로 주고,
서버가 원문에서 위치를 찾아 바꾼다.

위치 찾기:
  - 앞에서부터 순서대로 찾는다 (같은 표현이 여러 번 나와도 앞의 수정 다음부터 찾음)
  - 못 찾으면 글 처음부터 다시 찾는다 (모델이 순서를 틀린 경우)
  - 공백 차이는 무시하고, 단어 중간에 걸리는 위치는 쓰지 않는다 ("i" -> "it" 안의 i 방지)
  - 이미 고친 자리와 겹치거나 끝내 못 찾은 수정은 버린다 (원문은 그대로 둠)
"""
import re

from pydantic import BaseModel, Field


class Edit(BaseModel):
    original: str = Field(description="Exact words copied from the essay, including the error.")
    corrected: str = Field(description="The same words with the error fixed.")


def _pattern(original: str) -> re.Pattern | None:
    words = original.split()
    if not words:
        return None
    body = r"\s+".join(re.escape(w) for w in words)
    if words[0][0].isalnum():
        body = r"(?<![A-Za-z0-9])" + body
    if words[-1][-1].isalnum():
        body += r"(?![A-Za-z0-9])"
    return re.compile(body)


def apply_edits(text: str, edits: list[Edit]) -> tuple[str, int]:
    """(첨삭된 글, 적용 못 한 수정 수)"""
    spans: list[tuple[int, int, str]] = []  # 원문 위치 (시작, 끝, 바꿀 글)
    missed = 0
    cursor = 0

    def free(s: int, e: int) -> bool:
        return all(e <= a or s >= b for a, b, _ in spans)

    for ed in edits:
        if ed.original.strip() == ed.corrected.strip():
            continue
        pat = _pattern(ed.original)
        if pat is None:
            missed += 1
            continue
        found = None
        for start in (cursor, 0):
            for m in pat.finditer(text, start):
                if free(m.start(), m.end()):
                    found = m
                    break
            if found:
                break
        if not found:
            missed += 1
            continue
        spans.append((found.start(), found.end(), ed.corrected.strip()))
        cursor = found.end()

    out, pos = [], 0
    for s, e, rep in sorted(spans):
        out.append(text[pos:s])
        out.append(rep)
        pos = e
    out.append(text[pos:])
    return "".join(out), missed
