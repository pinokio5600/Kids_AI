"""에세이 첨삭 배치: DB에서 첨삭 안 된 글을 꺼내 한 편씩 첨삭하고 바로 저장한다.

자동: systemd timer가 매일 새벽 2시에 실행 (essay-batch.timer)
수동:
  sudo systemctl start essay-batch            # 새벽 2시와 똑같이 지금 실행 (로그: journalctl -u essay-batch)
  .venv/bin/python scripts/essay_batch.py --limit 5 --dry-run   # 5편만 첨삭해 보고 저장은 안 함
  .venv/bin/python scripts/essay_batch.py --id 123 --id 456     # 특정 글만

- 한 편 끝날 때마다 저장하므로 중간에 끊겨도 다음 실행이 남은 글부터 이어 한다.
- 실패한 글은 비워 둔다 -> 다음 실행 때 다시 시도.
- 동시에 두 개가 돌지 않게 잠금 파일을 쓴다 (timer 실행 중에 수동으로 돌려도 안전).
- 이미 첨삭본(ReWriting)이 있는 글은 읽지도 덮어쓰지도 않는다 (저장 직전에도 다시 확인).
"""
import os
from pathlib import Path

# OpenSSL은 처음 import될 때 설정을 읽으므로 다른 import보다 먼저 지정한다
# (Ssm DB가 TLS 1.0/1.1만 지원 -> mssql_openssl.cnf, programs/essay/store.py 참고)
os.environ.setdefault("OPENSSL_CONF", str(Path(__file__).resolve().parents[1] / "mssql_openssl.cnf"))

import argparse  # noqa: E402
import asyncio  # noqa: E402
import fcntl  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from programs.essay import store  # noqa: E402
from programs.essay.grade import grade_essay  # noqa: E402

LOCK_FILE = ROOT / "data" / ".essay_batch.lock"
MAX_CONSECUTIVE_FAILS = 5  # 연속으로 실패하면 Ollama·DB 문제로 보고 멈춘다


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


async def run(limit: int, ids: list[int], dry_run: bool) -> int:
    conn = store.connect()
    rows = store.fetch_by_ids(conn, ids) if ids else store.fetch_pending(conn, limit)
    log(f"대상 {len(rows)}편{' (dry-run: 저장 안 함)' if dry_run else ''}")

    ok = fail = skipped = streak = 0
    started = time.time()
    for n, row in enumerate(rows, 1):
        t = time.time()
        try:
            res = await grade_essay(row.essay, row.topic, row.level_name)
        except Exception as e:  # 한 편 실패가 배치 전체를 멈추지 않게
            fail += 1
            streak += 1
            log(f"[{n}/{len(rows)}] id={row.id} 실패: {type(e).__name__}: {str(e)[:200]}")
            if streak >= MAX_CONSECUTIVE_FAILS:
                log(f"연속 {streak}번 실패해서 중단합니다 (Ollama 상태를 확인하세요)")
                break
            continue
        streak = 0
        note = f" 되돌림 {len(res.reverted_edits)}" if res.reverted_edits else ""
        if dry_run:
            ok += 1
        elif store.save(conn, row.id, res.html, res.grade):
            ok += 1
        else:
            skipped += 1
            note += " (그 사이 선생님이 수정해서 저장 안 함)"
        log(f"[{n}/{len(rows)}] id={row.id} {time.time() - t:.1f}s {res.grade} {res.scores.total}/20{note}")

    log(f"끝: 성공 {ok}, 실패 {fail}, 건너뜀 {skipped}, {time.time() - started:.0f}초")
    conn.close()
    # 전부 실패했을 때만 오류 종료 (systemctl status에 failed로 보이게)
    return 1 if fail and not ok else 0


def main() -> int:
    p = argparse.ArgumentParser(description="에세이 첨삭 배치")
    p.add_argument("--limit", type=int, default=5000, help="이번 실행에서 처리할 최대 편수 (기본 5000)")
    p.add_argument("--id", type=int, action="append", default=[], help="이 글만 처리 (여러 번 쓸 수 있음)")
    p.add_argument("--dry-run", action="store_true", help="첨삭만 해 보고 DB에 저장하지 않음")
    args = p.parse_args()

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("이미 배치가 실행 중이라 종료합니다")
            return 0
        return asyncio.run(run(args.limit, args.id, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
