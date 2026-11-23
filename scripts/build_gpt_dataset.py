"""GPT 첨삭 내역(JSON)을 평가용 jsonl로 변환.

사용법:
  .venv/bin/python scripts/build_gpt_dataset.py data/essay/processed/gpt_correct_recent100.json
결과:
  data/essay/processed/<이름>_eval.jsonl   eval_essay.py run --data=<이름>_eval.jsonl 로 사용

GPT 첨삭 HTML 형식: 본문(<s>지운 것</s><font color="red">고친 것</font>)
  + "Suggestions for Improvement: ..." + "Your Score: B" (일부는 Content/Grammar/Structure 점수)
선생님 첨삭과 같은 표시 방식이라 본문은 teacher_parse로 읽는다.
"""
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from programs.essay.teacher_parse import parse_teacher  # noqa: E402

SUGGEST_HEAD = re.compile(r"suggestions? for improvement", re.I)


def text_of(h: str) -> str:
    t = re.sub(r"<br\s*/?>|</div>|</p>", "\n", h, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def split_gpt(correction: str) -> tuple[str, str, str | None, dict]:
    """(본문 HTML, 제안 글, 등급, 점수)"""
    m = SUGGEST_HEAD.search(correction)
    body_html = correction[:m.start()] if m else correction
    tail = text_of(correction[m.end():]) if m else ""
    grade = re.search(r"Your Score\s*:\s*([A-F])", tail)
    scores = {k.lower(): int(v) for k, v in re.findall(r"(Grammar|Structure|Content)\s*:\s*(\d+)", tail)}
    sugg = re.split(r"Your Score|Content\s*:|Grammar\s*:|Structure\s*:", tail)[0]
    sugg = re.sub(r"^\s*:?\s*", "", sugg)
    sugg = re.sub(r"^\s*(?:\d+\.|-)\s*", "", sugg, flags=re.M)  # 목록 기호 제거
    sugg = re.sub(r"\s+", " ", sugg).strip()
    return body_html, sugg, grade.group(1) if grade else None, scores


src = Path(sys.argv[1])
rows = json.load(src.open(encoding="utf-8"))
out = src.with_name(f"{src.stem}_eval.jsonl")
with out.open("w", encoding="utf-8") as f:
    for r in rows:
        body_html, sugg, grade, scores = split_gpt(r["correction"])
        p = parse_teacher({"id": r["homeworkStudentIdx"], "essay": r["essay"], "correction": body_html,
                           "topic": r.get("topic"), "levelName": r.get("levelName"), "eval": grade})
        p["gpt_suggestions"] = sugg
        p["rubric"] = scores if {"grammar", "structure", "content"} <= scores.keys() else None
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
out.chmod(0o600)
print(f"wrote {out} ({len(rows)} rows)")
