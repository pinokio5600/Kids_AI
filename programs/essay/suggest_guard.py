"""개선 제안(Suggestions for Improvement) 안전장치: 글이 이미 잘한 것을 하라는 제안을 지운다.

2026-11-26 배치 350편: 309편(88%)에 "Use transition words like 'however' or ..."가 붙었다.
그중 246편은 이미 연결어를 3개 이상 쓴 글, 만점 54편 중 46편에도 붙었다.
프롬프트에 "이미 잘한 건 제안하지 마"가 있어도 9B 모델이 지키지 못해서 코드로 거른다.
"""
import re
from difflib import SequenceMatcher

from programs.essay.guard import COMMON_WORDS
from programs.essay.mistakes import CAPITALIZATION, SPELLING, TENSE, mistake_types

# 글에서 찾는 연결어 (단락·이유를 잇는 말)
_TRANSITIONS = re.compile(
    r"\b(first(?:ly)?|second(?:ly)?|third(?:ly)?|next|then|also|in addition|additionally|moreover|furthermore|"
    r"however|on the other hand|finally|lastly|in conclusion|to sum up|in summary|to conclude|therefore|so|"
    r"for example|for instance|because of this|as a result|the most important reason|another reason|"
    r"the next important reason)\b",
    re.I,
)
_HAS_EXAMPLE = re.compile(r"\bfor (?:example|instance)\b|\bsuch as\b|\blike when\b", re.I)
_HAS_CONCLUSION = re.compile(r"\bin conclusion\b|\bto sum up\b|\bin summary\b|\bto conclude\b|\ball in all\b", re.I)
# "In conclusion" 없이 끝 문장으로 맺는 글: "Therefore, I think ...", "For these reasons, ...", "So I think ..."
# (2026-11-27 배치: 이런 글 24편에 "Add a concluding sentence"가 붙었다)
_CONCLUDING_START = re.compile(
    r"^(?:\d+\.\s*)?(?:therefore|thus|so(?! many\b| much\b)|as a result|in short|that'?s why|this is why|"
    r"for (?:these|this|all these|those|the(?:se)? above) reasons?|because of (?:these|this|those) reasons?)\b", re.I)
# "So"는 본문에도 흔해서("So, they lose their patience.") 의견을 다시 말하는 문장일 때만 결론으로 친다
_SO_START = re.compile(r"^(?:\d+\.\s*)?so\b", re.I)
_OPINION = re.compile(r"\b(?:i|we) (?:\w+ )?(?:think|believe|agree|disagree|support|oppose)|\bshould\b|\bmust\b|"
                      r"harm than good|good than harm|\bso far\b", re.I)
