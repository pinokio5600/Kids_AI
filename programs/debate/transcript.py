"""디베이트 발언 기록: 영상을 발언(아이 한 명)마다 나누고, 발언마다 받아써서 팀·번호·찬반별로 정리한다.

규칙 (README "디베이트")
- 팀마다 찬성 -> 반대 -> 찬성 ... 번갈아, 아이 한 명이 한 번씩 순서대로 발언
- 발언 수 = 팀별 인원의 합. 영상을 그만큼의 이어진 구간으로 나누고, 팀마다 1번부터 센다
- 홀수 번 = 찬성, 짝수 번 = 반대

나누는 방법 (2026-11-26): 화자 분리 라벨을 아이로 보지 않는다. 화자 분리는 한 아이를 둘로 쪼개거나
소리가 작은 아이를 놓치는데, 그러면 뒤의 번호·찬반이 다 밀린다. 대신 경계 후보(화면 전환, "Hello" 인사,
화자가 바뀌는 곳, 쉬는 틈)에 점수를 주고, 한 구간 안에 여러 화자가 섞이면 깎아서
정해진 발언 수로 가장 잘 나누는 방법을 고른다(동적 계획법).

선생님 목소리 (2026-11-26): 진행·질문하는 선생님이 들어간 영상이 있다. 어느 발언의 주인도 아니면서
여러 발언에 걸쳐 나오는 목소리를 선생님으로 보고, 그 목소리를 빼고 다시 나눈 뒤(선생님 말이 끝난 곳도 경계 후보)
선생님 말은 발언 기록에서 뺀다.
"""
from core.stt.engine import boost_quiet, is_hallucination, undo_loops

GREETINGS = {"hello", "hi"}
MERGE = 3.0            # seconds; boundary hints this close together are one boundary
CUT_CLUSTER = 2.0      # a fade gives several picture cuts in a row
BONUS = {"cut": 30, "greet": 30, "host": 20, "spk": 10, "gap": 5}
MIXED_PENALTY = 0.3    # per second of speech that isn't the segment's main speaker
MIN_SPEECH = 25.0      # seconds; a shorter speech costs SHORT_PENALTY
SHORT_PENALTY = 50
# a speech whose transcript can't be trusted (quiet recording): don't score it
MIN_WPM = 60           # children speak about 90-140 words a minute
MAX_UNSURE = 0.30
HOLE = 6.0             # seconds without a word inside a speech: transcribed again on its own
# A hole still empty after that is only reported, not a reason to hold the score: it can be a quiet child
# whisper can't hear, or a silent minute to prepare a rebuttal - neither loudness nor diarization tells them apart.
HOST_MIN_SPEECHES = 3  # a voice heard in this many speeches it doesn't own = the teacher


def transcribe_words(model, audio, drop_p=0.3, offset=0.0):
    """-> [{start, end, word, p}]. Same settings as portfolio: raise quiet parts, drop invented text.
    No topic hints (hotwords): tried on 2026-11-25, they made more words unsure and dropped whole
    stretches of speech, while fixing only a few names."""
    opts = dict(language="en", beam_size=5, condition_on_previous_text=False,
                temperature=0.0, word_timestamps=True)
    segments, _ = model.transcribe(boost_quiet(audio), vad_filter=True, **opts)
    words = []
    for seg in undo_loops(model, segments, audio, **opts):
        if is_hallucination(seg.words, drop_p):
            continue
        for w in seg.words or []:
            words.append({"start": round(float(w.start) + offset, 2), "end": round(float(w.end) + offset, 2),
                          "word": w.word.strip(), "p": round(float(w.probability), 2)})
    return words


def _norm(w):
    return w.strip(".,!?\"' -").lower()


