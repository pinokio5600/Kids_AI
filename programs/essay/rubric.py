"""에세이 채점 기준과 채점자 설정.

기준을 바꿀 때는 이 파일만 고치면 프롬프트와 점수 검증에 함께 반영된다.
  - 채점자: 미국의 영어 작문 선생님
  - 학생 수준: 레벨(LevelName)에 맞는 미국 초등학교 학년 기준으로 기대치를 잡는다
  - Grammar /5 + Structure /5 + Content /10 = Total /20
  - Grammar는 서버가 첨삭 결과(고친 곳 수)로 계산한다. 모델이 직접 매긴 문법 점수는
    고친 양과 따로 놀았다 (같은 4점인데 100단어당 1개~28개). 같은 첨삭이면 항상 같은 점수.
  - Structure, Content는 모델이 아래 기준표로 매긴다.
"""
import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    max_score: int
    levels: tuple[tuple[str, str], ...]  # (점수 또는 범위, 설명)
    by_model: bool = True                # False면 서버가 계산 (모델에게 묻지 않음)


# ---- 레벨(DB의 levelName 값 그대로) -> 미국 초등학교 학년
# 에세이는 Purple부터 시작 (그 아래 레벨은 에세이 없음)
LEVEL_GRADE: dict[str, int] = {
    "PurpleG": 2,
    "Navy": 2,
    "샘물": 3,
    "여울": 3,
    "가람": 3,
    "바다": 3,
    "미리내": 4,
    "별마루": 4,
    "pre폴라": 5,
    "유마": 5,
    "레오": 5,
    "파보": 5,
    "폴라": 5,
    "홉스": 6,
    "티카": 6,
    "빅키": 6,
    "바이칼": 6,
    "안나": 7,
    "낭가": 7,
    "로체": 7,
    "캉첸": 7,
}
# 레벨을 모르거나 안 보냈을 때. 가장 낮은 에세이 레벨 기준으로 채점한다.
DEFAULT_GRADE = 2


def grade_for_level(level_name: str | None) -> int | None:
    """DB levelName -> 학년. 표에 없는 레벨이면 None.

    Purple로 시작하는 레벨은 모두 같은 Purple(2학년)로 본다.
    pre로 시작하는 예비반(pre파보, pre레오, pre유마 ...)은 원래 반과 같은 학년으로 본다.
    """
    if not level_name:
        return None
    name = level_name.strip()
    if name in LEVEL_GRADE:
        return LEVEL_GRADE[name]
    if name.startswith("Purple"):
        return 2
    if name.lower().startswith("pre") and name[3:].strip() in LEVEL_GRADE:
        return LEVEL_GRADE[name[3:].strip()]
    return None


# 학년별 기대치 (미국 Common Core 작문·문법 기준 W.x.1 / L.x.1-2 요약)
GRADE_EXPECTATIONS: dict[int, str] = {
    2: """- Introduces the topic, gives reasons, and ends with a concluding sentence.
- Uses simple linking words (because, and, also).
- Writes complete simple sentences; uses capital letters for names and sentence beginnings,
  end punctuation, and correct spelling of common words.
- Short, simple sentences are fine. Do not expect advanced vocabulary.""",
    3: """- Introduces the topic, states an opinion, gives several reasons, and provides a concluding statement.
- Uses linking words and phrases (because, therefore, since, for example).
- Uses correct verb tenses and subject-verb agreement; uses commas and quotation marks in simple cases.
- Writes simple and compound sentences; may group related ideas into paragraphs.""",
    4: """- Introduces the topic clearly, organizes reasons logically, and supports them with facts and details.
- Uses linking phrases (for instance, in order to, in addition) and a clear concluding section.
- Writes complete sentences and avoids run-ons and fragments; uses commas, quotation marks,
  and capitalization correctly; uses relative pronouns (who, which, that) correctly.
- Uses paragraphs to separate introduction, body, and conclusion.""",
    5: """- Introduces the topic clearly with a clear position, and organizes reasons in a logical order
  that supports the writer's purpose.
- Supports each reason with facts and details; uses linking words such as consequently,
  specifically, and in contrast; ends with a concluding section related to the opinion.
- Uses verb tenses consistently (avoids unnecessary tense shifts), including perfect tenses;
  uses commas after introductory elements and in a series; spells grade-level words correctly.
- Writes varied sentences (simple, compound, complex) without run-ons or fragments.""",
    6: """- Introduces a clear claim and organizes reasons and evidence clearly.
- Supports the claim with clear reasons and relevant evidence (facts, examples, sources).
- Uses words, phrases, and clauses to show how claims and reasons connect;
  keeps a formal style; ends with a concluding statement that follows from the argument.
- Uses pronouns correctly (no vague pronouns); uses commas, parentheses, or dashes for
  extra information; varies sentence patterns; spells correctly.""",
    7: """- Introduces a claim, acknowledges opposing claims, and organizes reasons and evidence logically.
- Supports the claim with logical reasoning and relevant, accurate evidence; responds to
  the other side when rebutting.
- Uses words, phrases, and clauses that create cohesion; keeps a formal style;
  ends with a concluding section that supports the argument.
- Avoids misplaced and dangling modifiers; uses simple, compound, complex, and
  compound-complex sentences correctly; punctuates and spells correctly.""",
}


