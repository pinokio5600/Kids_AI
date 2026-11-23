"""/essay 에서 모델에게 보내는 지시문과 응답 형식.

첨삭 방식 (A): 틀린 것만 고친다. 맞게 쓴 부분은 아이가 쓴 단어·표현을 그대로 둔다.
Grammar 점수·총점·등급 계산과 HTML 생성은 서버가 한다 (모델은 JSON만 반환).
"""
from pydantic import BaseModel, Field

from core.grammar.rules import FIX_RULES
from programs.essay.rubric import grader_persona, rubric_text


class ModelScores(BaseModel):
    # grammar는 서버가 고친 양으로 계산 (programs/essay/rubric.py grammar_score)
    structure: int
    content: int


class ModelOutput(BaseModel):
    corrected: str = Field(description="The full essay with only the errors fixed.")
    scores: ModelScores
    suggestions: list[str] = Field(description="3-4 concrete suggestions for improvement, one sentence each.")


# 공통 교정 규칙(core/grammar/rules.py) + 에세이 전용 규칙
CORRECTION_RULES = f"""How to correct (VERY IMPORTANT):
{FIX_RULES}
- NEVER change the meaning. Do not add or remove "not", "no", "never", or other negative words,
  and do not change the student's opinion or argument, even if it seems illogical.
- If a sentence is incomplete, complete it only with the student's own nearby words or the
  smallest needed word (e.g., a missing verb). NEVER add a new idea, reason, or clause the
  student did not write.
- Keep the same line breaks and paragraph order as the original.
- Return the WHOLE essay in "corrected", including sentences that needed no changes."""

# GPT가 써 온 "Suggestions for Improvement" 100건을 보고 맞춘 형식 (3~5문장, 한 문장에 10단어 안팎)
SUGGESTION_RULES = """How to write "suggestions" (Suggestions for Improvement):
- 3 or 4 items. Each item is ONE short sentence (about 8-15 words) that tells the student what to do.
- Each item covers a DIFFERENT area, chosen from what this essay actually needs:
  content (reasons, examples, staying on topic, repetition), organization (introduction, conclusion,
  transition words), grammar (name the main type of mistake you corrected), word choice or sentence variety.
- Base every item on real problems in THIS essay. Do not give generic advice the essay does not need.
- Talk about PATTERNS and skills, not single words. The student already sees each corrected word
  in red, so do NOT write items like "Change 'go' to 'went'" or "Spell 'because' correctly".
  At most ONE item may be about grammar or spelling, and it should name the type of mistake
  (e.g., "Pay attention to past tense verbs.").
- The suggestions must match the scores (for example, if Structure is low, say which part is
  missing or weak). Use simple words the student can understand. No praise.
Example items:
  "Try to avoid repeating the same reason more than once."
  "Use transition words to link your ideas more smoothly."
  "Pay attention to subject-verb agreement and sentence clarity."
  "Make sure your concluding sentence matches your main argument."
"""


def build_messages(essay: str, topic: str | None, grade: int | None) -> list[dict]:
    system = "\n\n".join([
        grader_persona(grade),
        "Scoring rubric:\n" + rubric_text(),
        CORRECTION_RULES,
        SUGGESTION_RULES,
        "Return only JSON with: corrected, scores {structure, content}, suggestions.",
    ])
    topic_line = (
        f"Assignment topic: {topic}"
        if topic else
        "Assignment topic: (not given) - infer it from the essay and judge whether the essay stays on it."
    )
    user = f"{topic_line}\n\nStudent essay:\n{essay}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
