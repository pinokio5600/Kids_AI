"""STT 엔진: 음성 불러오기, 작은 소리 키우기, whisper 모델, 환각(지어낸 글) 걸러내기.

포트폴리오 채점·토론 등 음성을 다루는 프로그램이 모두 여기서 가져다 쓴다.
"""
import os
import sys
from dataclasses import replace
from pathlib import Path


def add_cuda_dlls():
    """Windows: make pip-installed cuBLAS/cuDNN DLLs visible to ctranslate2."""
    if sys.platform != "win32":
        return
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for bin_dir in nvidia_root.glob("*/bin"):
        os.add_dll_directory(str(bin_dir))
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]


add_cuda_dlls()

import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.audio import decode_audio  # noqa: E402

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".mov", ".aac"}
SR = 16000


def load_model(name="large-v3", device="cuda"):
    compute_type = "float16" if device == "cuda" else "int8"
    return WhisperModel(name, device=device, compute_type=compute_type)


def boost_quiet(audio, target_db=-20, max_gain_db=30, floor_db=-65, win=0.5):
    """Raise quiet stretches toward target_db, half a second at a time.
    Children often start softly; without this, silence filtering drops their first lines.
    Stretches below floor_db are treated as silence and left alone."""
    n = int(SR * win)
    db = np.array([20 * np.log10(np.sqrt(np.mean(audio[i:i + n] ** 2)) + 1e-9)
                   for i in range(0, len(audio), n)])
    # Average with neighbours so the gain doesn't jump in the middle of a word.
    db = np.convolve(np.pad(db, 2, mode="edge"), np.ones(5) / 5, mode="valid")
    gain_db = np.clip(target_db - db, 0, max_gain_db)
    gain_db[db < floor_db] = 0
    gain = np.repeat(10 ** (gain_db / 20), n)[: len(audio)]
    gain = np.convolve(gain, np.ones(n) / n, mode="same")
    return np.clip(audio * gain, -1, 1).astype(np.float32)


def load_audio(path):
    return decode_audio(str(path), SR)


LOOP_RATIO = 2.4  # faster-whisper's own threshold for "text repeats itself"


def undo_loops(model, segments, raw, **opts):
    """Boosting also raises background noise, which can make the model loop
    ("I couldn't do it, I couldn't do it, ..."). Redo those segments on the original audio."""
    for seg in segments:
        if seg.compression_ratio <= LOOP_RATIO:
            yield seg
            continue
        print(f"[{seg.start:6.2f}s -> {seg.end:6.2f}s] (repeating text, retrying on original audio)")
        # Cut the range out and keep silence filtering on: long pauses also cause loops.
        piece = raw[int(seg.start * SR): int(seg.end * SR)]
        redo, _ = model.transcribe(piece, vad_filter=True, **opts)
        for r in redo:
            if r.compression_ratio > LOOP_RATIO:
                # Still looping: the audio itself is unclear. Leave it out so a teacher checks it.
                print(f"[{r.start + seg.start:6.2f}s -> {r.end + seg.start:6.2f}s] (dropped, repeating) {r.text.strip()[:60]}")
                continue
            words = [replace(w, start=w.start + seg.start, end=w.end + seg.start)
                     for w in (r.words or [])]
            yield replace(r, start=r.start + seg.start, end=r.end + seg.start, words=words)


def is_hallucination(words, low_p, max_ratio=0.5):
    """Most words very unsure -> likely invented text (e.g. 'Thank you for your permission')."""
    if not words:
        return True
    unsure = sum(1 for w in words if w.probability < low_p)
    return unsure / len(words) > max_ratio


def collect_files(target):
    p = Path(target)
    if p.is_dir():
        return sorted(f for f in p.rglob("*") if f.suffix.lower() in AUDIO_EXTS)
    return [p]
