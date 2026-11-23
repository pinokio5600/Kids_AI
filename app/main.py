import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Security, UploadFile
from fastapi.concurrency import run_in_threadpool
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
    # 채점용 데이터 평가 결과: 생각 켬은 편당 78초에 정확도 차이가 없고 응답 실패(2/30)까지 있어서 기본은 끔
    think: bool = False


@app.post("/essay", response_model=EssayResponse, dependencies=[Depends(verify_api_key)])
async def essay(req: EssayRequest):
    """에세이를 첨삭(틀린 것만 고침)하고 채점해서 아이용 HTML과 함께 반환"""
    return await grade_essay(req.essay, req.topic, req.level_name, req.model, req.think)


# ---------------------------------------------------------------- 포트폴리오 영상 채점
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "programs" / "portfolio" / "scripts"
MAX_UPLOAD_MB = int(os.getenv("PORTFOLIO_MAX_UPLOAD_MB", "300"))


class PortfolioCheck(BaseModel):
    start: float
    end: float
    ref_score: float
    hyp_score: float
    omit_score: float | None
    gap: float


class PortfolioRow(BaseModel):
    t: float          # 녹음에서 몇 초 지점
    kind: str         # 다르게 읽음 / 빠뜨림 / 추가로 말함 / 불분명/빠뜨림 / 대본 밖 발화
    script: str       # 대본 문구
    said: str         # 받아 적은 문구
    verdict: str      # 통과 (모델이 잘못 들음) / 확인 필요 / 참고
    check: PortfolioCheck | None


class PortfolioPoints(BaseModel):
    accuracy: float   # /60
    fluency: float    # /25
    clarity: float    # /15


class PortfolioScore(BaseModel):
    total: float
    grade: str
    points: PortfolioPoints
    accuracy: float   # 0~1, 이름 뺀 대본 단어 중 맞게 읽은 비율
    n_content: int
    n_names: int
    wpm: float
    pauses: int
    confidence: float


class PortfolioResponse(BaseModel):
    model: str
    duration_sec: float
    script_words: int
    score: PortfolioScore | None  # None: 목소리가 거의 안 들려 채점 불가
    rate: float                   # 대본 일치율(%)
    matched: int
    todo: int                     # 선생님 확인 필요 개수
    rows: list[PortfolioRow]
    transcript: str
    report_md: str


@app.get("/portfolio/scripts", dependencies=[Depends(verify_api_key)])
async def portfolio_scripts():
    """서버에 저장된 대본 이름 목록 (/portfolio의 script_name에 사용)"""
    return {"scripts": sorted(p.stem for p in SCRIPTS_DIR.glob("*.txt"))}


@app.post("/portfolio", response_model=PortfolioResponse, dependencies=[Depends(verify_api_key)])
async def portfolio(
    file: UploadFile = File(...),                # 녹음/영상 파일 (mp4, m4a, wav ...)
    script: str | None = Form(None),             # 대본 전문 (줄 = 대사 한 줄)
    script_name: str | None = Form(None),        # 또는 저장된 대본 이름 (예: hercules)
    names: str = Form(""),                       # 정확도에서 뺄 이름, 쉼표로 (예: Altman,Dario)
):
    """아이가 대본을 읽은 녹음을 채점: 점수(정확도 60/유창성 25/명확도 15), 다른 곳 목록, 리포트(.md)"""
    if bool(script) == bool(script_name):
        raise HTTPException(422, "script 또는 script_name 중 하나만 보내세요.")
    if script_name:
        available = {p.stem: p for p in SCRIPTS_DIR.glob("*.txt")}
        if script_name not in available:
            raise HTTPException(404, f"대본 '{script_name}'이 없습니다. 목록: {sorted(available)}")
        script = available[script_name].read_text(encoding="utf-8")

    try:
        from programs.portfolio import service  # whisper는 필요할 때만 불러온다
    except ImportError as e:
        raise HTTPException(503, f"이 서버에는 STT 라이브러리가 설치되어 있지 않습니다: {e}")

    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in service.AUDIO_EXTS:
        raise HTTPException(415, f"지원하지 않는 파일 형식입니다: {suffix or '(없음)'}")

    # 디코더가 파일 경로를 받으므로 임시 파일로 저장 (크기 제한 확인하며)
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        size = 0
        with tmp:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_MB << 20:
                    raise HTTPException(413, f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_MB}MB).")
                tmp.write(chunk)
        name_list = [n.strip() for n in names.split(",") if n.strip()]
        try:
            result = await run_in_threadpool(
                service.grade_file, Path(tmp.name), Path(filename).stem, script, name_list)
        except ValueError as e:  # 빈 대본, 깨진 파일, 너무 짧은 녹음
            raise HTTPException(400, str(e))
    finally:
        os.unlink(tmp.name)

    result["transcript"] = " ".join(w["text"] for w in result.pop("hyp"))
    return PortfolioResponse(**result)
