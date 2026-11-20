# Kids_AI

아이들 영어 학습용 AI 도구 모음.

| 폴더 | 내용 |
|---|---|
| `app/`, `essay/`, `scripts/` | AI 서버 (FastAPI + Ollama): 에세이 첨삭·채점, 문법 교정, 채팅 |
| `stt/` | 소리 내어 읽기 채점: 음성을 받아 적고(faster-whisper) 대본과 비교 |

## AI 서버

- 실행: `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000` (운영은 `ai-server.service`로 systemd 등록)
- 설정: `.env`에 `OLLAMA_URL`, `DEFAULT_MODEL`, `API_KEYS` (저장소에는 올리지 않음)
- 모든 API는 `X-API-Key` 헤더 필요 (`/health` 제외)

| 엔드포인트 | 설명 |
|---|---|
| `POST /essay` | 에세이 첨삭(틀린 것만 고침) + 채점(Grammar 5 / Structure 5 / Content 10) + 아이용 HTML |
| `POST /grammar` | 영어 문법 교정 + 고친 이유 |
| `POST /chat`, `POST /chat/stream` | 일반 대화 (대화 기록, 스트리밍) |

- 채점 기준·레벨별 학년: `essay/rubric.py`
- 과제 양식 정리: `essay/clean.py`
- 선생님 첨삭 데이터 변환: `scripts/build_teacher_dataset.py`
- 선생님 첨삭과 비교 평가: `scripts/eval_essay.py`

## STT

`stt/` 폴더에서 실행. 자세한 사용법은 `stt/transcribe.py`, `stt/compare.py` 상단 설명 참고.
