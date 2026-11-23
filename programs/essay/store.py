"""에세이 배치용 MSSQL 읽기/쓰기. SQL은 전부 여기에만 둔다 (테이블이 바뀌면 이 파일만 고친다).

접속 정보는 .env:
  MSSQL_SERVER=호스트,포트      (예: 10.0.0.5,1433)
  MSSQL_DATABASE=DB이름
  MSSQL_USER=배치 전용 계정
  MSSQL_PASSWORD=...
  MSSQL_ENCRYPT=no            (기존 Spring 설정이 encrypt=false라서 맞춤. 기본 yes)
  MSSQL_TRUST_CERT=yes        (사내 DB가 자체 서명 인증서면 yes)

테이블: HC_HomeWork_Student (Writing = 학생 원본, ReWriting = 첨삭본, CorrectMpIdx = 첨삭한 선생님)
"""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PendingEssay:
    id: int
    essay: str
    topic: str | None
    level_name: str | None


# 첨삭 대상: 학원에서 쓰던 "첨삭할 학생 뽑기" 쿼리를 배치용으로 다듬음
#  - 에세이·뉴스 숙제 (HomeWorkKind 2 = 에세이, 3 = 뉴스. 뉴스는 글 없이 등급만 매기는 경우가 대부분), 글 있음, 첨삭본(ReWriting) 없음, 본사(FrCode=0), 재원생
#  - 학생 이름(M_PerSon, M_Student) 조인은 뺌 (첨삭에 필요 없음)
#  - 소속(M_SoSok)은 EXISTS로 바꿔서 소속이 여러 개인 학생의 글이 중복으로 나오지 않게 함
#  - 레벨 이름: P_Class.LevelNameIdx -> C_LevelName.LevelName
# 주제(topic)는 넘기지 않는다: 숙제 제목(HC_HomeWork_Detail.Title)이 주제가 아니라 선생님 숙제 안내문이라
# 모델이 글에서 주제를 추론하게 둔다.
_PENDING_FROM = """
FROM HC_HomeWork_Student a
JOIN HC_HomeWork_Detail d ON d.HomeWorkItemIdx = a.HomeWorkItemIdx
JOIN P_Class b ON b.ClassIdx = a.ClassIdx
LEFT JOIN C_LevelName L ON L.LevelNameIdx = b.LevelNameIdx
WHERE d.HomeWorkKind IN ('2', '3')  -- 2 = 에세이, 3 = 뉴스
  AND a.Writing <> ''
  AND (a.ReWriting IS NULL OR a.ReWriting = '')
  AND ISNULL(a.Eval, '') NOT IN ('N', 'F')  -- 선생님이 먼저 N/F로 채점한 글은 제외 (.NET 자동첨삭과 같음)
  AND EXISTS (SELECT 1 FROM M_SoSok h JOIN O_Group g ON g.GroupIdx = h.GroupIdx
              WHERE h.MPIdx = a.MPIdx AND g.FrCode = 0)
  AND EXISTS (SELECT 1 FROM P_Class_BaeJung bj WHERE bj.MPIdx = a.MPIdx AND bj.Status = '1')
"""
_COLUMNS = "a.HomeWorkStudentIdx, a.Writing, NULL AS topic, L.LevelName"

# ? 자리: 최대 건수. 오래된 글부터.
SQL_PENDING = f"SELECT TOP (?) {_COLUMNS} {_PENDING_FROM} ORDER BY a.HomeWorkStudentIdx"

# 특정 글만 (수동 실행 --id). 대상 조건은 같게 둬서 이미 첨삭된 글은 다시 안 건드린다.
SQL_BY_ID = f"SELECT {_COLUMNS} {_PENDING_FROM} AND a.HomeWorkStudentIdx = ?"

