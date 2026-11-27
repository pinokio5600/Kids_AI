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
# 2026-11-27: 제안의 70%가 이미 빨간 글씨로 보이는 문법·철자를 되풀이해서, "다음 글을 더 잘 쓰는 법"(이유 설명,
# 예시, 반론, 구성, 표현) 중심으로 바꿨다. 그 글의 내용을 짚게 하고 문법은 같은 실수 3번 이상일 때 1개까지.
# 블라인드 40편: 아이에게 더 도움 새 31 : 기존 9, 맞는 제안 84% (기존 39%), 엉뚱함 9% (기존 10%).
# 아이 의견의 반대편을 설명하라거나 이유를 번호로 잘못 부르는 실수가 있어서 그 두 줄을 넣었다.
# 실존 인물·사건 예시를 요구하면 아이가 지어낼 수 있어서 상상한 상황·일상 예시로 바꿨다 (블라인드 40편: 새 14 : 기존 7, 비슷 19,
# 엉뚱함 22% -> 16%). '제안 종류를 다 다르게'와 '아이 경험 예시'는 시험해 보니 없는 문제를 지어내고 노벨상 같은
# 주제에서 겪을 수 없는 경험을 요구해서 넣지 않았다 (기존 20 : 새 16).
SUGGESTION_ONLY_RULES = """How to write "suggestions" (Suggestions for Improvement):
- The student already sees every corrected mistake in red. The suggestions are NOT for repeating those
  corrections. They tell the student how to make their NEXT essay better as a writer.
- 2 to 4 items. Each item is ONE short sentence (about 10-20 words) telling the student what to do.
- Most items should be about writing skills, chosen from what THIS essay needs most:
  ideas (explain WHY a reason is true, add an example, answer what someone on the other side might say,
  stay on topic, avoid repeating the same point),
  organization (a clear opening that states the opinion, one reason per paragraph, a closing sentence),
  expression (more exact or vivid words, joining short sentences, varying how sentences start).
- When you ask for an example, never ask for a real or famous person, a real discovery, a news event, or a fact
  the student would have to look up (a child may make one up). Instead ask for an example the student can
  write without research: an imagined situation ("imagine a scientist who ..."), an everyday situation, or,
  only when the topic is about the student's own life, something they experienced.
- Make each item specific to THIS essay: mention which reason, example or part of the essay you mean,
  using the student's own topic words (e.g., name the reason that needs more support). An item that could be
  pasted onto any essay is not allowed.
- Grammar: write AT MOST ONE grammar item, and only if the program's mistake list below shows one type
  3 or more times. Write it as a habit to practice (name the type), without quoting words.
  Otherwise write no grammar item at all.
- First decide what the student's opinion is. Every item must help the student support THAT opinion better;
  never ask them to explain or give examples for the opposite side.
- Refer to a reason by what it says (e.g., "your reason about money for research"), never by its number
  ("first", "second", "third"), because essays often number them differently.
- Never ask the student to explain or describe something the essay already explains, or to add something
  the essay already has (see the facts below).
- Match the scores: if Structure or Content is low, say which part is missing or weak. For a strong essay,
  suggest a next step (e.g., answer a counterargument, deepen one example).
- Use simple words a child can understand. No praise."""


class SuggestionOutput(BaseModel):
    suggestions: list[str] = Field(description="2-4 concrete suggestions for improvement, one sentence each.")


# 학년별 제안 (2026-11-27): 2학년과 6학년이 같은 길이(평균 14.5단어)·같은 종류의 제안을 받고 있었다.
# 아이들은 영어가 외국어인 초·중학생이라 낮은 레벨일수록 짧고 쉬운 기본기 제안만 준다. 제안은 영어 그대로.
def suggestion_band(grade: int | None) -> str:
    g = grade or 2
    return "low" if g <= 3 else "mid" if g <= 5 else "high"


MAX_SUGGESTIONS = {"low": 2, "mid": 3, "high": 4}

_LEVEL_RULES = {
    "low": """Grade-level rules (these override the number and length of items above):
- This student is a young beginner who is learning English as a foreign language (U.S. grade 2-3 level).
- Write only 1 or 2 items. Each item has at most 10 words.
- Use only very common, short words a beginner knows. Write a direct, simple instruction
  (e.g., start with "Add", "Write", "Tell", "Use"). Do not use words like "specifically", "describe", "explain why".
- Only basic skills: write full sentences, give a reason with "because", add one more sentence about a reason,
  give a simple example, end with a sentence that says your opinion again.
- Do not ask about the other side's opinion or about paragraphs.""",
    "mid": """Grade-level rules (these override the number and length of items above):
- This student is an elementary school student learning English as a foreign language (U.S. grade 4-5 level).
- Write 2 or 3 items. Each item has at most 15 words, with simple, common words.
- Focus on: explaining why each reason is true, adding an example, a clear opening and closing sentence,
  joining short sentences. Answering the other side only if the essay is already strong.""",
    "high": """Grade-level rules (these override the number and length of items above):
- This student is an older elementary or middle school student learning English as a foreign language
  (U.S. grade 6-7 level).
- Write 2 to 4 items. Each item has at most 20 words.
- You may include deeper skills: answering the other side, one reason per paragraph, more exact words,
  varied sentences.""",
}


def suggestion_level_rules(grade: int | None) -> str:
    return _LEVEL_RULES[suggestion_band(grade)]


def build_suggestion_messages(essay: str, corrected: str, scores: dict, grade: int | None,
                              facts: str = "", mistakes: str = "") -> list[dict]:
    """essay: 양식 정리한 원문, corrected: 안전장치를 거친 첨삭 글, scores: grammar/structure/content,
    facts: 프로그램이 확인한 '이 글이 이미 한 것' (suggest_guard.facts_text),
    mistakes: 프로그램이 센 '실제로 고친 실수 종류' (mistakes.mistakes_text, 2026-11-27)"""
    system = "\n\n".join([
        grader_persona(grade),
        "Scoring rubric:\n" + rubric_text(),
        SUGGESTION_ONLY_RULES,
        suggestion_level_rules(grade),
        'Return only JSON: {"suggestions": [...]}',
    ])
    user = (f"Student essay:\n{essay}\n\n"
            f"The same essay with only the errors fixed (the student sees these fixes in red):\n{corrected}\n\n"
            f"Scores given: Grammar {scores['grammar']}/5, Structure {scores['structure']}/5, "
            f"Content {scores['content']}/10.")
    if facts:
        user += f"\n\n{facts}"
    if mistakes:
        user += f"\n\n{mistakes}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
