"""디베이트 영상: 다운로드, 음성 꺼내기, 화면 전환 지점 찾기."""
import re
import urllib.parse
import urllib.request
from pathlib import Path

import av
import numpy as np

SR = 16000


def download(url, folder):
    """Save the video under folder (data/debate/video/), keep it there, return the path.
    Already downloaded -> reuse."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    parts = urllib.parse.urlsplit(url)
    name = urllib.parse.unquote(Path(parts.path).name) or "video.mp4"
    name = re.sub(r"[^\w .()-]", "_", name)
    path = folder / name
    if path.exists():
        return path
    # The academy server gives paths with spaces: quote the path part only.
    safe = urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(urllib.parse.unquote(parts.path))))
    tmp = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(safe, timeout=60) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.chmod(0o600)
    tmp.rename(path)
    return path


def load_audio(path):
    """Mono 16 kHz float32. PyAV directly, because faster-whisper's decode_audio breaks on PyAV 16+."""
    chunks = []
    with av.open(str(path)) as c:
        rs = av.AudioResampler(format="fltp", layout="mono", rate=SR)
        for frame in c.decode(audio=0):
            for out in rs.resample(frame):
                chunks.append(out.to_ndarray()[0])
        for out in rs.resample(None):
            chunks.append(out.to_ndarray()[0])
    return np.concatenate(chunks).astype(np.float32)


def find_cuts(path, step=0.5, min_diff=6.0, rel=5.0):
    """Times where the picture changes at once (clips joined together).
    Debate videos are often one clip per speech, so a cut usually marks a new speaker.
    Compares small grey frames every `step` seconds; a cut is a jump far above the usual change."""
    with av.open(str(path)) as c:
        if not c.streams.video:
            return []
        v = c.streams.video[0]
        v.thread_type = "AUTO"
        prev, prev_t, diffs = None, None, []
        for frame in c.decode(video=0):
            t = float(frame.time)
            if prev_t is not None and t - prev_t < step:
                continue
            img = frame.to_ndarray(format="gray")[::8, ::8].astype(np.float32)
            if prev is not None:
                diffs.append((float(np.abs(img - prev).mean()), t))
            prev, prev_t = img, t
    if not diffs:
        return []
    limit = max(min_diff, rel * float(np.median([d for d, _ in diffs])))
    return [round(t, 2) for d, t in diffs if d >= limit]