def _candidates(words, turns, cuts, host=None):
    """Possible speech boundaries -> [{t, kinds}]. Hints within MERGE seconds are merged;
    the time is the greeting if there is one, else the picture cut, else the first hint."""
    hints = []
    cluster = []
    for t in sorted(cuts):
        if cluster and t - cluster[-1][-1] <= CUT_CLUSTER:
            cluster[-1].append(t)
        else:
            cluster.append([t])
    hints += [(g[-1], "cut") for g in cluster]
    for i, w in enumerate(words):
        n = _norm(w["word"])
        prev = words[i - 1] if i else None
        if n in GREETINGS:
            hints.append((w["start"], "greet"))
        elif n == "everyone" and (prev is None or (_norm(prev["word"]) not in GREETINGS
                                                    and w["start"] - prev["end"] > 0.8)):
            hints.append((w["start"], "greet"))  # "Hello" itself was too soft to catch
    if host:
        # a child starts after the teacher hands over ("...you have the floor")
        ends = [b for (_, b, k), nxt in zip(turns, turns[1:] + [None]) if k == host and (nxt is None or nxt[2] != host)]
        hints += [(t, "host") for t in ends]
        turns = [x for x in turns if x[2] != host]
    for (_, b, k), (a2, _, k2) in zip(turns, turns[1:]):
        if k != k2:
            hints.append(((b + a2) / 2, "spk"))
    for w1, w2 in zip(words, words[1:]):
        if w2["start"] - w1["end"] >= 1.5:
            hints.append(((w1["end"] + w2["start"]) / 2, "gap"))

    out = []
    for t, kind in sorted(hints):
        if out and t - out[-1]["first"] <= MERGE:
            c = out[-1]
            c["kinds"].add(kind)
            if kind == "greet" or (kind == "cut" and "greet" not in c["kinds"]):
                c["t"] = t
        else:
            out.append({"t": t, "first": t, "kinds": {kind}})
    return out


def split_speeches(words, turns, cuts, n, duration, host=None):
    """Cut the video into n speeches in a row -> [{start, end, hints}].
    hints = what marked the start of the speech (cut / greet / host / spk / gap), empty for the first.
    host = the teacher's diarization label: left out when judging if a speech mixes voices."""
    cands = [{"t": 0.0, "kinds": set()}] + _candidates(words, turns, cuts, host) + [{"t": duration, "kinds": set()}]
    turns = [x for x in turns if x[2] != host]
    cands = [c for c in cands if 0.0 <= c["t"] <= duration]
    times = [c["t"] for c in cands]
    m = len(cands)
    n = max(1, min(n, m - 1))

    def mixed(a, b):
        per = {}
        for s, e, k in turns:
            if s >= b:
                break
            o = min(e, b) - max(s, a)
            if o > 0:
                per[k] = per.get(k, 0.0) + o
        return sum(per.values()) - max(per.values()) if per else 0.0

    cost = {}
    for j in range(1, m):
        for i in range(j):
            length = times[j] - times[i]
            if length >= 1.0:
                cost[i, j] = MIXED_PENALTY * mixed(times[i], times[j]) + (SHORT_PENALTY if length < MIN_SPEECH else 0)
    gain = [sum(BONUS[k] for k in c["kinds"]) for c in cands]
    gain[-1] = 0

    NEG = float("-inf")
    best = [[NEG] * m for _ in range(n + 1)]
    back = [[None] * m for _ in range(n + 1)]
    best[0][0] = 0.0
    for s in range(1, n + 1):
        for j in range(1, m):
            for i in range(j):
                if best[s - 1][i] == NEG or (i, j) not in cost:
                    continue
                v = best[s - 1][i] - cost[i, j] + gain[j]
                if v > best[s][j]:
                    best[s][j], back[s][j] = v, i
    if best[n][m - 1] == NEG:
        raise ValueError(f"영상을 발언 {n}개로 나눌 수 없음")
    j, out = m - 1, []
    for s in range(n, 0, -1):
        i = back[s][j]
        out.append({"start": round(times[i], 2), "end": round(times[j], 2), "hints": sorted(cands[i]["kinds"])})
        j = i
    return out[::-1]


def _voices(turns, a, b):
    per = {}
    for s, e, k in turns:
        o = min(e, b) - max(s, a)
        if o > 0:
            per[k] = per.get(k, 0.0) + o
    return per


def find_host(turns, speeches, min_secs=1.0):
    """The teacher's label, or None: the voice heard (min_secs or more) in the most speeches
    it doesn't own, if that is HOST_MIN_SPEECHES or more. (A child asks a question in one or two
    others at most.) Not "owns no speech": with one child too many in team_sizes, a forced extra
    speech can be mostly the teacher."""
    guest = {}
    for sp in speeches:
        per = _voices(turns, sp["start"], sp["end"])
        main = max(per, key=per.get) if per else None
        for k, v in per.items():
            if k != main and v >= min_secs:
                guest[k] = guest.get(k, 0) + 1
    if not guest:
        return None
    k = max(guest, key=guest.get)
    return k if guest[k] >= HOST_MIN_SPEECHES else None


