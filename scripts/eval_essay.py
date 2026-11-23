"""/essay 결과를 선생님 첨삭과 비교한다.

사용법:
  .venv/bin/python scripts/eval_essay.py run [개수] [--no-think] [--name=이름] [--data=파일] [--rubric-only]
      # 채점용 데이터로 실행 (중단 후 이어서 가능)
      # --data: data/essay/processed/ 아래 jsonl (기본 essay_topic_100_eval.jsonl)
      # --rubric-only: 선생님 점수(grammar/structure/content)가 다 있는 글만
  .venv/bin/python scripts/eval_essay.py report                                # 결과 요약
  .venv/bin/python scripts/eval_essay.py same 이름1 이름2                        # 두 번 돌린 결과가 같은지 (일관성)
  .venv/bin/python scripts/eval_essay.py compare 이름 [개수]                     # 원문 / 기존 첨삭 / AI 첨삭 비교 HTML
결과:
  data/essay/processed/eval_runs/<이름>.jsonl         한 편씩 결과
  data/essay/processed/eval_runs/<이름>_compare.html  비교 화면 (브라우저로 열기)
지표:
  - 점수·등급 분포: 우리 기준표로 매긴 결과가 한쪽에 몰리지 않는지
  - 등급 일치율: 참고용. 선생님 등급은 글 외의 요소가 섞여 있어 맞추는 목표가 아님
  - 항목별 점수 비교: 선생님 점수가 있는 글만 (평균 차이, 일치율)
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

EVAL_FILE = ROOT / "data/essay/processed/essay_topic_100_eval.jsonl"
RUN_DIR = ROOT / "data/essay/processed/eval_runs"
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


def has_rubric(r: dict) -> bool:
    return bool(r.get("rubric")) and all(r["rubric"].get(k) is not None for k in ("grammar", "structure", "content"))


def run(limit: int | None, think: bool, name: str | None, data: Path, rubric_only: bool):
    rows = [json.loads(l) for l in data.open(encoding="utf-8")]
    if rubric_only:
        rows = [r for r in rows if has_rubric(r)]
    if limit:
        rows = rows[:limit]
    RUN_DIR.mkdir(mode=0o700, exist_ok=True)
    out_path = RUN_DIR / f"{name or ('think' if think else 'nothink')}.jsonl"
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
                           "comment": res.comment, "topic": r["topic"], "level": r["level"],
                           "teacher_scores": r["rubric"] if has_rubric(r) else None}
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
        for k in ("grammar", "structure", "content", "total"):
            dist = sorted(Counter(r["scores"][k] for r in ok).items())
            print(f"  {k}: avg {sum(r['scores'][k] for r in ok) / len(ok):.2f}  " + " ".join(f"{s}:{n}" for s, n in dist))
        tr = [r for r in ok if r.get("teacher_scores")]
        if tr:
            print(f"  vs teacher scores ({len(tr)} essays):")
            for k in ("grammar", "structure", "content", "total"):
                t = [r["teacher_scores"][k] if k != "total" else sum(r["teacher_scores"][c] for c in ("grammar", "structure", "content")) for r in tr]
                m = [r["scores"][k] for r in tr]
                print(f"    {k}: teacher avg {sum(t) / len(t):.2f}  model avg {sum(m) / len(m):.2f}  "
                      f"exact {sum(a == b for a, b in zip(t, m)) / len(tr):.0%}  within1 {sum(abs(a - b) <= 1 for a, b in zip(t, m)) / len(tr):.0%}")
        print("  grades: " + " ".join(f"{g}={n}" for g, n in sorted(Counter(r["grade"] for r in ok).items())))
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


def compare(name: str, limit: int | None):
    """원문 / 기존 첨삭(선생님이 만든 HTML 그대로) / AI 첨삭(아이 화면에 나갈 HTML)을 나란히"""
    import html as htmlmod
    from programs.essay.render import render

    recs = [r for r in map(json.loads, (RUN_DIR / f"{name}.jsonl").open(encoding="utf-8")) if r["ok"]]
    recs = recs[:limit] if limit else recs
    want = {r["id"] for r in recs}
    teacher = {}
    for src in (ROOT / "data/essay").glob("*.json"):
        for row in json.load(src.open(encoding="utf-8")):
            if row["id"] in want:
                teacher[row["id"]] = row
    cards = []
    for r in recs:
        t = teacher.get(r["id"], {})
        ai = render(r["essay"], r["corrected"], None, r["comment"], r["scores"], r["grade"])
        ts = r.get("teacher_scores")
        t_score = f" · 선생님 {ts['grammar']}/{ts['structure']}/{ts['content']}" if ts else ""
        s = r["scores"]
        cards.append(f"""
<section>
  <h3>id {r['id']} · {htmlmod.escape(r.get('level') or '')} · {htmlmod.escape(r.get('topic') or '')}</h3>
  <p class="meta">등급: 선생님 {r['teacher_grade']}{t_score} → AI {r['grade']} ({s['grammar']}/{s['structure']}/{s['content']} = {s['total']}/20) · {r['seconds']}초</p>
  <div class="cols">
    <div><h4>원문</h4><div class="box pre">{htmlmod.escape(r['essay'])}</div></div>
    <div><h4>기존 첨삭 (선생님)</h4><div class="box">{t.get('correction', '(원본 데이터 없음)')}</div></div>
    <div><h4>AI 첨삭</h4><div class="box">{ai}</div></div>
  </div>
</section>""")
    out = RUN_DIR / f"{name}_compare.html"
    out.write_text(f"""<!doctype html><meta charset="utf-8"><title>{name} 비교</title>
<style>body{{font-family:sans-serif;margin:20px}} .cols{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}}
.box{{border:1px solid #ccc;padding:10px;font-size:14px;line-height:1.6;overflow-wrap:anywhere}} .pre{{white-space:pre-wrap}}
.meta{{color:#555;font-size:13px}} section{{border-bottom:3px solid #eee;padding-bottom:20px;margin-bottom:20px}}</style>
<p>원문 = 과제 양식을 걷어낸 아이 글 (AI가 받은 입력) · 기존 첨삭 = 선생님이 만든 HTML 그대로 · AI 첨삭 = 아이 화면에 나갈 HTML</p>
{''.join(cards)}""", encoding="utf-8")
    out.chmod(0o600)
    print(f"wrote {out} ({len(cards)} essays)")


def same(a: str, b: str):
    load = lambda n: {r["id"]: r for r in map(json.loads, (RUN_DIR / f"{n}.jsonl").open(encoding="utf-8")) if r["ok"]}
    ra, rb = load(a), load(b)
    ids = sorted(ra.keys() & rb.keys())
    print(f"common: {len(ids)}")
    for key, f in [("scores", lambda r: r["scores"]), ("grade", lambda r: r["grade"]),
                   ("corrected", lambda r: r["corrected"]), ("comment", lambda r: r["comment"])]:
        n = sum(f(ra[i]) == f(rb[i]) for i in ids)
        print(f"  same {key}: {n}/{len(ids)}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "run":
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        name = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--name=")), None)
        data = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--data=")), None)
        run(int(args[0]) if args else None, think="--no-think" not in sys.argv, name=name,
            data=RUN_DIR.parent / data if data else EVAL_FILE, rubric_only="--rubric-only" in sys.argv)
    elif cmd == "compare":
        compare(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else None)
    elif cmd == "same":
        same(sys.argv[2], sys.argv[3])
    else:
        report()
