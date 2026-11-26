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
    suggestions: list[str] = Field(description="2-4 concrete suggestions for improvement, one sentence each.")


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

# GPT가 써 온 "Suggestions for Improvement" 100건을 보고 맞춘 형식 (한 문장에 10단어 안팎).
# 예시 문장을 넣었더니 모델이 글과 상관없이 그대로 베껴서 뺐다. 개수는 2~4개 (채우려고 지어내지 않게).
SUGGESTION_RULES = """How to write "suggestions" (Suggestions for Improvement):
- 2 to 4 items. Each item is ONE short sentence (about 8-15 words) that tells the student what to do.
  Write as many as THIS essay really needs: more for an essay with many problems, fewer for a
  strong one. Never invent an item just to fill the list.
- Each item covers a DIFFERENT area, chosen from what this essay actually needs:
  content (reasons, examples, staying on topic, repetition), organization (introduction, conclusion,
  transition words), grammar (name the main type of mistake you corrected), word choice or sentence variety.
- Base every item on real problems in THIS essay. Do not give generic advice the essay does not need.
- Talk about PATTERNS and skills, not single words. The student already sees each corrected word
  in red, so do NOT write items like "Change 'go' to 'went'" or "Spell 'because' correctly".
  At most ONE item may be about grammar or spelling, and it should name the type of mistake
  (e.g., "Pay attention to past tense verbs."). Write it ONLY if you actually corrected that type of
  mistake in this essay more than once; if you corrected almost nothing, write no grammar item.
- The suggestions must match the scores (for example, if Structure is low, say which part is
  missing or weak). Use simple words the student can understand. No praise.
- Never tell the student to add or fix something the essay already does well (e.g., do not ask for
  examples if each reason already has one, or for transition words if they are already used).
- If an area already has a full score, do not point out problems in it. For a strong essay, suggest
  a next step that would make it even better (e.g., answer a possible counterargument, explain
  an example in more depth, use more varied sentence structures or more precise words).
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


# ---- 개선 제안 전용 호출 (2026-11-26) ----
# 첨삭 호출(build_messages)은 그대로 두고 제안만 따로 만든다. 같은 호출에서 제안 지시를 바꾸면 첨삭까지
# 바뀌고 잡던 오류를 놓쳤다 (블라인드 비교 지금 38 : 새 17). 따로 만들면 고친 글을 보고 실제 실수를 짚어서
# 제안이 나아졌다 (블라인드 40편: 분리 18 : 기존 7, 비슷 15). 350편에 약 5분 더 걸린다.
# 영역 목록에 "transition words"를 예로 두면 모델이 거의 모든 글에 연결어 제안을 붙여서 뺐다.
SUGGESTION_ONLY_RULES = SUGGESTION_RULES.replace(
    "organization (introduction, conclusion,\n  transition words)", "organization (introduction, body, conclusion)")


class SuggestionOutput(BaseModel):
    suggestions: list[str] = Field(description="2-4 concrete suggestions for improvement, one sentence each.")


def build_suggestion_messages(essay: str, corrected: str, scores: dict, grade: int | None,
                              facts: str = "") -> list[dict]:
    """essay: 양식 정리한 원문, corrected: 안전장치를 거친 첨삭 글, scores: grammar/structure/content,
    facts: 프로그램이 확인한 '이 글이 이미 한 것' (suggest_guard.facts_text)"""
    system = "\n\n".join([
        grader_persona(grade),
        "Scoring rubric:\n" + rubric_text(),
        SUGGESTION_ONLY_RULES,
        'Return only JSON: {"suggestions": [...]}',
    ])
    user = (f"Student essay:\n{essay}\n\n"
            f"The same essay with only the errors fixed (the student sees these fixes in red):\n{corrected}\n\n"
            f"Scores given: Grammar {scores['grammar']}/5, Structure {scores['structure']}/5, "
            f"Content {scores['content']}/10.")
    if facts:
        user += f"\n\n{facts}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
