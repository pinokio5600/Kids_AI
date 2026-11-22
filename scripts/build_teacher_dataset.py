"""선생님 첨삭 원본(JSON) -> 통일된 JSONL + 검증용 미리보기 HTML

사용법:
  .venv/bin/python scripts/build_teacher_dataset.py data/essay/essay_topic_100.json
결과 (<이름> = 입력 파일 이름, 예: essay_topic_100):
  data/essay/processed/<이름>_normalized.jsonl   한 줄에 한 건
  data/essay/processed/<이름>_train.jsonl        학습·예시용
  data/essay/processed/<이름>_eval.jsonl         채점용 (약 100건)
  data/essay/processed/<이름>_preview.html       선생님 원본 vs 우리 렌더링 비교 (브라우저로 열기)
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from programs.essay.render import render  # noqa: E402
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

# ---- 미리보기: 무작위 + 플래그 있는 것 위주로 섞어서
random.seed(0)
by_id = {r["id"]: r for r in rows}
flagged = [p for p in parsed if p["flags"]]
picked = random.sample(parsed, min(12, n)) + random.sample(flagged, min(6, len(flagged)))
cards = []
for p in picked:
    ours = render(p["essay"], p["corrected"], p["notes"], p["comment"], p["rubric"], p["grade"])
    meta = json.dumps({k: p.get(k) for k in ("id", "topic", "level", "grade", "rubric", "flags", "stats", "header")}, ensure_ascii=False)
    cards.append(f"""
<section>
  <h3>id {p['id']} · {p['grade']} · flags: {', '.join(p['flags']) or '-'}</h3>
  <pre>{meta}</pre>
  <div class="cols">
    <div><h4>선생님 원본</h4><div class="box">{by_id[p['id']]['correction']}</div></div>
    <div><h4>우리 렌더링 (원문 essay ↔ 추출한 고친 글 비교)</h4><div class="box">{ours}</div></div>
  </div>
</section>""")
preview = out_dir / f"{stem}_preview.html"
preview.write_text(f"""<!doctype html><meta charset="utf-8"><title>teacher preview</title>
<style>body{{font-family:sans-serif;margin:20px}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.box{{border:1px solid #ccc;padding:10px;font-size:14px;line-height:1.6}} pre{{white-space:pre-wrap;font-size:12px;color:#555}}
section{{border-bottom:3px solid #eee;padding-bottom:20px;margin-bottom:20px}}</style>
{''.join(cards)}""", encoding="utf-8")
preview.chmod(0o600)
print(f"\nwrote {out} and {preview}")
