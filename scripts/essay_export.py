"""에세이 배치가 처리한 글을 DB에서 꺼내 HTML로 보기 (읽기만 한다).

사용법 (저장소 루트에서):
  .venv/bin/python scripts/essay_export.py                 # 오늘 배치
  .venv/bin/python scripts/essay_export.py --date 2026-11-25

대상 글 id와 점수는 그날 배치 로그(journalctl -u essay-batch)에서 읽는다.
결과: data/essay/exports/<날짜>.html (브라우저로 열기. eval_essay.py compare와 같은 카드 모양:
원문 / AI 첨삭 = DB에 저장된 HTML 그대로, 아이 화면과 같음)
"""
import argparse
import datetime as dt
import html
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from programs.essay import store  # noqa: E402

LINE = re.compile(r"\[(\d+)/\d+\] id=(\d+) ([\d.]+)s (\S+) (\d+)/20(?: 되돌림 (\d+))?")


def batch_log(day: dt.date) -> list[dict]:
    nxt = day + dt.timedelta(days=1)
    out = subprocess.run(["journalctl", "-u", "essay-batch.service", "--since", f"{day} 00:00",
                          "--until", f"{nxt} 00:00", "--no-pager", "-o", "cat"],
                         capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        m = LINE.search(line)
        if m:
            rows.append({"id": int(m[2]), "seconds": float(m[3]), "grade_log": m[4],
                         "score": int(m[5]), "reverts": int(m[6] or 0)})
    return rows


def main():
    p = argparse.ArgumentParser(description="에세이 배치 결과 HTML로 보기")
    p.add_argument("--date", default=str(dt.date.today()), help="배치 날짜 YYYY-MM-DD (기본 오늘)")
    args = p.parse_args()
    day = dt.date.fromisoformat(args.date)

    load_dotenv(ROOT / ".env")
    logged = batch_log(day)
    if not logged:
        sys.exit(f"{day} 배치 로그에 처리한 글이 없습니다.")
    conn = store.connect()
    db = {r["id"]: r for r in store.fetch_results(conn, [r["id"] for r in logged])}

    out_dir = ROOT / "data" / "essay" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    cards = []
    for r in logged:
        d = db.get(r["id"], {})
        edited = " · <b>이후 선생님 수정</b>" if d.get("edited_by_teacher") else ""
        reverts = f" · 되돌림 {r['reverts']}" if r["reverts"] else ""
        cards.append(f"""
<section>
  <h3>id {r['id']} · {html.escape(d.get('level') or '')}</h3>
  <p class="meta">등급 {html.escape(d.get('eval') or r['grade_log'])} · {r['score']}/20{reverts}{edited} · {r['seconds']}초</p>
  <div class="cols">
    <div><h4>원문</h4><div class="box pre">{html.escape(d.get('writing') or '')}</div></div>
    <div><h4>AI 첨삭 (아이 화면)</h4><div class="box">{d.get('rewriting') or '(첨삭본 없음)'}</div></div>
  </div>
</section>""")
    out = out_dir / f"{day}.html"
    out.write_text(f"""<!doctype html><meta charset="utf-8"><title>{day} 에세이 첨삭</title>
<style>body{{font-family:sans-serif;margin:20px}} .cols{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.box{{border:1px solid #ccc;padding:10px;font-size:14px;line-height:1.6;overflow-wrap:anywhere}} .pre{{white-space:pre-wrap}}
.meta{{color:#555;font-size:13px}} section{{border-bottom:3px solid #eee;padding-bottom:20px;margin-bottom:20px}}</style>
<h2>{day} 에세이 첨삭 배치 ({len(cards)}편)</h2>
{''.join(cards)}""", encoding="utf-8")
    out.chmod(0o600)

    grades = {}
    for r in logged:
        grades[r["grade_log"]] = grades.get(r["grade_log"], 0) + 1
    edited = sum(1 for d in db.values() if d["edited_by_teacher"])
    print(f"{day}: {len(logged)}편 (DB에서 찾음 {len(db)}), 등급 {dict(sorted(grades.items()))}, "
          f"평균 {sum(r['score'] for r in logged) / len(logged):.1f}/20, 되돌림 있는 글 {sum(1 for r in logged if r['reverts'])}, "
          f"이후 선생님 수정 {edited}")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
