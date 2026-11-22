"""포트폴리오 영상 채점: 아이가 대본을 읽은 녹음을 대본과 비교해서 점수와 리포트를 만든다.

1. Transcribe without hints (what the child actually said).
2. Align transcript words to script words: match / missed / different / extra.
3. For every mismatch, ask the model how well the audio fits the script wording vs.
   the transcribed wording. If the script wording fits about as well, the model
   probably mis-heard and the child read it right.

사용법 (저장소 루트에서):
  .venv/Scripts/python -m programs.portfolio.cli "data/stt/audio/Hercules" \
      --script programs/portfolio/scripts/hercules.txt --out "data/stt/reports/Hercules"
"""
import argparse
import sys
from pathlib import Path

from core.stt.engine import collect_files, load_audio, load_model
from programs.portfolio.align import script_words
from programs.portfolio.check import Scorer
from programs.portfolio.grade import grade_recording
from programs.portfolio.report import report_md, write_summary

# 아이들 녹음·결과는 저장소 루트의 data/stt/ 아래에 둔다 (git 제외)
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "stt"


def main():
    p = argparse.ArgumentParser(description="Compare children's reading against a script")
    p.add_argument("input", help="Audio/video file or folder")
    p.add_argument("--script", required=True, help="Script text file")
    p.add_argument("--out", default=str(DATA_DIR / "reports"))
    p.add_argument("--model", default="large-v3")
    p.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--drop-p", type=float, default=0.3)
    p.add_argument("--pass-gap", type=float, default=-1.0,
                   help="Script wording within this log-prob of the transcript -> model mis-heard")
    p.add_argument("--max-pass-words", type=int, default=3,
                   help="Only differences up to this many words can be passed as mis-hearing")
    p.add_argument("--no-boost", action="store_true", help="Don't raise quiet stretches")
    p.add_argument("--names", default="",
                   help="Extra names to leave out of accuracy, comma separated (e.g. Altman,Dario)")
    args = p.parse_args()

    ref = script_words(Path(args.script).read_text(encoding="utf-8"),
                       [n.strip() for n in args.names.split(",") if n.strip()])
    files = collect_files(args.input)
    if not files:
        sys.exit(f"No audio/video files found in {args.input}")

    model = load_model(args.model, args.device)
    scorer = Scorer(model)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for f in files:
        result = grade_recording(model, scorer, ref, load_audio(f), args.no_boost, args.drop_p,
                                 args.pass_gap, args.max_pass_words)
        summary.append((f.stem, result["rate"], result["todo"], result["score"]))
        report = out_dir / f"{f.stem}.md"
        report.write_text(report_md(f.stem, ref, result), encoding="utf-8")
        print(f"-> {report}")

    write_summary(summary, out_dir)


if __name__ == "__main__":
    main()
