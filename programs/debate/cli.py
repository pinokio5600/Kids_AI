"""디베이트 영상 하나 -> 아이별 발언 기록 (.md, .json).

사용법 (저장소 루트에서, .venv-debate):
  .venv-debate/bin/python -m programs.debate.cli "data/debate/video/영상.mp4" --teams 6,5
  .venv-debate/bin/python -m programs.debate.cli "https://.../영상.mp4" --teams 4

화면에는 시간·번호·찬반만 찍고, 받아쓴 내용은 파일(data/ 아래)에만 쓴다.
"""
import argparse
import gc
import json
import sys
import time
from pathlib import Path

from programs.debate import media
from programs.debate.diarize import diarize, load_pipeline
from programs.debate.transcript import _ts, build, render_md, transcribe_words

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "debate"


def run(src, team_sizes=None, out_root=DATA_DIR / "outputs", use_cuts=True, device="cuda", log=print):
    path = media.download(src, DATA_DIR / "video") if src.startswith(("http://", "https://")) else Path(src)
    if not path.exists():
        raise FileNotFoundError(path)

    t0 = time.time()
    audio = media.load_audio(path)
    cuts = media.find_cuts(path) if use_cuts else []
    log(f"음성 {len(audio) / media.SR:.0f}초, 화면 전환 {len(cuts)}곳 ({time.time() - t0:.0f}초)")

    t0 = time.time()
    pipe = load_pipeline(device)
    total = sum(team_sizes) if team_sizes else None
    turns = diarize(pipe, audio, min_speakers=total, max_speakers=total)
    del pipe
    gc.collect()
    if device == "cuda":
        import torch
        torch.cuda.empty_cache()
    log(f"화자 분리 {len({k for *_, k in turns})}명 ({time.time() - t0:.0f}초)")

    t0 = time.time()
    from core.stt.engine import load_model
    model = load_model("large-v3", device)
    words = transcribe_words(model, audio)
    del model
    gc.collect()
    log(f"받아쓰기 {len(words)}단어 ({time.time() - t0:.0f}초)")

    result = build(words, turns, cuts, team_sizes)
    result.update(video=str(path), words=words, duration=round(len(audio) / media.SR, 1),
                  team_sizes=team_sizes,
                  cuts=cuts, turns=[[round(a, 2), round(b, 2), k] for a, b, k in turns])

    out = Path(out_root) / path.stem
    out.mkdir(parents=True, exist_ok=True)
    for p in (Path(out_root), out):
        p.chmod(0o700)
    files = {out / "transcript.json": json.dumps(result, ensure_ascii=False, indent=1),
             out / "transcript.md": render_md(result, path.stem)}
    for f, text in files.items():
        f.write_text(text, encoding="utf-8")
        f.chmod(0o600)
    return result, out


def summary(result):
    """Times, numbers, roles only - no transcript text."""
    lines = []
    for team in result["teams"]:
        lines.append(f"[{team['team']}팀]" if team["team"] else "[팀 밖]")
        for s in team["speakers"]:
            head = f"{s['no']:>2}번 {s['role']}" if team["team"] else f"   {s['label']}"
            lines.append(f"  {head}  {_ts(s['start']):>5} ~ {_ts(s['end']):>5}  {s['seconds']:5.0f}초  {s['words']:4d}단어  불확실 {s['unsure'] / max(s['words'], 1):5.1%}")
    if result["checks"]:
        lines.append("확인 필요:")
        lines += [f"  - {c}" for c in result["checks"]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Debate video -> per-speaker transcript")
    ap.add_argument("input", help="video file or URL")
    ap.add_argument("--teams", help="people per team in order, e.g. 6,5")
    ap.add_argument("--out", default=str(DATA_DIR / "outputs"))
    ap.add_argument("--no-cuts", action="store_true", help="don't use picture cuts")
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    args = ap.parse_args()
    sizes = [int(x) for x in args.teams.split(",")] if args.teams else None
    if sizes and any(n < 1 for n in sizes):
        sys.exit("--teams: 1 이상 숫자")
    result, out = run(args.input, sizes, args.out, not args.no_cuts, args.device)
    print(summary(result))
    print(f"저장: {out}/transcript.md, transcript.json")


if __name__ == "__main__":
    main()