_RESTATE = re.compile(r"^(?:i (?:strongly |really )?(?:think|believe|agree|disagree)|in my opinion)\b", re.I)
_VERDICT = re.compile(r"\b(?:harm|good|bad|better|agree|disagree|should|important|helpful|harmful)\b", re.I)
_CLOSING = re.compile(r"^(?:thank(?:s| you)|bye|good ?bye)\b", re.I)
# 마침표 뒤 띄어쓰기를 빼먹은 글("progress.Because")도 문장을 나눈다
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s*(?=[A-Za-z\"'])|(?<=[.!?])\s+|\n+")
# 문장 첫 글자가 소문자인 곳, 소문자 대명사 i
# 마침표 뒤 띄어쓰기를 빼먹은 ".which"도 잡는다 (www.youtube.com 같은 것도 걸리지만 그러면 제안을 남길 뿐이다)
_LOWER_START = re.compile(r"(?:\A|[.!?]\s*|\n\s*)[\"'(]?[a-z]")
_LOWER_I = re.compile(r"(?<![\w'’])i(?![\w'’])")

# 제안 종류
_SUG_TRANSITION = re.compile(r"transition|linking words?|connecting words?|connect(?:ing)? (?:your|the) (?:ideas|sentences|paragraphs|reasons)", re.I)
_SUG_EXAMPLE = re.compile(r"\b(?:add|give|include|use|provide|support\b.*\bwith)\b.*\bexamples?\b", re.I)
_SUG_EXAMPLE_DEEPER = re.compile(r"\bexplain\b|\bdepth\b|\bdetail|\bmore specific|\bdevelop|\bpersonal\b", re.I)
_SUG_CONCLUSION = re.compile(r"\b(?:add|write|include|make|end|finish)\b.*\bconclu(?:sion|ding)\b|\brestate\b|\bsumm(?:ary|arize)\b.*\bend\b|"
                             r"\b(?:opinion|idea)\b.*\bagain\b|\bat the (?:very )?end\b", re.I)  # 낮은 레벨: "says your opinion again at the end"
# 있는 결론을 낫게 하라는 제안은 남긴다: "... instead of just repeating", "Clarify the conclusion by explaining ..."
_SUG_CONCLUSION_BETTER = re.compile(r"instead of|\bexpand|\bstronger|\bclarify", re.I)
# "explain"은 있는 결론을 고치라는 뜻일 때만 남긴다. "Add a concluding sentence that explains ..."는 결론을 새로 넣으라는 것
_SUG_EXPLAIN = re.compile(r"\bexplain", re.I)
_SUG_ADD_START = re.compile(r"^(?:try\s+)?(?:add|adding|write|writing|include|including)\b", re.I)
# 철자 제안이 인용한 단어 ("Check your spelling of 'believe' and 'danger'")
_SUG_SPELL = re.compile(r"\bspell", re.I)
_QUOTED_WORD = re.compile(r"['‘\"“]([A-Za-z]+(?:'[a-z]+)?)['’\"”]")
_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
# "Use commas after introductory words like 'Because'": because 앞뒤 쉼표 조언은 틀린 조언이다
_SUG_COMMA_BECAUSE = re.compile(r"comma.*\bbecause\b|\bbecause\b.*comma", re.I)
# 시제·대문자 제안: 첨삭에 그런 고침이 하나도 없으면 없는 실수다 (mistakes.py)
_SUG_TENSE = re.compile(r"past tense|verb tenses?|\btenses?\b", re.I)
_SUG_CAPITAL_ANY = re.compile(r"capital", re.I)
# 실존 인물·발견·사건을 찾아야 하는 예시 요구: 프롬프트로 막아도 나온다 (2026-11-27 블라인드: 4~5학년 엉뚱함의 절반)
# "a real example ...", "an example of a specific discovery ..." (famous·news는 글 내용에 흔해서 넣지 않았다)
_SUG_REAL_WORLD = re.compile(r"\breal\b(?!-life| life)|\bexamples? of (?:a |an |one )?(?:specific |real )?"
                             r"(?:discover(?:y|ies)|scientists?|inventors?|inventions?|technolog(?:y|ies)|medicines?|winners?)\b", re.I)
# 문법·철자·문장부호 제안 (1개까지만 남긴다)
_SUG_GRAMMAR = re.compile(r"spell|verb|tense|subject|agree|plural|singular|capital|comma|period|punctuat|article|"
                          r"'a'|'the'|preposition|apostrophe|missing word|grammar|noun|fragment|complete sentence|run-on", re.I)
# 대문자 제안: "Use capital letters at the beginning of every sentence." (대문자 실수가 없는 글 9편에 붙었다)
# 고유명사 대문자 제안은 남긴다 ("the international energy agency"처럼 실제 실수가 있었다)
_SUG_PROPER = re.compile(r"proper|names?\b|nouns?\b", re.I)
_SUG_CAPITAL = re.compile(r"capital.*\b(?:begin\w*|start\w*|first)\b|\b(?:begin\w*|start\w*)\b.*capital", re.I)
# 쉼표 제안: "Use commas after introductory words like 'First' and 'Second'"
_SUG_COMMA_INTRO = re.compile(r"comma.*\b(?:introductory|first|second|then|also|but|so|because)\b", re.I)
_INTRO_WITH_COMMA = re.compile(r"\b(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|next|finally|lastly|also|for example|in conclusion|however),", re.I)
# 단어 하나 고치기만 하는 제안: "Change 'go' to 'went'", "Replace 'reson' with 'reason'" (아이는 이미 빨간 글씨로 본다.
# 프롬프트에서 금지해도 2026-11-27 비교 40편에서 99개 중 22개). 실수 종류를 말하고 예를 드는 제안은 남긴다:
# "Fix subject-verb agreement errors, such as changing 'it have' to 'it has'", "Change verb phrases like '...' to ..."
_SUG_SINGLE_FIX = re.compile(r"^(?:change|replace|correct|fix)\s+(?:the\s+(?:word|phrase|verb|spelling\s+of)\s+)?['\"‘“]", re.I)
# 고치면서 규칙을 알려주면 남긴다: "Change 'is' to 'are' when talking about plural subjects", "... because research is uncountable"
_SUG_RULE = re.compile(r"\b(?:when|because)\b", re.I)
# "'however' or 'furthermore'"에서 however만 뺀다 (이유와 이유 사이에 however는 틀린 조언)
_HOWEVER_EXAMPLE = re.compile(r"'however'\s*(?:,|or|and)\s*|\s*(?:,|or|and)\s*'however'", re.I)

MIN_TRANSITIONS = 3  # 서로 다른 연결어를 이만큼 쓰면 연결어 제안을 지운다


def essay_facts(essay: str) -> dict:
    used = sorted({m.lower() for m in _TRANSITIONS.findall(essay)})
    ending = concluding_sentence(essay)
    return {
        "transitions": used,
        "has_example": bool(_HAS_EXAMPLE.search(essay)),
        "has_conclusion": bool(_HAS_CONCLUSION.search(essay)) or bool(ending),
        "concluding_sentence": ending,
        "capitals_ok": not _LOWER_START.search(essay.strip()) and not _LOWER_I.search(essay),
    }


def concluding_sentence(essay: str) -> str:
    """끝 두 문장(인사 빼고) 중 Therefore/So/For these reasons 등으로 시작하는 문장. 4문장 미만 글은 보지 않는다."""
    sents = [x.strip() for x in _SENT_SPLIT.split(essay.strip()) if x.strip()]
    while sents and _CLOSING.match(sents[-1]):
        sents.pop()
    if len(sents) < 4:
        return ""
    for x in reversed(sents[-2:]):
        if _CONCLUDING_START.match(x) and (not _SO_START.match(x) or (_OPINION.search(x) and len(x.split()) >= 4)):
            return x
    # "I think the Nobel Prize is more good than harm."처럼 처음에 말한 의견을 마지막 문장에서 다시 말함
    if _RESTATE.match(sents[-1]) and (any(_RESTATE.match(x) for x in sents[:3]) or _VERDICT.search(sents[-1])):
        return sents[-1]
    return ""


def _bad_spelling_quote(essay: str, s: str) -> str:
    """철자 제안이 인용한 단어 중, 원문에 맞게 썼고 틀리게 쓴 비슷한 단어도 없는 것 (없으면 "")"""
    words = {w.lower().replace("’", "'") for w in _WORD.findall(essay)}
    for q in _QUOTED_WORD.findall(s):
        q = q.lower()
        if q in words and q not in COMMON_WORDS:
            continue  # 아이가 틀리게 쓴 단어를 그대로 인용 ('thet', 'chuludren')
        variant = any(w != q and SequenceMatcher(None, w, q).ratio() >= 0.75 for w in words)
        if not variant:
            return q  # 맞게 썼거나(그럼 고칠 게 없다) 글에 아예 없는 단어
    return ""


def filter_suggestions(essay: str, suggestions: list[str],
                       corrected: str | None = None) -> tuple[list[str], list[tuple[str, str]]]:
    """-> (남길 제안, [(지운 제안, 이유)]). corrected를 주면 첨삭에 실제로 있는 실수 종류로도 거른다."""
    facts = essay_facts(essay)
    types = mistake_types(essay, corrected) if corrected is not None else None
    kept, dropped = [], []
    for s in suggestions:
        if _SUG_SINGLE_FIX.search(s) and not _SUG_RULE.search(s):
            dropped.append((s, "단어 하나 고치기 (빨간 글씨와 겹침)"))
            continue
        if _SUG_TRANSITION.search(s):
            if len(facts["transitions"]) >= MIN_TRANSITIONS:
                dropped.append((s, f"이미 연결어 {len(facts['transitions'])}개 사용"))
                continue
            s = _HOWEVER_EXAMPLE.sub("", s)
        if _SUG_EXAMPLE.search(s) and not _SUG_EXAMPLE_DEEPER.search(s) and facts["has_example"]:
            dropped.append((s, "이미 예시 있음"))
            continue
        if _SUG_COMMA_INTRO.search(s) and len(_INTRO_WITH_COMMA.findall(essay)) >= 2:
            dropped.append((s, "이미 First, 등 뒤에 쉼표 사용"))
            continue
        if _SUG_SPELL.search(s) and (q := _bad_spelling_quote(essay, s)):
            dropped.append((s, f"철자 제안에 틀리지 않은 단어 '{q}'"))
            continue
        if _SUG_REAL_WORLD.search(s):
            dropped.append((s, "실존 인물·사건 사례 요구 (아이가 지어낼 수 있음)"))
            continue
        if _SUG_COMMA_BECAUSE.search(s):
            dropped.append((s, "because 쉼표 (틀린 조언)"))
            continue
        if types is not None:
            if _SUG_TENSE.search(s) and TENSE not in types:
                dropped.append((s, "첨삭에 시제 고침 없음"))
                continue
            if _SUG_CAPITAL_ANY.search(s) and CAPITALIZATION not in types:
                dropped.append((s, "첨삭에 대문자 고침 없음"))
                continue
            if _SUG_SPELL.search(s) and SPELLING not in types:
                dropped.append((s, "첨삭에 철자 고침 없음"))
                continue
        better = _SUG_CONCLUSION_BETTER.search(s) or (_SUG_EXPLAIN.search(s) and not _SUG_ADD_START.search(s))
        if _SUG_CONCLUSION.search(s) and not better and facts["has_conclusion"]:
            dropped.append((s, "이미 결론 있음"))
            continue
        if _SUG_CAPITAL.search(s) and not _SUG_PROPER.search(s) and facts["capitals_ok"]:
            dropped.append((s, "문장 첫 글자 대문자 실수 없음"))
            continue
        if _SUG_GRAMMAR.search(s):
            if any(_SUG_GRAMMAR.search(x) for x in kept):
                dropped.append((s, "문법 제안은 1개까지 (빨간 글씨와 겹침)"))
                continue
        kept.append(s)
    # (2026-11-27) 남은 게 없을 때 단어 고치기 제안을 되살리던 장치는 뺐다: 빨간 글씨와 겹치는 말은 안 올린다
    return [strip_reason_number(strip_fix_example(x)) for x in kept], dropped


# 이유를 번호로 부르면 틀리기 쉽다 ("For your third point ..."인데 실제로는 첫 번째 이유). 프롬프트로 막아도 계속 써서 코드로 뺀다
_NUM = r"(?:first|second|third|fourth|fifth|last|final|1st|2nd|3rd)"


def strip_reason_number(s: str) -> str:
    out = re.sub(rf"\byour\s+{_NUM}\s+(reason|point|paragraph)\s+(?=about\b)", r"your \1 ", s, flags=re.I)
    out = re.sub(rf"^(?:in|for)\s+your\s+{_NUM}\s+(?:reason|point|paragraph),\s*", "", out, flags=re.I)
    out = re.sub(rf"\s+(?:in|for)\s+your\s+{_NUM}\s+(?:reason|point|paragraph)(?=[.!?]$)", "", out, flags=re.I)
    out = re.sub(rf"\byour\s+{_NUM}\s+(reason|point)\b", r"your \1", out, flags=re.I)
    return out[:1].upper() + out[1:] if out else s


# 실수 종류를 말하면서 붙인 "X를 Y로" 예시: 아이는 이미 빨간 글씨로 봤다 (2026-11-27 사용자 지적)
# "..., such as changing 'do' to 'does'." / "... like 'gives' instead of 'for give' ..." / "(e.g., 'go' -> 'went')"
# 따옴표 안 단어 (people's처럼 글자 앞뒤에 낀 아포스트로피는 단어의 일부)
_Q = r"['‘\"“](?:[^'’\"”]|(?<=[A-Za-z])['’](?=[A-Za-z])){1,40}['’\"”]"
_FIX_EXAMPLE = re.compile(
    r",?\s*\(?(?:such as|like|for example,?|for instance,?|e\.g\.,?|including)\s+(?:by\s+)?(?:chang(?:e|ing)|us(?:e|ing)|writ(?:e|ing)|replac(?:e|ing))?\s*"
    rf"{_Q}\s*(?:to|into|with|instead of|rather than|->|→)\s*{_Q}"
    rf"(?:\s*(?:,|and|or)\s*{_Q}\s*(?:to|into|with|instead of|rather than|->|→)\s*{_Q})*\)?", re.I)


_SPELL_LIST = re.compile(
    rf",?\s*(?:\b(?:like|such as|including|e\.g\.,?)\s+(?:the\s+words?\s+)?|\s(?:of|for|on|in)\s+)?{_Q}(?:\s*,\s*{_Q})*(?:,?\s*(?:and|or)\s*{_Q})?", re.I)


def strip_fix_example(s: str) -> str:
    """제안에서 'X -> Y' 예시와 철자 제안의 단어 목록을 뺀다. 빼고 나서 너무 짧으면(4단어 미만) 그대로 둔다."""
    if re.match(r"(?:replace|change|correct|fix)\s+(?:the\s+)?(?:(?:words?|phrases?|verbs?)\s+like\b|['‘\"“])", s, re.I):
        return s  # "Replace words like 'Vy' with 'by'": 예시가 문장의 목적어라 빼면 문장이 깨진다
    out = _FIX_EXAMPLE.sub("", s).strip()
    if _SUG_SPELL.search(out):
        # 철자 제안의 단어 목록도 뺀다 ("... like 'thet' and 'beacuse'"): 틀린 단어는 이미 빨간 글씨로 보인다
        out = _SPELL_LIST.sub("", out).strip()
        out = re.sub(r"\s+(?:of|for|on|in|with)(?:\s+(?:the\s+)?words)?\s*([.!?])$", r"\1", out)  # "... for words." -> "..."
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out)
    if out and out[-1] not in ".!?":
        out += "."
    if len(out.split()) >= 4:
        return out
    if _SUG_SPELL.search(s) and out != s:
        return "Check the spelling of your words carefully."  # "Fix spelling mistakes like 'a' and 'b'." -> 너무 짧아짐
    return s


def facts_text(essay: str) -> str:
    """제안 호출에 넣을 '이 글이 이미 한 것' (구체적인 사실을 주면 9B 모델이 이미 한 걸 덜 제안한다)"""
    f = essay_facts(essay)
    done = []
    if f["transitions"]:
        done.append("uses these transition words: " + ", ".join(f["transitions"]))
    if f["has_example"]:
        done.append("already gives examples")
    if f["concluding_sentence"]:
        done.append(f'already ends with a concluding sentence: "{f["concluding_sentence"]}"')
    elif f["has_conclusion"]:
        done.append("already has a conclusion")
    if f["capitals_ok"]:
        done.append("starts every sentence with a capital letter")
    if not done:
        return ""
    return ("Facts about this essay (checked by a program): it " + "; it ".join(done) +
            ".\nDo not suggest adding or using anything listed in these facts.")
