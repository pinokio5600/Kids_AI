"""Ollama 설정과 공통 호출 함수. 모든 기능(채팅·문법·에세이)이 여기서 모델을 부른다."""
import os

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen3.5:9b-mtp-q4_K_M")
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
