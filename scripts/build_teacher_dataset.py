"""선생님 첨삭 원본(JSON) -> 통일된 JSONL + 검증용 미리보기 HTML

사용법:
  .venv/bin/python scripts/build_teacher_dataset.py data/essay/essay_topic_100.json
결과 (<이름> = 입력 파일 이름, 예: essay_topic_100):
  data/essay/processed/<이름>_normalized.jsonl   한 줄에 한 건
  data/essay/processed/<이름>_train.jsonl        학습·예시용
  data/essay/processed/<이름>_eval.jsonl         채점용 (약 100건)
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from programs.essay.teacher_parse import parse_teacher  # noqa: E402

src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/essay/essay_topic_100.json")
out_dir = src.parent / "processed"  # 원본(data/)과 섞이지 않게 생성 파일은 따로
out_dir.mkdir(mode=0o700, exist_ok=True)
stem = src.stem
rows = json.loads(src.read_text(encoding="utf-8"))

parsed, errors = [], []
for r in rows:
    try:
        parsed.append(parse_teacher(r))
    except Exception as e:  # 한 건이 이상해도 전체는 계속
        errors.append((r.get("id"), repr(e)))

out = out_dir / f"{stem}_normalized.jsonl"
with out.open("w", encoding="utf-8") as f:
    for p in parsed:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
out.chmod(0o600)

# ---- 통계
n = len(parsed)
flags = Counter(fl for p in parsed for fl in p["flags"])
print(f"parsed {n}/{len(rows)}  errors={len(errors)}")
for e in errors[:5]:
    print("  error:", e)
print("flags:", dict(flags))
print("with rubric:", sum(p["rubric"] is not None for p in parsed),
      " full rubric(g/s/c):", sum(bool(p["rubric"]) and {"grammar", "structure", "content"} <= p["rubric"].keys() for p in parsed))
print("with comment:", sum(p["comment"] is not None for p in parsed))
print("with notes:", sum(bool(p["notes"]) for p in parsed), " total notes:", sum(len(p["notes"]) for p in parsed))
print("with header:", sum(p["header"] is not None for p in parsed))
al = sorted(p["stats"]["alignment"] for p in parsed)
print("alignment min/p10/median:", al[0], al[n // 10], al[n // 2])
print("grade:", Counter(p["grade"] for p in parsed))
if any(p.get("topic") for p in parsed):
    print("topics:", len({p["topic"] for p in parsed}))
by_grade = {}
for p in parsed:
    if p["rubric"] and "total" in p["rubric"]:
        by_grade.setdefault(p["grade"], []).append(p["rubric"]["total"])
for g, v in sorted(by_grade.items()):
    print(f"  total/20 for {g}: n={len(v)} min={min(v)} max={max(v)} avg={sum(v) / len(v):.1f}")

# ---- 학습용 / 채점용 분리
# 채점용(약 100건)은 문제 플래그 없는 깨끗한 데이터에서 뽑는다. seed 고정 = 항상 같은 분리
# 주제(topic)가 있으면 주제 x 등급 비율대로, 없으면 등급 비율대로.
rng = random.Random(42)
clean = [p for p in parsed if not p["flags"]]
strata = Counter((p.get("topic"), p["grade"]) for p in parsed)
eval_rows = []
for key in sorted(strata, key=str):
    pool = [p for p in clean if (p.get("topic"), p["grade"]) == key]
    k = round(100 * strata[key] / n)
    eval_rows += rng.sample(pool, min(k, len(pool)))
eval_ids = {p["id"] for p in eval_rows}
for name, subset in (("train", [p for p in parsed if p["id"] not in eval_ids]), ("eval", eval_rows)):
    path = out_dir / f"{stem}_{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for p in subset:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    path.chmod(0o600)
    print(f"{name}: {len(subset)} {dict(Counter(p['grade'] for p in subset))}")

print(f"\nwrote {out}")
