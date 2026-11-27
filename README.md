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

**모델을 바꾸면 이 표부터 고친다.** (마지막 수정: 2026-11-27)

| 용도 | 모델 | 어디서 정하나 | 비고 |
|---|---|---|---|
| 에세이 첨삭·채점 (API `/essay`, 새벽 2시 배치) | Ollama `qwen3.5:9b-mtp-q4_K_M` (4bit, MTP) | `.env` `DEFAULT_MODEL` | temperature 0, seed 0, thinking 끔, `NUM_CTX` 16384. 한 편에 호출 2번: 첨삭·채점 → 개선 제안 (2026-11-26부터). 제안은 '다음 글을 더 잘 쓰는 법' 중심, 프로그램이 센 실수 종류를 넣음 (2026-11-27) |
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
- 개선 제안은 이미 빨간 글씨로 보이는 문법을 되풀이하지 않고 '다음 글을 더 잘 쓰는 법'(이유 설명, 예시, 반론, 구성, 표현)을
  그 글의 내용을 짚어서 알려 준다 (2026-11-27, `prompt.py` `SUGGESTION_ONLY_RULES`). 문법은 같은 실수 3번 이상일 때 1개까지.
  전에는 제안의 70%가 문법·철자였다. 블라인드 40편: 아이에게 더 도움 새 31 : 기존 9, 맞는 제안 84% (기존 39%)
  예시는 실존 인물·사건 대신 상상한 상황·일상 예시로 요구한다 (아이가 지어낼 수 있어서. 블라인드 새 14 : 기존 7, 비슷 19)
  학년별로 다르게 (`prompt.py` `suggestion_level_rules`): 2~3학년 1~2개·10단어 이하·기본기만, 4~5학년 2~3개·15단어,
  6~7학년 2~4개·20단어·반론까지. 블라인드 40편(2~3학년 20편): 새 19 : 기존 15, 엉뚱함 27% -> 21% (2~3학년 23% -> 13%)
- `mistakes.py`: 첨삭 전후를 비교해 실제로 고친 실수 종류(철자, 동사형, 관사 ...)를 세서 제안 호출에 넣는다 (2026-11-27).
  목록에 없는 종류는 말하지 말라고 하니 엉뚱한 제안이 28% -> 14% (블라인드 40편, 제안 320개, 평가자 2명).
  비교한 다른 방법: 제안 호출 thinking 켜기(편당 57초라 배치에 못 씀), 원문 인용 필수(맞는 제안까지 버려져 1/3이 제안 없음)
- `align.py`: 원문·첨삭 토큰 줄 맞춤 (guard·render·grammar 점수 공용). difflib은 첫·마지막 문장이 비슷한 글에서
  순서를 엇갈려 짝지어서 안전장치가 글 전체를 되돌렸다 (2026-11-27). 순서를 지키는 LCS로 맞춘다
- `suggest_guard.py`: 글이 이미 잘한 것(연결어 3개 이상, 예시, 결론, First, 뒤 쉼표)을 하라는 개선 제안과 "however" 예시를 지운다.
  2026-11-27 추가: 대문자 실수 없는 글의 대문자 제안, Therefore/So I think로 끝나는 글의 결론 제안, 단어 하나 고치기 제안
  ("Change 'X' to 'Y'"), 맞게 쓴 단어가 섞인 철자 제안, because 쉼표 조언, 첨삭에 그런 고침이 없는 시제·대문자·철자 제안,
  두 번째부터의 문법 제안. 남기는 제안에서도 'X -> Y' 예시, 철자 단어 목록, 이유 번호("your third point")는 뺀다
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
  -> `transcript.py` 받아쓰기(whisper, core/stt/engine.py) -> 발언 나누기 -> 팀별로 자르고 번호·찬반
- 발언 나누기 (2026-11-26): 화자 분리 라벨을 아이로 보지 않고, 영상을 **팀별 인원 합계만큼의 이어진 구간**으로 나눈다.
  경계 후보에 점수를 준다: 화면 전환 30, "Hello"(또는 "Hello"가 묻힌 "everyone") 인사 30, 화자가 바뀌는 곳 10, 1.5초 이상 쉬는 틈 5.
  한 구간에 다른 화자 말이 섞이면 1초에 0.3, 25초보다 짧은 발언은 50을 깎는다. 이 점수로 가장 잘 나누는 방법을 고른다 (동적 계획법).
  화자 분리가 한 아이를 둘로 쪼개거나 소리 작은 아이를 놓쳐도 번호·찬반이 밀리지 않는다
