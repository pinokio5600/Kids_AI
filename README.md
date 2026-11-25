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
  debate/             디베이트 영상 분석 (개발 중, 아래 "디베이트" 참고)
scripts/              개발용 스크립트 (선생님 데이터 변환, 에세이 평가)
data/                 아이들 데이터 (git 제외, 아래 참고)
```

규칙: **programs는 core를 가져다 쓰고, core는 programs를 모른다.**

모든 명령은 저장소 루트에서 실행한다.

## 사용 모델

**모델을 바꾸면 이 표부터 고친다.** (마지막 수정: 2026-11-25)

| 용도 | 모델 | 어디서 정하나 | 비고 |
|---|---|---|---|
| 에세이 첨삭·채점 (API `/essay`, 새벽 2시 배치) | Ollama `qwen3.5:9b-mtp-q4_K_M` (4bit, MTP) | `.env` `DEFAULT_MODEL` | temperature 0, seed 0, thinking 끔, `NUM_CTX` 16384 |
| 문법 교정 `/grammar`, 대화 `/chat` | 위와 같음 | `.env` `DEFAULT_MODEL` | 요청에 `model`을 넣으면 그 모델 사용 |
| 포트폴리오 받아쓰기 (STT) | faster-whisper `large-v3` | `.env` `STT_MODEL` (기본 large-v3), `STT_DEVICE` (기본 cuda) | 첫 요청 때 불러옴 |
| 디베이트 화자 분리 (개발 중) | pyannote.audio 4.1.1 `pyannote/speaker-diarization-community-1` | 코드 | `.venv-debate`, 처음 한 번 `.env` `HF_TOKEN`으로 받음. 이후 서버 캐시에서 실행 |
| 디베이트 받아쓰기 (개발 중) | faster-whisper `large-v3` | 코드 | `.venv-debate` |

- `.env`에 `DEFAULT_MODEL`이 없어도 같은 모델을 쓴다 (코드 기본값, `core/llm.py`).
- 이 서버에 받아 둔 Ollama 모델: `qwen3.5:9b-mtp-q4_K_M` (사용 중) 하나. 예전 비교용 `qwen3.5:9b`는 2026-11-25 삭제
- 2026-11-24 파인튜닝(Qwen3.5-9B 8bit LoRA)을 두 번 시도했지만 지금 모델보다 낫지 않아 쓰지 않았고, 실험 파일은 모두 지웠다.

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

## 디베이트 (개발 중)

한 영상에 여러 아이가 순서대로 발언한 디베이트 영상을 아이별로 나눠 분석한다.

영상 규칙
- 발언 순서는 항상 **찬성 → 반대 → 찬성 → …** 번갈아. 아이 한 명이 한 번씩 발언한다.
- 인원은 정해져 있지 않다 (2명, 5명, 8명 …). 홀수일 수도 있다.
- 한 영상이 **여러 팀 합본**일 수 있다. 같은 반은 주제가 같아 내용으로 팀 경계를 찾을 수 없고,
  영상은 발언마다 따로 찍은 클립을 이어 붙여서 화면 전환으로도 팀 경계를 알 수 없다.
- 그래서 관리화면에서 **팀별 인원**을 받는다 (예: `[6, 5]`). 총 인원만으로는 뒤 팀 찬/반이 뒤집힐 수 있다.
- 아이 이름은 쓰지 않고 팀마다 1번, 2번 …으로 부른다.

처리 흐름 (계획)
1. 영상 URL → 서버로 다운로드 (`data/debate/video/`) → 음성 추출 (PyAV, 16kHz mono)
2. 화자 분리 (pyannote). 팀별 인원 합계를 `num_speakers`로 넘긴다
3. 화면 전환 지점으로 발언 시작 시각 보정 (클립 경계 = 발언 경계인 경우가 많다)
4. 받아쓰기 (whisper). 화자가 안 붙은 말은 바로 다음 화자에게 붙인다
5. 처음 말한 순서대로 팀별 인원만큼 자르고, 팀마다 홀수 번 = 찬성, 짝수 번 = 반대
6. 찾은 화자 수 ≠ 인원 합계, 또는 찬/반 번갈이가 깨지면 "확인 필요"

첫 시험 (2026-11-25, 14분 43초 합본 영상, 팀 6명 + 5명)
- 인원을 알려 주지 않고도 화자 11명을 정확히 찾음. GPU에서 18초
- 틀린 곳: 2번 시작이 8초 늦게 잡힘 (작게 시작한 말을 놓침). whisper는 그 말을 잡았고, 화면 전환(1:34.6)도 실제 시작과 맞음

설치 (서비스용 `.venv`와 따로 둔다)
```
python3 -m venv .venv-debate
.venv-debate/bin/pip install pyannote.audio==4.1.1 faster-whisper==1.2.1 python-dotenv \
    nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```
- whisper는 pip로 받은 CUDA 12 라이브러리를 써서 `LD_LIBRARY_PATH`에
  `.venv-debate/lib/python3.14/site-packages/nvidia/{cublas,cudnn}/lib`를 넣어야 한다
- pyannote 모델은 HuggingFace 약관 동의가 필요하다: `pyannote/speaker-diarization-community-1`,
  `pyannote/speaker-diarization-3.1`, `pyannote/segmentation-3.0`. 읽기 전용 토큰을 `.env` `HF_TOKEN`에 넣고
  처음 한 번 받으면 `~/.cache/huggingface`에 남는다. 이후에는 `HF_HUB_OFFLINE=1`로 돌릴 수 있다
- 유료 pyannoteAI(클라우드 API)는 음성을 밖으로 보내므로 쓰지 않는다

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
  debate/
    video/          디베이트 영상 (학원 서버에서 받은 것)
```
