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
  debate/             디베이트 영상 -> 아이별 발언 기록 (개발 중, 아래 "디베이트" 참고)
scripts/              개발용 스크립트 (선생님 데이터 변환, 에세이 평가)
data/                 아이들 데이터 (git 제외, 아래 참고)
```

규칙: **programs는 core를 가져다 쓰고, core는 programs를 모른다.**

모든 명령은 저장소 루트에서 실행한다.

## 사용 모델

**모델을 바꾸면 이 표부터 고친다.** (마지막 수정: 2026-11-26)

| 용도 | 모델 | 어디서 정하나 | 비고 |
|---|---|---|---|
| 에세이 첨삭·채점 (API `/essay`, 새벽 2시 배치) | Ollama `qwen3.5:9b-mtp-q4_K_M` (4bit, MTP) | `.env` `DEFAULT_MODEL` | temperature 0, seed 0, thinking 끔, `NUM_CTX` 16384. 한 편에 호출 2번: 첨삭·채점 → 개선 제안 (2026-11-26부터) |
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
- `clean.py`: Topic 줄·과제 안내문·빈칸 밑줄은 지우고, 단락 제목(Intro / Body 1 / Conclusion)은 남긴다 (2026-11-26)
- 개선 제안은 첨삭이 끝난 뒤 따로 호출해서 만든다 (`prompt.py` `build_suggestion_messages`): 고친 글·점수·'이미 한 것'을 보고 실제 실수를 짚는다.
  블라인드 40편 비교 분리 18 : 기존 7 (비슷 15). 350편 배치에 약 5분 더 걸린다. 첨삭 호출 프롬프트는 그대로 둔다
- `suggest_guard.py`: 글이 이미 잘한 것(연결어 3개 이상, 예시, 결론, First, 뒤 쉼표)을 하라는 개선 제안과 "however" 예시를 지운다.
  2026-11-26 배치에서 88%에 같은 연결어 제안이 붙던 문제. 제안 프롬프트를 고쳐 보니 첨삭까지 바뀌고 오류를 놓쳐서
  (블라인드 비교 지금 38 : 새 17) 프롬프트는 그대로 두고 코드로만 거른다
- 채점 기준·레벨별 학년: `rubric.py`
- 선생님 첨삭 데이터 변환: `scripts/build_teacher_dataset.py`
- 선생님 첨삭과 비교 평가: `scripts/eval_essay.py`
- 배치 결과 꺼내기 (읽기만): `.venv/bin/python scripts/essay_export.py [--date YYYY-MM-DD]` -> `data/essay/exports/<날짜>.html` (원문 / AI 첨삭 카드, 브라우저로 열기)

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

**디베이트는 첨삭하지 않고 채점만 한다.** 아이별 Logic 50 / Delivery 25 / Role 25.
받아쓰기는 말한 내용과 논리를 알아보는 용도라, 받아쓰기 모델이 아이의 문법 실수를 고쳐 적어도 괜찮다.
중요한 건 핵심 단어(근거, 고유명사, 찬반, 역할 이름)를 맞게 받아쓰는 것이다.

영상 규칙
- 발언 순서는 항상 **찬성 → 반대 → 찬성 → …** 번갈아. 아이 한 명이 한 번씩 발언한다.
- 인원은 정해져 있지 않다 (2명, 5명, 8명 …). 홀수일 수도 있다.
- 한 영상이 **여러 팀 합본**일 수 있다. 같은 반은 주제가 같아 내용으로 팀 경계를 찾을 수 없고,
  영상은 발언마다 따로 찍은 클립을 이어 붙여서 화면 전환으로도 팀 경계를 알 수 없다.
- 그래서 관리화면에서 **팀별 인원**을 받는다 (예: `[6, 5]`). 총 인원만으로는 뒤 팀 찬/반이 뒤집힐 수 있다.
- 아이 이름은 쓰지 않고 팀마다 1번, 2번 …으로 부른다.

발언 기록 만들기 (`programs/debate/`)
```
.venv-debate/bin/python -m programs.debate.cli "data/debate/video/영상.mp4" --teams 6,5
.venv-debate/bin/python -m programs.debate.cli "https://.../영상.mp4" --teams 4   # URL이면 data/debate/video/로 받음
```
- 결과: `data/debate/outputs/<영상 이름>/transcript.md` (선생님이 읽는 기록, `[단어?]` = 확실하지 않음),
  `transcript.json` (단어별 시각, 화자 분리 원본 포함). 화면에는 시간·번호·찬반만 찍는다
- 흐름: `media.py` 다운로드·음성 추출(PyAV 16kHz)·화면 전환 찾기 -> `diarize.py` 화자 분리(팀별 인원 합계를 화자 수로 넘김)
  -> `transcript.py` 받아쓰기(whisper, core/stt/engine.py) -> 단어마다 화자 붙이기 -> 팀별로 자르고 번호·찬반
- 단어에 화자 붙이기: 겹치는 화자 구간 → 화자 구간 밖의 말(작게 시작한 말)은 화면 전환이 있으면 거기서 나누고
  없으면 다음 화자에게 → 화자가 바뀌는 곳 3초 안에 화면 전환이 있으면 그 지점으로 옮김
  → 화자가 바뀌기 4초 안에 "Hello"가 있으면 거기서부터 다음 화자 (발언은 모두 "Hello everyone"으로 시작)
- "확인 필요": 찾은 화자 수 ≠ 입력 인원, 5초 미만만 말한 화자, 한 화자가 여러 번 나뉘어 나옴 (두 아이가 합쳐졌을 수 있음)

첫 시험 (2026-11-25, 14분 43초 합본 영상, 팀 6명 + 5명)
- 인원을 알려 주지 않고도 화자 11명을 정확히 찾음. GPU에서 18초
- 틀린 곳: 2번 시작이 8초 늦게 잡힘 (작게 시작한 말을 놓침). whisper는 그 말을 잡았고, 화면 전환(1:34.6)도 실제 시작과 맞음
- 발언 기록까지 전체 1분 정도 (화자 분리 21초, 받아쓰기 33초). 위 보정으로 2번 시작이 1:35로 맞게 나옴
- 받아쓰기 불확실 단어: 2팀 2~4%, 1팀 7~15% (1팀 녹음 소리가 작음)

토론 자료 (`data/debate/topics/`, 학원 교재라 git 제외)
- 찬성·반대 주장/근거/증거 자료. 아이들은 이걸 **그대로 읽지 않고 자기 말로** 발언한다
  (첫 시험에서 아이별 받아쓰기와 자료 단락의 세 단어 연속 일치가 0~27%)
- 그래서 포트폴리오처럼 대본과 맞춰 보는 채점은 안 된다. 나중에 내용 평가(근거를 맞게 썼는지)에 쓴다
- whisper 힌트(hotwords)로 넣어 봤지만 쓰지 않는다: 자료 단어 55개, 고유명사 11개 둘 다
  불확실 단어가 늘고 발언 일부(최대 65단어)가 통째로 빠졌다. 맞힌 고유명사는 1~3개뿐

설치 (서비스용 `.venv`와 따로 둔다)
```
python3 -m venv .venv-debate
.venv-debate/bin/pip install pyannote.audio==4.1.1 faster-whisper==1.2.1 python-dotenv nvidia-cublas-cu12
```
- whisper(ctranslate2)는 CUDA 12 cuBLAS가 필요해서 `nvidia-cublas-cu12`를 따로 넣는다. cuDNN은 torch가 가져온
  `nvidia-cudnn-cu13`을 같이 쓴다. **`nvidia-cudnn-cu12`는 설치하지 않는다** (같은 폴더에 덮어써서 torch 쪽 cuDNN이 바뀜)
- 리눅스에서는 `core/stt/engine.py`가 이 라이브러리들을 직접 불러 와서 `LD_LIBRARY_PATH`가 필요 없다
- PyAV는 최신(19)을 쓴다. faster-whisper의 `decode_audio`는 PyAV 16+에서 깨지므로 음성은 `programs/debate/media.py`로 꺼낸다
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
    outputs/        발언 기록 (영상마다 폴더: transcript.md, transcript.json)
    topics/         토론 자료 (주제별 .txt)
```
