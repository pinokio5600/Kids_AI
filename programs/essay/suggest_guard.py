"""개선 제안(Suggestions for Improvement) 안전장치: 글이 이미 잘한 것을 하라는 제안을 지운다.

2026-11-26 배치 350편: 309편(88%)에 "Use transition words like 'however' or ..."가 붙었다.
그중 246편은 이미 연결어를 3개 이상 쓴 글, 만점 54편 중 46편에도 붙었다.
프롬프트에 "이미 잘한 건 제안하지 마"가 있어도 9B 모델이 지키지 못해서 코드로 거른다.
"""
import re

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

# 제안 종류
_SUG_TRANSITION = re.compile(r"transition|linking words?|connecting words?|connect(?:ing)? (?:your|the) (?:ideas|sentences|paragraphs|reasons)", re.I)
_SUG_EXAMPLE = re.compile(r"\b(?:add|give|include|use|provide|support\b.*\bwith)\b.*\bexamples?\b", re.I)
_SUG_EXAMPLE_DEEPER = re.compile(r"\bexplain\b|\bdepth\b|\bdetail|\bmore specific|\bdevelop|\bpersonal\b", re.I)
_SUG_CONCLUSION = re.compile(r"\b(?:add|write|include|make)\b.*\bconclusion\b|\brestate\b|\bsumm(?:ary|arize)\b.*\bend\b", re.I)
# "'however' or 'furthermore'"에서 however만 뺀다 (이유와 이유 사이에 however는 틀린 조언)
_HOWEVER_EXAMPLE = re.compile(r"'however'\s*(?:,|or|and)\s*|\s*(?:,|or|and)\s*'however'", re.I)

MIN_TRANSITIONS = 3  # 서로 다른 연결어를 이만큼 쓰면 연결어 제안을 지운다


def essay_facts(essay: str) -> dict:
    used = sorted({m.lower() for m in _TRANSITIONS.findall(essay)})
    return {
        "transitions": used,
        "has_example": bool(_HAS_EXAMPLE.search(essay)),
        "has_conclusion": bool(_HAS_CONCLUSION.search(essay)),
    }


def filter_suggestions(essay: str, suggestions: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """-> (남길 제안, [(지운 제안, 이유)])"""
    facts = essay_facts(essay)
    kept, dropped = [], []
    for s in suggestions:
        if _SUG_TRANSITION.search(s):
            if len(facts["transitions"]) >= MIN_TRANSITIONS:
                dropped.append((s, f"이미 연결어 {len(facts['transitions'])}개 사용"))
                continue
            s = _HOWEVER_EXAMPLE.sub("", s)
        if _SUG_EXAMPLE.search(s) and not _SUG_EXAMPLE_DEEPER.search(s) and facts["has_example"]:
            dropped.append((s, "이미 예시 있음"))
            continue
        if _SUG_CONCLUSION.search(s) and facts["has_conclusion"]:
            dropped.append((s, "이미 결론 있음"))
            continue
        kept.append(s)
    return kept, dropped
