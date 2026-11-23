"""에세이 첨삭·채점: 모델 호출 -> 점수 보정 -> 아이용 HTML 생성."""
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from core.llm import DEFAULT_MODEL, NUM_CTX, ollama_chat
from programs.essay.clean import strip_scaffolding
from programs.essay.prompt import ModelOutput, build_messages
from programs.essay.render import render
from programs.essay.rubric import DEFAULT_GRADE, clamp, grade_for_level, grammar_score, letter_grade, total


class EssayScores(BaseModel):
    grammar: int
    structure: int
    content: int
    total: int


class EssayResponse(BaseModel):
    html: str                 # 아이들 화면에 그대로 보여줄 첨삭 HTML (인라인 style)
    corrected: str            # 고친 글 (텍스트)
    essay: str                # 양식 정리 후 원문 (비교 기준)
    scores: EssayScores
    grade: str                # A / B / C (총점으로 서버가 계산)
    comment: str
    us_grade: int             # 채점에 적용한 미국 학년
    model: str


async def grade_essay(essay: str, topic: str | None = None, level_name: str | None = None,
                      model: str | None = None, think: bool = False) -> EssayResponse:
    """에세이를 첨삭(틀린 것만 고침)하고 채점해서 아이용 HTML과 함께 반환"""
    text = strip_scaffolding(essay)
    if not text:
        raise HTTPException(status_code=422, detail="과제 양식을 빼고 나니 에세이 내용이 없습니다.")
    us_grade = grade_for_level(level_name) or DEFAULT_GRADE
    model = model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": build_messages(text, topic, us_grade),
        "stream": False,
        "think": think,
        "format": ModelOutput.model_json_schema(),
        # 같은 글이면 같은 결과가 나오도록 무작위성 제거
        "options": {"num_ctx": NUM_CTX, "temperature": 0, "seed": 0},
    }
    content = await ollama_chat(payload, timeout=600)
    try:
        out = ModelOutput.model_validate_json(content)
    except ValidationError:
        raise HTTPException(status_code=502, detail=f"모델 응답 형식이 잘못됐습니다: {content[:500]}")

    corrected = out.corrected.strip()
    # grammar는 모델이 고친 양으로 서버가 계산 (programs/essay/rubric.py grammar_score)
    scores = clamp({**out.scores.model_dump(), "grammar": grammar_score(text, corrected)})
    total_score = total(scores)
    grade = letter_grade(total_score)
    rubric = {**scores, "total": total_score}
    return EssayResponse(
        html=render(text, corrected, None, out.comment.strip(), rubric, grade),
        corrected=corrected,
        essay=text,
        scores=EssayScores(**rubric),
        grade=grade,
        comment=out.comment.strip(),
        us_grade=us_grade,
        model=model,
    )
