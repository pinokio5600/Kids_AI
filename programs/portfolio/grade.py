"""녹음 한 개 채점: 받아 적기 -> 대본과 맞춰 보기 -> 다른 곳마다 실수/오인식 판정 -> 점수."""
from programs.portfolio.align import compare, phrase, transcribe_words
from programs.portfolio.check import check_mismatch
from programs.portfolio.score import score_reading


def grade_recording(model, scorer, ref, audio, no_boost=False, drop_p=0.3,
                    pass_gap=-1.0, max_pass_words=3):
    hyp = transcribe_words(model, audio, no_boost, drop_p)

    matched = 0
    rows = []
    correct = [False] * len(ref)
    pairs = []
    for op, rs, hs in compare(ref, hyp):
        n_ref = rs[1] - rs[0]
        if op == "equal":
            matched += n_ref
            correct[rs[0]:rs[1]] = [True] * n_ref
            if n_ref == hs[1] - hs[0]:
                pairs += zip(range(*rs), range(*hs))
            else:  # "cyberattacks" vs "cyber attacks": only the ends line up
                pairs += [(rs[0], hs[0]), (rs[1] - 1, hs[1] - 1)]
            continue
        said = phrase(hyp, *hs)
        script = phrase(ref, *rs)
        t = hyp[hs[0]]["start"] if hs[0] < len(hyp) else (hyp[-1]["end"] if hyp else 0)
        if op == "insert" and rs[0] in (0, len(ref)):
            # Greeting / closing words before or after the script: not a reading error.
            rows.append({"t": t, "kind": "대본 밖 발화", "script": "", "said": said,
                         "verdict": "참고", "check": None})
            continue
        check = check_mismatch(scorer, audio, ref, hyp, rs, hs)
        kind = {"replace": "다르게 읽음", "delete": "빠뜨림", "insert": "추가로 말함"}[op]
        omit = check["omit_score"] if check else None
        if (op == "replace" and omit is not None
                and omit >= max(check["ref_score"], check["hyp_score"])):
            # Saying nothing fits the audio best: mumbled or skipped.
            kind = "불분명/빠뜨림"
            verdict = "확인 필요"
        elif (check and check["gap"] >= pass_gap
              # A long stretch that differs is not a slip of the model's ear.
              and max(n_ref, hs[1] - hs[0]) <= max_pass_words):
            verdict = "통과 (모델이 잘못 들음)"
            if op != "insert":
                matched += n_ref
                correct[rs[0]:rs[1]] = [True] * n_ref
        else:
            verdict = "확인 필요"
        rows.append({"t": t, "kind": kind, "script": script, "said": said,
                     "verdict": verdict, "check": check})

    pairs.sort()
    return {
        "hyp": hyp,
        "rows": rows,
        "matched": matched,
        "rate": matched / len(ref) * 100 if ref else 0,
        "score": score_reading(ref, hyp, correct, pairs),
        "todo": sum(r["verdict"] == "확인 필요" for r in rows),
    }