def drop_host_words(words, turns, host):
    """Words mostly inside the teacher's turns -> left out of the children's speeches."""
    if not host:
        return words, []
    ht = [(s, e) for s, e, k in turns if k == host]
    keep, drop = [], []
    for w in words:
        d = max(w["end"] - w["start"], 0.01)
        o = sum(max(0.0, min(e, w["end"]) - max(s, w["start"])) for s, e in ht)
        (drop if o / d > 0.5 else keep).append(w)
    return keep, drop


def _text(words, flag_p=None):
    if flag_p is None:
        return " ".join(w["word"] for w in words)
    return " ".join(f"[{w['word']}?]" if w["p"] < flag_p else w["word"] for w in words)


def build(speeches, team_sizes=None, flag_p=0.5):
    """speeches: [{start, end, hints, words}] in order -> {"teams": [...], "checks": [...]}.
    team_sizes e.g. [6, 5]; None = one team of everyone."""
    checks, speakers = [], []
    for i, sp in enumerate(speeches):
        ws = sp["words"]
        secs = sp["end"] - sp["start"]
        unsure = sum(w["p"] < flag_p for w in ws)
        wpm = len(ws) / secs * 60 if secs > 0 else 0.0
        s = {"start": sp["start"], "end": sp["end"], "seconds": round(secs, 1), "words": len(ws),
             "unsure": int(unsure), "wpm": round(wpm), "boundary": sp["hints"],
             "text": _text(ws), "review_text": _text(ws, flag_p), "unreliable": None}
        s["missing"] = sp.get("missing", 0.0)
        if wpm < MIN_WPM:
            s["unreliable"] = f"{secs:.0f}초 동안 {len(ws)}단어만 받아씀"
        elif ws and unsure / len(ws) > MAX_UNSURE:
            s["unreliable"] = f"불확실한 단어 {unsure / len(ws):.0%}"
        speakers.append(s)
        if i and not ({"cut", "greet"} & set(sp["hints"])):
            checks.append(f"{_ts(sp['start'])} 발언 경계: 화면 전환이나 인사 없이 정함")

    sizes = list(team_sizes) if team_sizes else [len(speakers)]
    teams, pos = [], 0
    for t, size in enumerate(sizes, 1):
        members = speakers[pos:pos + size]
        pos += size
        for n, s in enumerate(members, 1):
            s["team"], s["no"] = t, n
            s["role"] = "찬성" if n % 2 == 1 else "반대"
            if s["unreliable"]:
                checks.append(f"{t}팀 {n}번 ({_ts(s['start'])}) 녹음 불량 의심, 채점 보류: {s['unreliable']}")
            elif s["missing"] >= 10:
                checks.append(f"{t}팀 {n}번 ({_ts(s['start'])}) {s['missing']:.0f}초 동안 받아쓴 말이 없음 "
                              f"(준비 시간인지, 작게 말해 못 들은 건지 확인)")
        teams.append({"team": t, "size": size, "speakers": members})
    return {"teams": teams, "checks": checks}


def _ts(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def render_md(result, title):
    """Transcript for a teacher to read: team -> number (찬/반) -> time -> text. [word?] = unsure."""
    out = [f"# {title} 발언 기록", ""]
    if result["checks"]:
        out += ["## 확인 필요", ""] + [f"- {c}" for c in result["checks"]] + [""]
    for team in result["teams"]:
        out.append(f"## {team['team']}팀")
        out.append("")
        for s in team["speakers"]:
            note = " — 녹음 불량 의심, 채점 보류" if s["unreliable"] else ""
            out.append(f"### {s['no']}번 {s['role']} ({_ts(s['start'])} ~ {_ts(s['end'])}, {s['seconds']:.0f}초){note}")
            out += ["", s["review_text"], ""]
    out.append("`[단어?]`: 받아쓰기가 확실하지 않은 곳")
    return "\n".join(out) + "\n"
