"""디베이트 발언 기록: 받아쓰기(whisper) + 화자 분리 결과를 합쳐 팀·번호·찬반별로 나눈다.

규칙 (README "디베이트")
- 팀마다 찬성 -> 반대 -> 찬성 ... 번갈아, 아이 한 명이 한 번씩 발언
- 처음 말한 순서대로 번호를 붙이고, 팀별 인원(team_sizes)만큼 잘라 팀마다 1번부터 다시 센다
- 홀수 번 = 찬성, 짝수 번 = 반대
"""
from core.stt.engine import boost_quiet, is_hallucination, undo_loops

CUT_SNAP = 3.0       # a picture cut this close to a speaker change is taken as the real change
SHORT_SPEECH = 5.0   # seconds; a "speaker" with less than this is probably noise or a teacher's word
GREETINGS = {"hello", "hi"}
GREETING_WINDOW = 4.0  # seconds before a speaker change to look for the next child's greeting


def transcribe_words(model, audio, drop_p=0.3):
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
            words.append({"start": round(float(w.start), 2), "end": round(float(w.end), 2),
                          "word": w.word.strip(), "p": round(float(w.probability), 2)})
    return words


def assign_speakers(words, turns, cuts):
    """Give each word one speaker.
    1. the diarization turn it overlaps most
    2. words no turn covers (quiet starts pyannote misses): between two different speakers,
       split at a picture cut if there is one, otherwise give them to the next speaker
    3. a picture cut close to a speaker change moves the change onto the cut
    4. a greeting ("Hello") just before a change goes to the next speaker"""
    spk = []
    for w in words:
        best, best_ov = None, 0.0
        for a, b, k in turns:
            if a >= w["end"]:
                break
            ov = min(b, w["end"]) - max(a, w["start"])
            if ov > best_ov:
                best, best_ov = k, ov
        spk.append(best)

    def mid(i):
        return (words[i]["start"] + words[i]["end"]) / 2

    i = 0
    while i < len(words):
        if spk[i] is not None:
            i += 1
            continue
        j = i
        while j < len(words) and spk[j] is None:
            j += 1
        prev = spk[i - 1] if i > 0 else None
        nxt = spk[j] if j < len(words) else None
        if prev is None or nxt is None or prev == nxt:
            for x in range(i, j):
                spk[x] = prev or nxt
        else:
            lo = words[i - 1]["end"]
            hi = words[j]["start"]
            inside = [c for c in cuts if lo <= c <= hi]
            split = inside[-1] if inside else lo
            for x in range(i, j):
                spk[x] = prev if mid(x) < split else nxt
        i = j

    for i in range(1, len(words)):
        if spk[i] == spk[i - 1] or spk[i] is None:
            continue
        t = words[i]["start"]
        near = [c for c in cuts if abs(c - t) <= CUT_SNAP]
        if not near:
            continue
        c = min(near, key=lambda c: abs(c - t))
        prev, nxt = spk[i - 1], spk[i]
        # only touch words right around this change
        x = i - 1
        while x >= 0 and spk[x] == prev and mid(x) >= c:
            spk[x] = nxt
            x -= 1
        x = i
        while x < len(words) and spk[x] == nxt and mid(x) < c:
            spk[x] = prev
            x += 1

    # 4. every speech opens with "Hello everyone": a greeting just before a speaker change
    #    belongs to the next speaker (2026-11-26: a "Hello," before a picture cut went to the previous child)
    for i in range(1, len(words)):
        if spk[i] == spk[i - 1] or spk[i] is None:
            continue
        x = i - 1
        while x >= 0 and spk[x] == spk[i - 1] and words[i]["start"] - words[x]["start"] <= GREETING_WINDOW:
            if words[x]["word"].strip(".,!?").lower() in GREETINGS:
                for y in range(x, i):
                    spk[y] = spk[i]
                break
            x -= 1
    return spk


