# Kids_AI

아이들 영어 학습용 AI 도구 모음.

## 구조

```
app/main.py           API 입구 (요청 검사 -> 프로그램/핵심 기능 호출)
core/                 핵심 기능: 여러 프로그램이 같이 쓴다
  llm.py              Ollama 설정·호출
  grammar/            문법 교정 규칙 (rules.py), 문법 검사 (check.py)
  stt/                음성 받아 적기 엔진 (engine.py), 받아쓰기 명령줄 도구 (transcribe.py)
programs/             프로그램: core를 가져다 쓴다
  essay/              에세이 첨삭·채점
  portfolio/          포트폴리오 영상(대본 읽기) 채점
scripts/              개발용 스크립트 (선생님 데이터 변환, 에세이 평가)
data/                 아이들 데이터 (git 제외, 아래 참고)
```

규칙: **programs는 core를 가져다 쓰고, core는 programs를 모른다.**

모든 명령은 저장소 루트에서 실행한다.

## 사용 모델

**모델을 바꾸면 이 표부터 고친다.** (마지막 수정: 2026-11-24)

| 용도 | 모델 | 어디서 정하나 | 비고 |
|---|---|---|---|
| 에세이 첨삭·채점 (API `/essay`, 새벽 2시 배치) | Ollama `qwen3.5:9b-mtp-q4_K_M` (4bit, MTP) | `.env` `DEFAULT_MODEL` | temperature 0, seed 0, thinking 끔, `NUM_CTX` 16384 |
| 문법 교정 `/grammar`, 대화 `/chat` | 위와 같음 | `.env` `DEFAULT_MODEL` | 요청에 `model`을 넣으면 그 모델 사용 |
| 포트폴리오 받아쓰기 (STT) | faster-whisper `large-v3` | `.env` `STT_MODEL` (기본 large-v3), `STT_DEVICE` (기본 cuda) | 첫 요청 때 불러옴 |

- `.env`에 `DEFAULT_MODEL`이 없으면 코드 기본값 `qwen3.5:9b`(MTP 없는 버전)를 쓴다 (`core/llm.py`).
- 이 서버에 받아 둔 Ollama 모델: `qwen3.5:9b-mtp-q4_K_M` (사용 중), `qwen3.5:9b` (미사용, 비교용)
- 실험 중 (서비스에 안 씀): 에세이 파인튜닝. 원본 `Qwen/Qwen3.5-9B`를 8bit로 올려 LoRA 학습
  (`scripts/train_essay_lora.py`, 결과는 `models/`, git 제외). 1,200편 평가에서 지금 모델보다 나을 때만 교체한다.

## AI 서버

- 실행: `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000` (운영은 `ai-server.service`로 systemd 등록)
- 설정: `.env`에 `OLLAMA_URL`, `DEFAULT_MODEL`, `API_KEYS` (저장소에는 올리지 않음)
- 모든 API는 `X-API-Key` 헤더 필요 (`/health` 제외)

| 엔드포인트 | 설명 |
|---|---|
| `POST /essay` | 에세이 첨삭(틀린 것만 고침) + 채점(Grammar 5 / Structure 5 / Content 10) + 아이용 HTML |
| `POST /grammar` | 영어 문법 교정 + 고친 이유 |
| `POST /chat`, `POST /chat/stream` | 일반 대화 (대화 기록, 스트리밍) |
| `POST /portfolio` | 포트폴리오 영상(대본 읽기) 채점: 점수(정확도 60 / 유창성 25 / 명확도 15) + 다른 곳 목록 + 리포트 .md |
| `GET /portfolio/scripts` | 서버에 저장된 대본 이름 목록 |

`/portfolio` (multipart/form-data)
- `file`: 녹음/영상 (mp4, m4a, wav 등, 기본 최대 300MB: `PORTFOLIO_MAX_UPLOAD_MB`)
- `script` (대본 전문) 또는 `script_name` (저장된 대본 이름, 예: `hercules`) 중 하나
- `names`: 정확도에서 뺄 이름, 쉼표로 (선택)
- STT 라이브러리(`core/stt/requirements.txt`)가 있어야 한다. 없으면 503, 다른 API는 그대로 동작
- whisper 모델은 첫 요청 때 불러온다 (`STT_MODEL` 기본 large-v3, `STT_DEVICE` 기본 cuda). 채점은 한 번에 하나씩

```
curl -H "X-API-Key: $KEY" -F file=@kid.mp4 -F script_name=hercules http://localhost:8000/portfolio
```

에세이 (`programs/essay/`)
- 흐름: `clean.py` 과제 양식 정리 -> `prompt.py` 지시문 (core/grammar/rules.py 포함) -> `grade.py` 모델 호출·점수 -> `render.py` 첨삭 HTML
- 채점 기준·레벨별 학년: `rubric.py`
- 선생님 첨삭 데이터 변환: `scripts/build_teacher_dataset.py`
- 선생님 첨삭과 비교 평가: `scripts/eval_essay.py`

## STT / 포트폴리오 채점

설치: `pip install -r core/stt/requirements.txt` (faster-whisper, GPU용 CUDA 라이브러리)

```
# 받아쓰기만 (.txt / .review.txt / .srt)
.venv/Scripts/python -m core.stt.transcribe "data/stt/audio/Hercules"

# 포트폴리오 채점 (대본과 비교 -> 아이별 리포트 .md + 반 전체 scores.csv)
.venv/Scripts/python -m programs.portfolio.cli "data/stt/audio/Hercules" \
    --script programs/portfolio/scripts/hercules.txt --out "data/stt/reports/Hercules"
```

포트폴리오 (`programs/portfolio/`)
- 흐름: `align.py` 받아 적고 대본과 맞춰 보기 -> `check.py` 다른 곳이 아이 실수인지 모델 오인식인지 판정 -> `score.py` 점수 -> `report.py` 리포트
- `grade.py`: 녹음 한 개 채점 (위 흐름을 순서대로 부름), `cli.py`: 폴더째 실행
- 대본: `scripts/` (hercules.txt 등)

## 데이터 (git 제외)

아이들 글·음성이 들어간 파일은 전부 `data/` 아래에 둔다. 저장소에는 올리지 않는다.

```
data/
  essay/            선생님 첨삭 원본 JSON (예: essay_topic_100.json)
    processed/      build_teacher_dataset.py 결과, eval_runs/
  stt/
    audio/          녹음 파일
    reports/        포트폴리오 채점 결과 (기본 저장 위치)
    outputs/        받아쓰기 결과 (기본 저장 위치)
```
