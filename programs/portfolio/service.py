"""API용 포트폴리오 채점: 모델은 처음 요청 때 한 번만 불러오고, 녹음은 한 번에 하나씩 채점한다.

whisper(faster-whisper)를 import하므로 app/main.py에서는 요청이 올 때 불러온다.
그래야 STT 라이브러리가 없는 서버에서도 다른 API는 뜬다.
"""
import os
import threading
from pathlib import Path

from core.stt.engine import AUDIO_EXTS, SR, load_audio, load_model  # noqa: F401 (AUDIO_EXTS: API에서 씀)
from programs.portfolio.align import script_words
from programs.portfolio.check import Scorer
from programs.portfolio.grade import grade_recording
from programs.portfolio.report import report_md

MODEL_NAME = os.getenv("STT_MODEL", "large-v3")
DEVICE = os.getenv("STT_DEVICE", "cuda")

# GPU 하나를 같이 쓰므로 모델 로딩·채점은 한 번에 하나만
_lock = threading.Lock()
_model = None
_scorer = None


def _get_model():
    global _model, _scorer
    if _model is None:
        _model = load_model(MODEL_NAME, DEVICE)
        _scorer = Scorer(_model)
    return _model, _scorer


def grade_file(path: Path, name: str, script: str, names=()):
    """녹음 파일 하나를 대본과 비교해 채점. 결과 dict (점수, 다른 곳 목록, 리포트 .md)."""
    ref = script_words(script, names)
    if not ref:
        raise ValueError("대본에 단어가 없습니다.")
    try:
        audio = load_audio(path)
    except Exception as e:  # 깨진 파일, 소리 트랙 없는 영상 등
        raise ValueError("녹음 파일을 읽지 못했습니다 (깨진 파일이거나 소리 트랙이 없음).") from e
    if len(audio) < SR:
        raise ValueError("녹음이 1초보다 짧습니다.")
    with _lock:
        model, scorer = _get_model()
        result = grade_recording(model, scorer, ref, audio)
    return {
        "model": MODEL_NAME,
        "duration_sec": round(len(audio) / SR, 1),
        "script_words": len(ref),
        **result,
        "report_md": report_md(name, ref, result),
    }
