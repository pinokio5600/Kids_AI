"""영어 문장 문법 검사: 고친 문장 + 고친 부분별 이유(한국어)를 돌려준다."""
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from core.llm import DEFAULT_MODEL, NUM_CTX, ollama_chat

GRAMMAR_PROMPT = """You are an English proofreader.
Fix grammar, spelling, and punctuation errors in the user's text.
Rules:
- Keep the original meaning, tone, and style. Do not rewrite or rephrase correct parts.
- Change only what is actually wrong.
- If there are no errors, return the text unchanged with an empty changes list.
- For each change, write the "reason" in Korean, briefly."""


class GrammarChange(BaseModel):
    original: str
    corrected: str
    reason: str


class GrammarResult(BaseModel):
    corrected: str
    changes: list[GrammarChange]


async def check_grammar(text: str, model: str | None = None, think: bool = True) -> tuple[str, GrammarResult]:
    """문법을 고쳐서 (사용한 모델 이름, 결과)를 반환"""
    model = model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GRAMMAR_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "think": think,
        # 답변을 이 JSON 형태로만 내도록 강제
        "format": GrammarResult.model_json_schema(),
        "options": {"num_ctx": NUM_CTX, "temperature": 0},
    }
    content = await ollama_chat(payload)
    try:
        return model, GrammarResult.model_validate_json(content)
    except ValidationError:
        raise HTTPException(status_code=502, detail=f"모델 응답 형식이 잘못됐습니다: {content[:500]}")