def grader_persona(grade: int | None) -> str:
    g = grade if grade in GRADE_EXPECTATIONS else DEFAULT_GRADE
    ordinal = {2: "2nd", 3: "3rd"}.get(g, f"{g}th")
    school = "elementary school" if g <= 5 else "middle school"
    return f"""You are an experienced English writing teacher in the United States.
You are grading essays and speeches written by young English learners.
Judge this essay by what is expected of a U.S. {ordinal}-grade {school} student.
Expectations for {ordinal} grade:
{GRADE_EXPECTATIONS[g]}
Score generously, like a warm and encouraging teacher of young learners:
- Do not demand more than this grade level. An essay that answers the topic with a clear
  beginning, middle, and end deserves full or nearly full marks, even if it is simple.
- When you are between two scores, choose the higher one.
- Take points off only for real problems: a missing part, going off topic, or very little content."""

RUBRIC: tuple[Criterion, ...] = (
    Criterion(
        key="grammar",
        label="Grammar",
        max_score=5,
        by_model=False,  # grammar_score()로 계산. 아래 설명은 기준 문서용
        levels=(
            ("5", "No major grammar problems. Only tiny slips, if any."),
            ("4", "A few minor mistakes that do not affect understanding."),
            ("3", "Repeated mistakes (e.g., verb tense, subject-verb agreement, articles)."),
            ("2", "Mistakes that sometimes make the meaning unclear."),
            ("1", "Mistakes make the writing hard to understand."),
        ),
    ),
    Criterion(
        key="structure",
        label="Structure",
        max_score=5,
        levels=(
            ("5", "Has an introduction, a body, and a conclusion (they can be short and simple)."),
            ("4", "All three parts are there, but one is very weak (e.g., a conclusion of only a few words)."),
            ("3", "One of the three parts is missing."),
            ("1-2", "No clear introduction/body/conclusion."),
        ),
    ),
    Criterion(
        key="content",
        label="Content",
        max_score=10,
        levels=(
            ("10", "Answers the topic and supports it with reasons or examples. Simple ideas are fine."),
            ("9", "Answers the topic, but one reason or example is thin."),
            ("8", "On topic, but the support is short or repeated."),
            ("7", "On topic, but very little support (only one or two sentences of ideas)."),
            ("5-6", "Some parts drift away from the topic or the ideas do not fit together."),
            ("1-4", "Mostly unrelated to the topic."),
        ),
    ),
)

MAX_TOTAL = sum(c.max_score for c in RUBRIC)  # 20


MODEL_CRITERIA = tuple(c for c in RUBRIC if c.by_model)


def rubric_text() -> str:
    """모델에게 보여 줄 기준표 (모델이 매기는 항목만)"""
    lines = []
    for c in MODEL_CRITERIA:
        lines.append(f"{c.label} (0-{c.max_score}):")
        lines += [f"  {score}: {desc}" for score, desc in c.levels]
    return "\n".join(lines)


def total(scores: dict[str, int]) -> int:
    return sum(scores[c.key] for c in RUBRIC)


def clamp(scores: dict[str, int]) -> dict[str, int]:
    """모델이 만점을 넘거나 음수를 주는 경우를 막는다"""
    return {c.key: max(0, min(c.max_score, int(scores.get(c.key, 0)))) for c in RUBRIC}


# ---- Grammar: 100단어당 실수 수 -> 점수
# 실수 1개 = 첨삭에서 이어서 바뀐 한 덩어리. 대소문자만 / 문장부호만 고친 것은 0.5개로 센다.
# 고학년(6~7학년) 선생님 점수 150편과 비교해 맞춤: 평균 선생님 4.19 / 계산 4.35, 1점 이내 93%
GRAMMAR_CUTOFFS: tuple[tuple[float, int], ...] = (
    (5, 5),    # 100단어당 5개 미만
    (9, 4),    # 9개 미만
    (14, 3),   # 14개 미만
    (20, 2),   # 20개 미만
)
GRAMMAR_FLOOR = 1  # 20개 이상

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*|[^\sA-Za-z0-9]")
_WORD = re.compile(r"[A-Za-z]+")


def count_errors(original: str, corrected: str) -> tuple[int, int]:
    """첨삭 전후를 비교해 (큰 실수 수, 작은 실수 수)를 센다. 작은 실수 = 대소문자·문장부호만 고친 것"""
    o = [t.replace("’", "'") for t in _TOKEN.findall(original)]
    n = [t.replace("’", "'") for t in _TOKEN.findall(corrected)]
    major = minor = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        a, b = o[i1:i2], n[j1:j2]
        if [x.lower() for x in a] == [x.lower() for x in b] or all(not x[0].isalnum() for x in a + b):
            minor += 1
        else:
            major += 1
    return major, minor


def grammar_score(original: str, corrected: str) -> int:
    words = max(1, len(_WORD.findall(original)))
    major, minor = count_errors(original, corrected)
    per100 = (major + minor / 2) / words * 100
    for limit, score in GRAMMAR_CUTOFFS:
        if per100 < limit:
            return score
    return GRAMMAR_FLOOR


# ---- 총점 -> 등급 (기준표 점수로 일관되게 매긴다)
# 넉넉한 채점 기준으로 돌려 보니 A 비율: 고학년 83% (선생님 82%), 저학년 85% (선생님 77%)
GRADE_CUTOFFS: tuple[tuple[int, str], ...] = (
    (17, "A"),  # 17~20 (85% 이상)
    (14, "B"),  # 14~16 (70% 이상)
    (0, "C"),   # 0~13
)


def letter_grade(total_score: int) -> str:
    for cutoff, letter in GRADE_CUTOFFS:
        if total_score >= cutoff:
            return letter
    return GRADE_CUTOFFS[-1][1]