- 받아쓰기는 영상 전체를 한 번에 하고 경계대로 나눈다. whisper가 소리 작은 곳을 건너뛰면(처음 27초, 한 번은 90초)
  **발언 안에서 6초 이상 단어가 없는 곳만** 앞뒤 1초·5초 여유로 두 번 다시 받아써서 단어가 많은 쪽을 끼워 넣는다.
  소리가 작으면 whisper가 자르는 위치에 따라 크게 흔들려서 여유 하나로는 모든 영상에서 낫지 않았다.
  발언 전체를 다시 받아쓰는 것도 첫 몇 초를 놓치는 등 흔들려서 쓰지 않는다
- 선생님 목소리: 진행·질문하는 선생님이 들어간 영상이 있다. **자기 발언이 아닌 발언 3개 이상에서 들리는 목소리**를
  선생님으로 보고, 그 목소리를 빼고 다시 나눈다(선생님 말이 끝난 곳도 경계 후보 20). 선생님 말은 발언 기록에서 빼고
  json `host`에 따로 둔다. 아이끼리 묻고 답한 질문(POI)은 그대로 둔다
- "확인 필요": 화면 전환이나 인사 없이 정한 경계, 선생님 말을 뺀 것, 10초 이상 받아쓴 말이 없는 곳
  (반박 준비 시간일 수도, 작게 말해 못 들은 것일 수도 있다. 소리 크기와 화자 분리로는 둘을 구분하지 못했다),
  **녹음 불량 의심(채점 보류)**: 분당 60단어 미만이거나 불확실한 단어가 30% 넘는 발언.
  json의 아이별 `unreliable`에 이유가 들어간다. 이런 발언은 어떤 받아쓰기 모델로도 읽을 만한 결과가 안 나왔다
- 입력 인원이 영상 속 아이보다 많으면 한 아이가 억지로 둘로 나뉜다. 그 경계는 보통 "화면 전환이나 인사 없이 정함"으로 나온다

두 번째 시험 (2026-11-26, 16분 합본 영상 `Garam 3M_2`, 팀 5명 + 6명)
- 예전 방식(화자 라벨 = 아이)은 1팀 2번을 두 사람으로 쪼개 뒤 번호·찬반이 밀렸고, 1팀 5번(97초)은 whisper가 거의 통째로 빠뜨려
  2팀 1번에 붙었다. 화면 전환 8곳은 모두 실제 발언 경계와 맞았다
- 새 방식: 두 영상 모두 11명 경계가 정답과 2.5초 안. 첫 영상 발언 기록은 예전과 글자까지 같다.
  두 번째 영상 1팀 4·5번은 소리가 너무 작아 "채점 보류"로 표시된다
- 화면 전환 없이(`--no-cuts`) 나누면 두 번째 영상 1팀이 틀린다 (소리 작은 아이들은 인사도 화자 변화도 잘 안 잡힘)

세 번째 시험 (2026-11-26, 23분 합본 영상 `Garam 3M July_1`, 팀 6명 + 4명 + 4명)
- 14명 경계 모두 화면 전환과 맞고 발언 첫머리도 맞음 (화면 전환 25곳 중 나머지 12곳은 페이드로 겹쳐 잡혔거나 한 발언 안의 전환이라 쓰지 않음)
- 2팀(소리가 작음) 2·4번 채점 보류. 2팀 4번은 중간 42초를 다시 받아써도 whisper가 아무것도 못 냄

네 번째 시험 (2026-11-26, 18분 영상 `BadaT November`, 선생님이 진행·질문, 반박 준비 시간 약 2분)
- 6명이라고 받았지만 영상에는 5명(PM, LO, DPM, DLO, GW)만 나온다. 6으로 넣으면 PM이 둘로 나뉜다
- 5로 넣으면 경계 모두 맞고 선생님 말("you have the floor", 질문, 아이 이름 부르기)은 빠진다. DPM은 소리가 작아 채점 보류

받아쓰기 모델 비교 (2026-11-26, 두 영상 22명, 정답 없이 직접 읽고 비교)
- whisper large-v3 (지금), Qwen3-ASR-1.7B (교재 용어 힌트 있음/없음), NVIDIA Canary-Qwen 2.5B
- 소리가 깨끗한 발언: 셋 다 쓸 만하고 Qwen3-ASR이 고유명사·역할 이름을 가장 잘 잡는다. Canary는 첫머리를 빠뜨리거나 문장부호가 없는 곳이 있다
- 소리가 작은 발언: 모두 실패. Qwen은 찬반을 뒤집거나 지어내고, 힌트를 주면 힌트 목록을 그대로 출력한다. Canary는 같은 말을 수백 번 반복한다
- 그래서 whisper를 유지한다. 효과가 가장 큰 건 녹음(아이 가까이 마이크)이다

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
