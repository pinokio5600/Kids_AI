"""대본과 다르게 들린 곳이 정말 아이 실수인지, 모델이 잘못 들은 것인지 판단한다.

같은 소리 구간에 대해 "대본 문구"와 "받아 적은 문구" 중 어느 쪽이 더 잘 맞는지
whisper 모델에게 점수를 매기게 한다. 대본 쪽도 비슷하게 맞으면 모델이 잘못 들은 것.
"""
import numpy as np
from faster_whisper.audio import pad_or_trim
from faster_whisper.tokenizer import Tokenizer

from core.stt.engine import SR
from programs.portfolio.align import phrase


class Scorer:
    """Average log-probability of a given text for an audio clip (teacher-forced)."""

    def __init__(self, model):
        self.model = model
        self.tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                             task="transcribe", language="en")

    def evidence(self, clip, text):
        """How much the audio supports the text beyond plain language fluency:
        score on the clip minus score on silence of the same length."""
        s = self.score(clip, text)
        prior = self.score(np.zeros_like(clip), text)
        if s is None or prior is None:
            return None
        return s - prior

    def score(self, clip, text):
        tokens = self.tok.encode(" " + text.strip())
        if not tokens:
            return None
        feats = self.model.feature_extractor(clip)
        n_frames = min(feats.shape[-1], self.model.feature_extractor.nb_max_frames)
        enc = self.model.encode(pad_or_trim(feats))
        res = self.model.model.align(enc, self.tok.sot_sequence, [tokens], n_frames,
                                     median_filter_width=7)
        probs = np.clip(np.array(res[0].text_token_probs[: len(tokens)]), 1e-6, 1.0)
        return float(np.mean(np.log(probs)))


def check_mismatch(scorer, audio, ref, hyp, rs, hs):
    """Score script wording vs transcribed wording on the same audio, with 1 word of context."""
    (i1, i2), (j1, j2) = rs, hs
    ci1, ci2 = max(i1 - 1, 0), min(i2 + 1, len(ref))
    cj1, cj2 = max(j1 - 1, 0), min(j2 + 1, len(hyp))
    if cj1 >= cj2:
        return None
    start = max(hyp[cj1]["start"] - 0.3, 0)
    end = hyp[cj2 - 1]["end"] + 0.3
    if end - start > 29:
        return None
    clip = audio[int(start * SR): int(end * SR)]
    ref_score = scorer.evidence(clip, phrase(ref, ci1, ci2))
    hyp_score = scorer.evidence(clip, phrase(hyp, cj1, cj2))
    if ref_score is None or hyp_score is None:
        return None
    # Third candidate: the script words were not (clearly) said at all.
    # The model tends to fill a mumbled spot with a plausible word ("minutes").
    omit_score = None
    if i2 > i1:
        context = ref[ci1:i1] + ref[i2:ci2]
        if context:
            omit_score = scorer.evidence(clip, " ".join(w["text"] for w in context))
    return {"start": start, "end": end, "ref_score": ref_score, "hyp_score": hyp_score,
            "omit_score": omit_score, "gap": ref_score - hyp_score}