def _blocks(words, spk):
    blocks = []
    for w, k in zip(words, spk):
        if k is None:
            continue
        if blocks and blocks[-1]["label"] == k:
            blocks[-1]["words"].append(w)
        else:
            blocks.append({"label": k, "words": [w]})
    for b in blocks:
        b["start"], b["end"] = b["words"][0]["start"], b["words"][-1]["end"]
    return blocks


def _text(words, flag_p=None):
    if flag_p is None:
        return " ".join(w["word"] for w in words)
    return " ".join(f"[{w['word']}?]" if w["p"] < flag_p else w["word"] for w in words)


def build(words, turns, cuts, team_sizes=None, flag_p=0.5):
    """-> {"teams": [...], "checks": [...]} . team_sizes e.g. [6, 5]; None = one team of everyone."""
    spk = assign_speakers(words, turns, cuts)
    blocks = _blocks(words, spk)

    order, info = [], {}
    for b in blocks:
        k = b["label"]
        if k not in info:
            order.append(k)
            info[k] = {"label": k, "blocks": []}
        info[k]["blocks"].append(b)

    checks = []
    speakers = []
    for k in order:
        bl = info[k]["blocks"]
        ws = [w for b in bl for w in b["words"]]
        secs = sum(b["end"] - b["start"] for b in bl)
        s = {"label": k, "start": bl[0]["start"], "end": bl[-1]["end"], "seconds": round(secs, 1),
             "words": len(ws), "unsure": int(sum(w["p"] < flag_p for w in ws)),
             "text": _text(ws), "review_text": _text(ws, flag_p),
             "blocks": [{"start": b["start"], "end": b["end"], "text": _text(b["words"])} for b in bl]}
        speakers.append(s)
        if secs < SHORT_SPEECH:
            checks.append(f"{_ts(s['start'])} 화자가 {secs:.0f}초만 말함 (잡음이나 선생님 말일 수 있음)")
        long_parts = [b for b in bl if b["end"] - b["start"] >= SHORT_SPEECH]
        if len(long_parts) > 1:
            checks.append(f"{_ts(s['start'])}에 처음 말한 화자가 {len(long_parts)}번 나뉘어 나옴 "
                          f"({', '.join(_ts(b['start']) for b in long_parts)}). 두 아이가 합쳐졌을 수 있음")

    sizes = list(team_sizes) if team_sizes else [len(speakers)]
    if sum(sizes) != len(speakers):
        checks.append(f"찾은 화자 {len(speakers)}명 ≠ 입력 인원 {sum(sizes)}명 ({'+'.join(map(str, sizes))})")

    teams, pos = [], 0
    for t, size in enumerate(sizes, 1):
        members = speakers[pos:pos + size]
        pos += size
        for n, s in enumerate(members, 1):
            s["team"], s["no"] = t, n
            s["role"] = "찬성" if n % 2 == 1 else "반대"
        teams.append({"team": t, "size": size, "speakers": members})
    if pos < len(speakers):
        teams.append({"team": None, "size": 0, "speakers": speakers[pos:]})  # left over, not numbered
    return {"teams": teams, "checks": checks}


def _ts(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def render_md(result, title):
    """Transcript for a teacher to read: team -> number (찬/반) -> time -> text. [word?] = unsure."""
    out = [f"# {title} 발언 기록", ""]
    if result["checks"]:
        out += ["## 확인 필요", ""] + [f"- {c}" for c in result["checks"]] + [""]
    for team in result["teams"]:
        out.append(f"## {team['team']}팀" if team["team"] else "## 팀에 넣지 못한 화자")
        out.append("")
        for s in team["speakers"]:
            head = f"{s['no']}번 {s['role']}" if team["team"] else s["label"]
            out.append(f"### {head} ({_ts(s['start'])} ~ {_ts(s['end'])}, {s['seconds']:.0f}초)")
            out += ["", s["review_text"], ""]
    out.append("`[단어?]`: 받아쓰기가 확실하지 않은 곳")
    return "\n".join(out) + "\n"
