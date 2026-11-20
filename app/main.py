import json
import os
import secrets
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, ValidationError, model_validator

from essay.clean import strip_scaffolding
from essay.prompt import ModelOutput, build_messages
from essay.render import render
from essay.rubric import DEFAULT_GRADE, clamp, grade_for_level, letter_grade, total

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3.5:9b")
# 모델이 한 번에 읽을 수 있는 토큰 수 (Ollama 기본값 4096은 대화가 길어지면 부족)
NUM_CTX = int(os.getenv("NUM_CTX", "16384"))


def _parse_bool(value: str | None) -> bool | None:
    if value is None or value.strip() == "":
        return None
    v = value.strip().lower()
    if v in ("true", "1", "yes", "on"):
        return True
    if v in ("false", "0", "no", "off"):
        return False
    raise RuntimeError(f"DEFAULT_THINK 값이 잘못됐습니다: {value!r} (true 또는 false)")


# 요청에 think가 없을 때 쓸 기본값. 비워 두면 모델 기본 동작을 따른다
# (qwen3.5는 생각 켬, 생각 기능이 없는 모델은 그냥 답함).
DEFAULT_THINK = _parse_bool(os.getenv("DEFAULT_THINK"))

# 쉼표로 여러 개 등록 가능: API_KEYS=key1,key2
API_KEYS = [k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()]
if not API_KEYS:
    raise RuntimeError("API_KEYS가 .env에 설정되지 않았습니다. 키 없이 서버를 열 수 없습니다.")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(key: str | None = Security(api_key_header)) -> None:
    """X-API-Key 헤더가 등록된 키 중 하나와 일치하는지 확인"""
    if key is None or not any(secrets.compare_digest(key, k) for k in API_KEYS):
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키입니다.")


app = FastAPI(title="AI Server")


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """둘 중 하나 이상 필요:
    - message:  한 번만 묻는 질문 (기존 방식)
    - messages: 지금까지의 대화 기록. message도 함께 보내면 맨 뒤에 user로 붙는다.
    """
    message: str | None = None
    messages: list[Message] | None = None
    model: str | None = None
    # true: 답하기 전에 생각 (느리지만 계산·추론에 강함)
    # false: 바로 답함 (빠르지만 복잡한 문제는 틀리기 쉬움)
    think: bool | None = None

    @model_validator(mode="after")
    def check_input(self):
        if not self.message and not self.messages:
            raise ValueError("message 또는 messages 중 하나는 필요합니다.")
        return self

    def to_ollama(self, stream: bool) -> dict:
        msgs = [m.model_dump() for m in self.messages or []]
        if self.message:
            msgs.append({"role": "user", "content": self.message})
        payload = {
            "model": self.model or DEFAULT_MODEL,
            "messages": msgs,
            "stream": stream,
            "options": {"num_ctx": NUM_CTX},
        }
        think = self.think if self.think is not None else DEFAULT_THINK
        if think is not None:
            payload["think"] = think
        return payload


class ChatResponse(BaseModel):
    model: str
    reply: str


@app.get("/health")
async def health():
    """서버와 Ollama 연결 상태 확인"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
        return {"status": "ok", "ollama": "connected", "models": models}
    except httpx.HTTPError as e:
        return {"status": "degraded", "ollama": f"unreachable: {e}"}


async def ollama_chat(payload: dict, timeout: float = 300) -> str:
    """Ollama에 스트리밍 없이 요청하고 답변 본문을 반환"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Ollama 연결 실패: {e}")
    return r.json()["message"]["content"]


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest):
    """메시지를 Ollama 모델에 보내고 답변을 반환"""
    payload = req.to_ollama(stream=False)
    return ChatResponse(model=payload["model"], reply=await ollama_chat(payload))


GRAMMAR_PROMPT = """You are an English proofreader.
Fix grammar, spelling, and punctuation errors in the user's text.
Rules:
- Keep the original meaning, tone, and style. Do not rewrite or rephrase correct parts.
- Change only what is actually wrong.
- If there are no errors, return the text unchanged with an empty changes list.
- For each change, write the "reason" in Korean, briefly."""


class GrammarRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    model: str | None = None
    think: bool = True  # 영어 문법은 생각을 켜야 정확함 (테스트로 확인)


class GrammarChange(BaseModel):
    original: str
    corrected: str
    reason: str


class GrammarResult(BaseModel):
    corrected: str
    changes: list[GrammarChange]


class GrammarResponse(GrammarResult):
    model: str


