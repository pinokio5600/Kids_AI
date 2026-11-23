"""/essay 에서 모델에게 보내는 지시문과 응답 형식.

첨삭 방식 (A): 틀린 것만 고친다. 맞게 쓴 부분은 아이가 쓴 단어·표현을 그대로 둔다.
Grammar 점수·총점·등급 계산과 HTML 생성은 서버가 한다 (모델은 JSON만 반환).
"""
from pydantic import BaseModel, Field

from core.grammar.rules import FIX_RULES
from programs.essay.edits import Edit
from programs.essay.rubric import grader_persona, rubric_text


class ModelScores(BaseModel):
    # grammar는 서버가 고친 양으로 계산 (programs/essay/rubric.py grammar_score)
    structure: int
    content: int


class ModelOutput(BaseModel):
    # 글 전체 대신 고친 부분만 받는다 (답이 짧아져 빠름). 서버가 원문에 적용: programs/essay/edits.py
    edits: list[Edit] = Field(description="Every error fix, in the order they appear in the essay.")
    scores: ModelScores
    comment: str = Field(description="Short overall comment for the student.")


# 공통 교정 규칙(core/grammar/rules.py) + 에세이 전용 규칙
CORRECTION_RULES = f"""How to correct (VERY IMPORTANT):
{FIX_RULES}

How to report corrections in "edits" (do NOT rewrite the whole essay):
- One item per error, in the order the errors appear in the essay.
- "original": copy the words EXACTLY as the student wrote them (same spelling, capitalization,
  and punctuation), including the error and 1-3 words around it so the place is clear.
  Keep it inside one line of the essay.
- "corrected": the same words with only the error fixed.
  Example: {{"original": "I go to school yesterday", "corrected": "I went to school yesterday"}}
  Example: {{"original": "my friend and me played", "corrected": "My friend and I played"}}
- Do not list parts that are already correct. If there are no errors, return an empty list."""

COMMENT_RULES = """How to write the comment:
- 2 or 3 short sentences in simple English that this student can understand.
- Mention one thing the student did well and the most important thing to improve.
- The comment must match the scores (for example, if Structure is low, say what part is missing).
- Grammar is scored from the number of corrections you made. If you made many corrections,
  name the most common kind of mistake; if you made almost none, you may praise the grammar."""


def build_messages(essay: str, topic: str | None, grade: int | None) -> list[dict]:
    system = "\n\n".join([
        grader_persona(grade),
        "Scoring rubric:\n" + rubric_text(),
        CORRECTION_RULES,
        COMMENT_RULES,
        "Return only JSON with: edits, scores {structure, content}, comment.",
    ])
    topic_line = (
        f"Assignment topic: {topic}"
        if topic else
        "Assignment topic: (not given) - infer it from the essay and judge whether the essay stays on it."
    )
    user = f"{topic_line}\n\nStudent essay:\n{essay}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
