"""에세이 채점 기준과 채점자 설정.

기준을 바꿀 때는 이 파일만 고치면 프롬프트와 점수 검증에 함께 반영된다.
  - 채점자: 미국의 영어 작문 선생님
  - 학생 수준: 레벨(LevelName)에 맞는 미국 초등학교 학년 기준으로 기대치를 잡는다
  - Grammar /5 + Structure /5 + Content /10 = Total /20
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    max_score: int
    levels: tuple[tuple[str, str], ...]  # (점수 또는 범위, 설명)


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
    """
    if not level_name:
        return None
    name = level_name.strip()
    if name in LEVEL_GRADE:
        return LEVEL_GRADE[name]
    if name.startswith("Purple"):
        return 2
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
Score fairly against these expectations: do not demand more than this grade level,
but do not overlook mistakes this grade level should already handle."""

RUBRIC: tuple[Criterion, ...] = (
    Criterion(
        key="grammar",
        label="Grammar",
        max_score=5,
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
            ("5", "Clear introduction, body, and conclusion, all well organized."),
            ("4", "All three parts are present, but one part is weak."),
            ("3", "One of the three parts is missing."),
            ("1-2", "Little or no clear introduction/body/conclusion."),
        ),
    ),
    Criterion(
        key="content",
        label="Content",
        max_score=10,
        levels=(
            ("9-10", "Stays on the lesson topic throughout and includes all expected elements."),
            ("7-8", "On topic, but some expected elements are missing or thin."),
            ("5-6", "Some parts drift away from the topic or the ideas are not consistent."),
            ("1-4", "Mostly unrelated to the lesson topic."),
        ),
    ),
)

MAX_TOTAL = sum(c.max_score for c in RUBRIC)  # 20


def rubric_text() -> str:
    lines = []
    for c in RUBRIC:
        lines.append(f"{c.label} (0-{c.max_score}):")
        lines += [f"  {score}: {desc}" for score, desc in c.levels]
    lines.append(f"Total = sum of the above (0-{MAX_TOTAL}).")
    return "\n".join(lines)


def total(scores: dict[str, int]) -> int:
    return sum(scores[c.key] for c in RUBRIC)


def clamp(scores: dict[str, int]) -> dict[str, int]:
    """모델이 만점을 넘거나 음수를 주는 경우를 막는다"""
    return {c.key: max(0, min(c.max_score, int(scores.get(c.key, 0)))) for c in RUBRIC}


# ---- 총점 -> 등급 (임시 기준. 채점용 데이터로 선생님 등급 분포와 비교한 뒤 조정)
GRADE_CUTOFFS: tuple[tuple[int, str], ...] = (
    (17, "A"),  # 17~20
    (14, "B"),  # 14~16
    (0, "C"),   # 0~13
)


def letter_grade(total_score: int) -> str:
    for cutoff, letter in GRADE_CUTOFFS:
        if total_score >= cutoff:
            return letter
    return GRADE_CUTOFFS[-1][1]
