import json
import os
import secrets
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, model_validator

from core.llm import DEFAULT_MODEL, DEFAULT_THINK, NUM_CTX, OLLAMA_URL, ollama_chat
from core.grammar.check import GrammarResult, check_grammar
from programs.essay.grade import EssayResponse, grade_essay

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


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest):
    """메시지를 Ollama 모델에 보내고 답변을 반환"""
    payload = req.to_ollama(stream=False)
    return ChatResponse(model=payload["model"], reply=await ollama_chat(payload))


# ---------------------------------------------------------------- 문법 검사
class GrammarRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    model: str | None = None
    think: bool = True  # 영어 문법은 생각을 켜야 정확함 (테스트로 확인)


class GrammarResponse(GrammarResult):
    model: str


@app.post("/grammar", response_model=GrammarResponse, dependencies=[Depends(verify_api_key)])
async def grammar(req: GrammarRequest):
    """영어 문장의 문법을 고치고, 고친 부분과 이유를 반환"""
    model, result = await check_grammar(req.text, req.model, req.think)
    return GrammarResponse(model=model, **result.model_dump())


# ---------------------------------------------------------------- 채팅 스트리밍
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


@app.post("/essay", response_model=EssayResponse, dependencies=[Depends(verify_api_key)])
async def essay(req: EssayRequest):
    """에세이를 첨삭(틀린 것만 고침)하고 채점해서 아이용 HTML과 함께 반환"""
    return await grade_essay(req.essay, req.topic, req.level_name, req.model, req.think)
