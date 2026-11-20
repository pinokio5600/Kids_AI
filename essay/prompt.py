"""/essay 에서 모델에게 보내는 지시문과 응답 형식.

첨삭 방식 (A): 틀린 것만 고친다. 맞게 쓴 부분은 아이가 쓴 단어·표현을 그대로 둔다.
점수·등급 계산과 HTML 생성은 서버가 한다 (모델은 JSON만 반환).
"""
from pydantic import BaseModel, Field

from essay.rubric import grader_persona, rubric_text


class ModelScores(BaseModel):
    grammar: int
    structure: int
    content: int


class ModelOutput(BaseModel):
    corrected: str = Field(description="The full essay with only the errors fixed.")
    scores: ModelScores
    comment: str = Field(description="Short overall comment for the student.")


CORRECTION_RULES = """How to correct (VERY IMPORTANT):
- Fix ONLY real errors: grammar, spelling, capitalization, punctuation, and missing or
  wrong small words (articles, prepositions, verb forms) that make a sentence incorrect.
- Do NOT rewrite or "improve" sentences that are already correct.
  Keep the student's own words, word choices, and ideas. Do not replace a correct word with a
  "better" one, and do not add new sentences or new information.
  Example: "I visited Guam in U.S.A." -> "I visited Guam in the U.S.A." (add only "the";
  do NOT change it to "Guam, America").
- NEVER replace names of people, places, schools, or classes (e.g., "Tom", "Navy 1M",
  "샘물3M", "Jeju"). You may only fix their capitalization and spacing
  (e.g., "navy1m" -> "Navy 1M"). Never insert the student's grade level into the essay.
- When a sentence is unclear, make the smallest change that makes it grammatical.
- Keep the same line breaks and paragraph order as the original.
- Return the WHOLE essay in "corrected", including sentences that needed no changes."""

COMMENT_RULES = """How to write the comment:
- 2 or 3 short sentences in simple English that this student can understand.
- Mention one thing the student did well and the most important thing to improve.
- The comment must match the scores (for example, if Structure is low, say what part is missing)."""


def build_messages(essay: str, topic: str | None, grade: int | None) -> list[dict]:
    system = "\n\n".join([
        grader_persona(grade),
        "Scoring rubric:\n" + rubric_text(),
        CORRECTION_RULES,
        COMMENT_RULES,
        "Return only JSON with: corrected, scores {grammar, structure, content}, comment.",
    ])
    topic_line = (
        f"Assignment topic: {topic}"
        if topic else
        "Assignment topic: (not given) - infer it from the essay and judge whether the essay stays on it."
    )
    user = f"{topic_line}\n\nStudent essay:\n{essay}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