@app.post("/grammar", response_model=GrammarResponse, dependencies=[Depends(verify_api_key)])
async def grammar(req: GrammarRequest):
    """영어 문장의 문법을 고치고, 고친 부분과 이유를 반환"""
    model = req.model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": GRAMMAR_PROMPT},
            {"role": "user", "content": req.text},
        ],
        "stream": False,
        "think": req.think,
        # 답변을 이 JSON 형태로만 내도록 강제
        "format": GrammarResult.model_json_schema(),
        "options": {"num_ctx": NUM_CTX, "temperature": 0},
    }
    content = await ollama_chat(payload)
    try:
        result = GrammarResult.model_validate_json(content)
    except ValidationError:
        raise HTTPException(status_code=502, detail=f"모델 응답 형식이 잘못됐습니다: {content[:500]}")
    return GrammarResponse(model=model, **result.model_dump())


def sse(event: str, data: dict) -> str:
    """SSE 형식의 이벤트 한 개를 만든다"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(req: ChatRequest):
    """답변을 만들어지는 대로 SSE로 전송

    이벤트 종류:
      thinking - 모델이 답하기 전 생각하는 과정 (조각 단위)
      content  - 실제 답변 (조각 단위)
      done     - 완료, 소요 시간 등 통계
      error    - 스트리밍 도중 발생한 오류
    """
    payload = req.to_ollama(stream=True)
    model = payload["model"]

    # 스트리밍을 시작하기 전에 Ollama 응답 상태를 먼저 확인해서,
    # 모델 없음 같은 오류는 일반 HTTP 오류로 돌려준다.
    client = httpx.AsyncClient(timeout=httpx.Timeout(300, connect=5))
    try:
        r = await client.send(
            client.build_request("POST", f"{OLLAMA_URL}/api/chat", json=payload),
            stream=True,
        )
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"Ollama 연결 실패: {e}")

    if r.is_error:
        body = (await r.aread()).decode(errors="replace")
        await r.aclose()
        await client.aclose()
        raise HTTPException(status_code=r.status_code, detail=body)

    async def events():
        try:
            async for line in r.aiter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    yield sse("error", {"detail": chunk["error"]})
                    return
                msg = chunk.get("message", {})
                if msg.get("thinking"):
                    yield sse("thinking", {"text": msg["thinking"]})
                if msg.get("content"):
                    yield sse("content", {"text": msg["content"]})
                if chunk.get("done"):
                    yield sse("done", {
                        "model": model,
                        "done_reason": chunk.get("done_reason"),
                        "total_seconds": round(chunk.get("total_duration", 0) / 1e9, 2),
                        "eval_count": chunk.get("eval_count"),
                    })
        except httpx.HTTPError as e:
            yield sse("error", {"detail": f"스트리밍 중 연결 끊김: {e}"})
        finally:
            await r.aclose()
            await client.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- 에세이 첨삭·채점
class EssayRequest(BaseModel):
    essay: str = Field(min_length=1, max_length=8000)
    topic: str | None = None        # 과제 주제 (없으면 모델이 글에서 추론)
    level_name: str | None = None   # DB levelName 그대로 (예: PurpleG, 샘물)
    model: str | None = None
    think: bool = True              # 영어 문법 교정은 생각을 켜야 정확함


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


@app.post("/essay", response_model=EssayResponse, dependencies=[Depends(verify_api_key)])
async def essay(req: EssayRequest):
    """에세이를 첨삭(틀린 것만 고침)하고 채점해서 아이용 HTML과 함께 반환"""
    text = strip_scaffolding(req.essay)
    if not text:
        raise HTTPException(status_code=422, detail="과제 양식을 빼고 나니 에세이 내용이 없습니다.")
    us_grade = grade_for_level(req.level_name) or DEFAULT_GRADE
    model = req.model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": build_messages(text, req.topic, us_grade),
        "stream": False,
        "think": req.think,
        "format": ModelOutput.model_json_schema(),
        "options": {"num_ctx": NUM_CTX, "temperature": 0},
    }
    content = await ollama_chat(payload, timeout=600)
    try:
        out = ModelOutput.model_validate_json(content)
    except ValidationError:
        raise HTTPException(status_code=502, detail=f"모델 응답 형식이 잘못됐습니다: {content[:500]}")

    scores = clamp(out.scores.model_dump())
    total_score = total(scores)
    grade = letter_grade(total_score)
    corrected = out.corrected.strip()
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
