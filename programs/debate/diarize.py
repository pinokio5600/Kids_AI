"""화자 분리 (pyannote): 언제 누가 말했는지만 나눈다. 음성은 이 서버 GPU에서만 처리한다."""
import os

import numpy as np
import torch

MODEL = "pyannote/speaker-diarization-community-1"


def load_pipeline(device="cuda"):
    """First run downloads the model with HF_TOKEN (.env); later runs use ~/.cache/huggingface.
    Set HF_HUB_OFFLINE=1 to make sure nothing is fetched."""
    from dotenv import dotenv_values
    from pyannote.audio import Pipeline

    token = os.environ.get("HF_TOKEN") or dotenv_values(".env").get("HF_TOKEN")
    pipe = Pipeline.from_pretrained(MODEL, token=token)
    return pipe.to(torch.device(device))


def diarize(pipe, audio, sr=16000, min_speakers=None, max_speakers=None):
    """-> [(start, end, speaker_label), ...] sorted by time, no overlaps."""
    kw = {}
    if min_speakers:
        kw["min_speakers"] = min_speakers
    if max_speakers:
        kw["max_speakers"] = max_speakers
    out = pipe({"waveform": torch.from_numpy(np.asarray(audio, dtype=np.float32))[None], "sample_rate": sr}, **kw)
    # exclusive: one speaker at a time, easier to give each word one owner
    ann = getattr(out, "exclusive_speaker_diarization", None) or getattr(out, "speaker_diarization", out)
    return [(float(s.start), float(s.end), str(k)) for s, _, k in ann.itertracks(yield_label=True)]