# 첨삭본 저장: .NET GPT 첨삭이 쓰던 프로시저 두 개를 쿼리 하나로 옮김 (프로시저는 걷어낼 예정)
#   HomeWork_Eassy_Rewrite_Save    -> ReWriting, GPTCorrectYn, GptCorrectDt(오늘. 프로시저는 비어 있을 때만 넣었지만
#                                     첨삭 대상 에세이 중 날짜가 이미 있는 글은 0건이라 단순화)
#   HomeWork_Student_One_Tms_Save2 -> Eval, CorrectMpIdx(= 첨삭자), GPTCorrectYn
#     (EvlComment는 선생님 코멘트라 건드리지 않는다. 프로시저는 받은 값으로 덮어썼음)
# 문장 하나라 원자적이고, WHERE에서 첨삭본이 아직 비어 있는지 확인하므로
# 배치가 도는 사이에 선생님이 먼저 첨삭한 글은 덮어쓰지 않는다.
# 선생님이 나중에 수정하면 CorrectMpIdx가 그 선생님 id로 바뀌므로, 시스템 id면 "AI 첨삭 그대로"다.
# TODO: AI 첨삭본 컬럼(AiReWriting 등)이 추가되면 같이 저장
SYSTEM_MPIDX = 6951  # 시스템 계정 (GPT 첨삭도 이 id로 들어가 있음)
# GPTCorrectYn = '1': GPT 첨삭과 똑같이 표시 (Royalty_Proc 로열티 정산 건수에 포함됨)
# ? 자리: html, grade, 시스템 id, id
SQL_SAVE = """
UPDATE HC_HomeWork_Student
SET ReWriting = ?,
    Eval = ?,
    CorrectMpIdx = ?,
    GPTCorrectYn = '1',
    GptCorrectDt = CONVERT(char(8), GETDATE(), 112)
WHERE HomeWorkStudentIdx = ?
  AND (ReWriting IS NULL OR ReWriting = '')
"""


def connect():
    # Ssm DB(SQL Server 2008 R2)가 TLS 1.0/1.1만 지원 -> 이 프로세스에서만 옛 TLS 허용 (mssql_openssl.cnf)
    os.environ.setdefault("OPENSSL_CONF", str(Path(__file__).resolve().parents[2] / "mssql_openssl.cnf"))
    import pyodbc  # 드라이버가 없는 개발 환경에서도 다른 모듈은 import 되게 여기서 불러온다

    missing = [k for k in ("MSSQL_SERVER", "MSSQL_DATABASE", "MSSQL_USER", "MSSQL_PASSWORD") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f".env에 {', '.join(missing)} 가 없습니다.")
    def braced(v: str) -> str:  # 비밀번호에 ; { } 가 있어도 안전하게
        return "{" + v.replace("}", "}}") + "}"

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['MSSQL_SERVER']};"
        f"DATABASE={os.environ['MSSQL_DATABASE']};"
        f"UID={braced(os.environ['MSSQL_USER'])};"
        f"PWD={braced(os.environ['MSSQL_PASSWORD'])};"
        f"Encrypt={os.getenv('MSSQL_ENCRYPT', 'yes')};"
        f"TrustServerCertificate={os.getenv('MSSQL_TRUST_CERT', 'no')};"
    )
    return pyodbc.connect(conn_str, timeout=15, autocommit=True)


def _rows(cur) -> list[PendingEssay]:
    return [PendingEssay(id=r[0], essay=r[1], topic=r[2], level_name=r[3]) for r in cur.fetchall()]


def fetch_pending(conn, limit: int) -> list[PendingEssay]:
    cur = conn.cursor()
    cur.execute(SQL_PENDING, limit)
    return _rows(cur)


def fetch_by_ids(conn, ids: list[int]) -> list[PendingEssay]:
    out = []
    cur = conn.cursor()
    for i in ids:
        cur.execute(SQL_BY_ID, i)
        out += _rows(cur)
    return out


def save(conn, essay_id: int, html: str, grade: str) -> bool:
    """저장했으면 True. 그 사이 선생님이 고쳐서 조건에 안 맞으면 False"""
    # 첨삭 컬럼이 varchar(Korean_Wansung)라서 ’ “ — 같은 문자는 저장하면 "?"로 깨진다
    # (선생님 첨삭 데이터의 "?" 흔적이 이것). HTML 엔티티(&#8217;)로 바꿔 저장하면 화면에는 그대로 보인다.
    html = html.encode("ascii", "xmlcharrefreplace").decode("ascii")
    cur = conn.cursor()
    cur.execute(SQL_SAVE, html, grade, SYSTEM_MPIDX, essay_id)
    return cur.rowcount == 1
