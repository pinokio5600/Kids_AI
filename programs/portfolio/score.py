"""포트폴리오 읽기 점수: 정확도 60 + 유창성 25 + 명확도 15 = 100, 등급 A/B/C."""

# Score weights and the ranges that map a measurement to 0..1 of its points.
WEIGHTS = {"accuracy": 60, "fluency": 25, "clarity": 15}
WPM_RANGE = (80, 160)      # words per minute inside a sentence: 80 or less -> 0, 160 or more -> full
PAUSE_SEC = 1.5            # a stop this long inside a sentence counts as hesitation
PAUSE_COST = 0.2           # each hesitation takes 20% of the pause half of fluency
CLARITY_RANGE = (0.8, 0.96)  # average model confidence on correctly read words
GRADES = [(85, "A"), (70, "B"), (0, "C")]  # provisional: tune against teacher grades
MIN_HEARD = 0.3            # heard fewer words than 30% of the script -> can't score


def scale(x, lo, hi):
    return min(max((x - lo) / (hi - lo), 0.0), 1.0)


def score_reading(ref, hyp, correct, pairs):
    """pairs: (ref index, hyp index) for words read exactly as written."""
    if len(hyp) < MIN_HEARD * len(ref):
        return None

    content = [i for i, w in enumerate(ref) if not w["name"]]
    accuracy = sum(correct[i] for i in content) / len(content) if content else 0

    # Fluency is measured within each script line only: the gap between lines
    # may just be waiting for the next character's turn in the video.
    by_line = {}
    for i, j in pairs:
        by_line.setdefault(ref[i]["line"], []).append((i, j))
    words = span = pauses = 0
    for line_pairs in by_line.values():
        if len(line_pairs) < 2:
            continue
        (i_a, j_a), (i_b, j_b) = line_pairs[0], line_pairs[-1]
        words += i_b - i_a + 1
        span += hyp[j_b]["end"] - hyp[j_a]["start"]
        pauses += sum(hyp[j + 1]["start"] - hyp[j]["end"] >= PAUSE_SEC for j in range(j_a, j_b))
    wpm = words / span * 60 if span > 0 else 0
    fluency = 0.5 * scale(wpm, *WPM_RANGE) + 0.5 * max(0.0, 1 - PAUSE_COST * pauses)

    probs = [hyp[j]["p"] for _, j in pairs]
    confidence = sum(probs) / len(probs) if probs else 0
    clarity = scale(confidence, *CLARITY_RANGE)

    parts = {"accuracy": accuracy, "fluency": fluency, "clarity": clarity}
    points = {k: parts[k] * WEIGHTS[k] for k in WEIGHTS}
    total = sum(points.values())
    grade = next(g for cut, g in GRADES if total >= cut)
    return {"total": total, "grade": grade, "points": points, "accuracy": accuracy,
            "n_content": len(content), "n_names": len(ref) - len(content),
            "wpm": wpm, "pauses": pauses, "confidence": confidence}
