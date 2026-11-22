"""대본 단어 vs 아이가 읽은(받아 적은) 단어를 맞춰 본다: 맞음 / 빠뜨림 / 다르게 읽음 / 추가로 말함."""
import re
from difflib import SequenceMatcher

from core.stt.engine import boost_quiet, is_hallucination, undo_loops

NUMBERS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten", "11": "eleven",
    "12": "twelve", "13": "thirteen", "14": "fourteen", "15": "fifteen", "20": "twenty",
}


def norm(word):
    w = re.sub(r"[^a-z0-9']", "", word.lower().replace("’", "'"))
    return NUMBERS.get(w, w)


def script_words(text, extra_names=()):
    words = []
    for line_no, line in enumerate(text.splitlines()):
        for raw in line.split():
            n = norm(raw)
            if n:
                words.append({"text": raw, "norm": n, "line": line_no})

    # Names (Philoctetes, Pegasus, Dario...) are often mis-heard even when read well,
    # so they are left out of the accuracy score. A capitalised word in mid-sentence is a name;
    # every other occurrence of it counts too.
    names = {norm(x) for x in extra_names}
    for prev, w in zip(words, words[1:]):
        if (w["text"][0].isupper() and w["norm"] not in {"i", "i'm", "i'll", "i've", "i'd"}
                and prev["line"] == w["line"] and not prev["text"].endswith((".", "!", "?", ":"))):
            names.add(w["norm"])
    for w in words:
        w["name"] = w["norm"] in names
    return words


def transcribe_words(model, raw, no_boost=False, drop_p=0.3):
    """Transcribe without hints (what the child actually said), as normalized words."""
    opts = dict(language="en", beam_size=5, condition_on_previous_text=False,
                temperature=0.0, word_timestamps=True)
    if no_boost:
        segments, _ = model.transcribe(raw, vad_filter=True, **opts)
    else:
        segments, _ = model.transcribe(boost_quiet(raw), vad_filter=True, **opts)
        segments = undo_loops(model, segments, raw, **opts)
    words = []
    for seg in segments:
        if is_hallucination(seg.words, drop_p):
            continue
        for w in seg.words:
            n = norm(w.word)
            if n:
                words.append({"text": w.word.strip(), "norm": n, "start": w.start, "end": w.end,
                              "p": w.probability})
    return words


def compare(ref, hyp):
    """Yield (op, ref_slice, hyp_slice) word-level diff."""
    sm = SequenceMatcher(None, [w["norm"] for w in ref], [w["norm"] for w in hyp], autojunk=False)
    ops = [list(o) for o in sm.get_opcodes()]

    # Merge mismatches split by a single coincidentally matching word
    # ("the end OF the decade" vs "a little bit, a small group OF").
    merged = []
    for o in ops:
        if (merged and o[0] != "equal" and len(merged) >= 2 and merged[-1][0] == "equal"
                and merged[-1][2] - merged[-1][1] == 1 and merged[-2][0] != "equal"):
            eq = merged.pop()
            prev = merged.pop()
            o = ["replace", prev[1], o[2], prev[3], o[4]]
            del eq
        merged.append(o)

    for op, i1, i2, j1, j2 in merged:
        if op != "equal" and "".join(w["norm"] for w in ref[i1:i2]) == "".join(
            w["norm"] for w in hyp[j1:j2]
        ):
            op = "equal"  # e.g. "cyberattacks" vs "cyber attacks"
        if op != "equal" and i2 > i1 and j2 > j1:
            op = "replace"
        yield op, (i1, i2), (j1, j2)


def phrase(words, a, b):
    return " ".join(w["text"] for w in words[a:b])
