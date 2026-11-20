"""/essay 결과를 선생님 첨삭과 비교한다.

사용법:
  .venv/bin/python scripts/eval_essay.py run [개수] [--no-think]   # 채점용 데이터로 실행 (중단 후 이어서 가능)
  .venv/bin/python scripts/eval_essay.py report                  # 결과 요약
결과:
  data/processed/eval_runs/<이름>.jsonl   한 편씩 결과
지표:
  - 등급 일치율: 서버가 계산한 A/B/C vs 선생님 등급
  - 수정 위치 일치: 모델이 고친 곳 중 선생님도 고친 비율(정밀도), 선생님이 고친 곳 중 모델도 고친 비율(재현율)
    (선생님은 표현 다듬기까지 하고 우리는 틀린 것만 고치므로, 재현율은 낮게 나오는 게 정상)
  - 과잉 수정: 모델이 바꾼 단어 비율 vs 선생님이 바꾼 단어 비율
"""
import asyncio
import json
import re
import sys
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.main import EssayRequest, essay  # noqa: E402

EVAL_FILE = ROOT / "data/processed/essay_topic_100_eval.jsonl"
RUN_DIR = ROOT / "data/processed/eval_runs"
TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*|[^\sA-Za-z0-9]")


def toks(text: str) -> list[str]:
    return [t.replace("’", "'") for t in TOKEN.findall(text)]


def changed_positions(orig: list[str], new: list[str]) -> set[tuple]:
    """원문 기준으로 바뀐 위치. 바뀐/지운 토큰은 ('t', i), 끼워 넣은 자리는 ('gap', i)"""
    pos = set()
    for op, i1, i2, _, _ in SequenceMatcher(None, orig, new, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            pos.update(("t", i) for i in range(i1, i2))
        elif op == "insert":
            pos.add(("gap", i1))
    return pos


def run(limit: int | None, think: bool):
    rows = [json.loads(l) for l in EVAL_FILE.open(encoding="utf-8")]
    if limit:
        rows = rows[:limit]
    RUN_DIR.mkdir(mode=0o700, exist_ok=True)
    out_path = RUN_DIR / f"{'think' if think else 'nothink'}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.open(encoding="utf-8")}
    todo = [r for r in rows if r["id"] not in done]
    print(f"eval rows: {len(rows)}  done: {len(done)}  todo: {len(todo)}  -> {out_path}", flush=True)

    async def go():
        with out_path.open("a", encoding="utf-8") as f:
            for i, r in enumerate(todo, 1):
                t = time.time()
                try:
                    res = await essay(EssayRequest(essay=r["essay_raw"], topic=r["topic"],
                                                   level_name=r["level"], think=think))
                    rec = {"id": r["id"], "ok": True, "seconds": round(time.time() - t, 1),
                           "teacher_grade": r["grade"], "grade": res.grade,
                           "scores": res.scores.model_dump(), "essay": res.essay,
                           "corrected": res.corrected, "teacher_corrected": r["corrected"],
                           "comment": res.comment, "topic": r["topic"], "level": r["level"]}
                except Exception as e:  # 한 편 실패해도 계속
                    rec = {"id": r["id"], "ok": False, "error": repr(e)[:300],
                           "seconds": round(time.time() - t, 1)}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                status = f"{rec['teacher_grade']}->{rec['grade']} {rec['scores']['total']}/20" if rec["ok"] else "ERROR"
                print(f"[{i}/{len(todo)}] {r['id']} {rec['seconds']}s {status}", flush=True)

    asyncio.run(go())
    out_path.chmod(0o600)


def report():
    for path in sorted(RUN_DIR.glob("*.jsonl")):
        recs = [json.loads(l) for l in path.open(encoding="utf-8")]
        ok = [r for r in recs if r["ok"]]
        print(f"\n===== {path.name}: {len(ok)}/{len(recs)} ok, "
              f"avg {sum(r['seconds'] for r in ok) / max(1, len(ok)):.0f}s/essay")
        if not ok:
            continue
        # 등급
        match = sum(r["grade"] == r["teacher_grade"] for r in ok)
        print(f"grade match: {match}/{len(ok)} = {match / len(ok):.0%}")
        conf = Counter((r["teacher_grade"], r["grade"]) for r in ok)
        print("confusion (teacher -> model):")
        for tg in "ABC":
            print(f"  teacher {tg}: " + "  ".join(f"{mg}={conf[(tg, mg)]}" for mg in "ABC"))
        by = defaultdict(list)
        for r in ok:
            by[r["teacher_grade"]].append(r["scores"]["total"])
        for tg in sorted(by):
            v = by[tg]
            print(f"  model total for teacher {tg}: avg {sum(v) / len(v):.1f}  min {min(v)}  max {max(v)}")
        for k in ("grammar", "structure", "content"):
            print(f"  avg {k}: {sum(r['scores'][k] for r in ok) / len(ok):.2f}")
        # 수정 위치
        tp = mp = tt = 0
        m_ratio = t_ratio = 0.0
        for r in ok:
            o = toks(r["essay"])
            m = changed_positions(o, toks(r["corrected"]))
            t = changed_positions(o, toks(r["teacher_corrected"]))
            tp += len(m & t)
            mp += len(m)
            tt += len(t)
            m_ratio += len(m) / max(1, len(o))
            t_ratio += len(t) / max(1, len(o))
        print(f"edit precision (model edits teacher also made): {tp / max(1, mp):.0%}")
        print(f"edit recall (teacher edits model also made):    {tp / max(1, tt):.0%}")
        print(f"changed tokens per essay: model {m_ratio / len(ok):.1%}  teacher {t_ratio / len(ok):.1%}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        run(int(args[0]) if args else None, think="--no-think" not in sys.argv)
    else:
        report()
