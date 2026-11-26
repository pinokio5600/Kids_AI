"""아이가 과제 양식(템플릿)을 지우지 않고 제출한 부분을 걷어낸다.

예)  2025 Spring Semester 3-minute speech
     Topic : The smart device I want in the future
     [Introduction] ?Introduce yourself to everyone ex) Hi. I'm Tim. I'm in 샘물M.
     Hello, my name is Tom (이름) and I am in Navy 1M.
     ♡ Body
     wolf__________ are one of the endangered animals.
     Korea is a great [ex)great/beautiful] country.
이런 부분은 영어 실수가 아니므로, 첨삭·채점 전에 지워서 틀린 것으로 표시되지 않게 한다.
본문 문장 안의 한글 반 이름(예: "I'm in 샘물1M")은 아이가 쓴 문장이므로 그대로 둔다.
"""
import re

SECTION = r"(?:introduction|intro|body|conclusion|closing|opening)"
# 단락 번호: "Body 1", "Body1", "Body #2", "Body paragraph 1", "Body II"
# (2026-11-26: "Body 1"에서 "Body"만 지우고 "1"이 아이 화면에 남던 문제)
_NUM = r"(?:\s*(?:paragraph\s*)?#?\s*\d{1,2}\b|\s+(?:paragraph\s+)?[IV]{1,3}\b|\s+paragraph\b)?"
_MARKER = re.compile(
    rf"^\s*[♡♥★☆•*]?\s*(?:"
    rf"[<〈\[(（]\s*{SECTION}{_NUM}\s*[)）\]〉>]\s*[:：\-–]?"  # [Body 1] / <Intro>
    rf"|{SECTION}{_NUM}\s*(?:[:：\-–]|$)"                    # Body 1 / Intro: ... (줄 끝이나 구분 기호까지)
    rf")\s*",
    re.I,
)
# 괄호 없는 제목은 그 줄에 제목만 있거나 뒤에 : - 가 올 때만 제목으로 본다.
# "Body language is important."나 "Introduction of new rules ..." 같은 아이 문장은 그대로 둔다.

# 줄 전체를 지우는 패턴
_DROP_LINE = [
    re.compile(r"^\s*[<〈\[(（]?\s*topic\s*[)）\]〉>]?\s*[:：].*$", re.I),                 # Topic : ...
    re.compile(r"\bminute[\s-]+speech\b|\bsemester\b.*\bspeech\b", re.I),                  # 2025 Spring Semester 3-minute speech
    re.compile(r"introduce yourself to everyone", re.I),                                   # 과제 안내문
    re.compile(r"^\s*ex\)", re.I),                                                         # ex) Hi. I'm Tim ...
    re.compile(r"^[\s\d.,:()/~\-가-힣]*[가-힣][\s\d.,:()/~\-가-힣]*$"),                      # 한글로만 된 안내 줄
]
# 단락 제목 뒤에 붙은 안내문: "[Body] ? Animals' appearance, ..."  "[Body] - ex) ..."
_HINT_AFTER_MARKER = re.compile(r"^\s*(?:[?\-–]|ex\))", re.I)
# 보기 힌트: "[ex)great/beautiful]"
_EX_HINT = re.compile(r"\s*\[\s*ex\)[^\]]*\]", re.I)
# 괄호 안 한글 메모: (이름), (주제쓰기), (노래부르면 럭키쿠폰-의무는 아님)
_PAREN = re.compile(r"\s*[(（]([^()（）]{1,60})[)）]")


def _drop_korean_paren(m: re.Match) -> str:
    inner = m.group(1)
    hangul = len(re.findall(r"[가-힣]", inner))
    latin = len(re.findall(r"[A-Za-z]", inner))
    # 한글이 섞인 괄호 메모는 지운다 (예: "(이는 Coco Chanel에서 비롯되었다.)")
    return "" if hangul >= 2 or (hangul and hangul >= latin) else m.group(0)


def strip_scaffolding(text: str) -> str:
    out = []
    for line in text.splitlines():
        if any(p.search(line) for p in _DROP_LINE):
            continue
        m = _MARKER.match(line)
        if m and _HINT_AFTER_MARKER.match(line[m.end():]):
            # 단락 제목 + 과제 안내문: 안내문만 지우고 제목은 남긴다
            # (2026-11-26 사용자 결정: Intro / Body / Conclusion 같은 단락 제목은 지우지 않는다)
            line = re.sub(r"[\s:：\-–]+$", "", m.group(0)).strip()
        line = _EX_HINT.sub("", line)
        line = _PAREN.sub(_drop_korean_paren, line)
        if "_" in line:  # 빈칸 채우기 밑줄
            line = re.sub(r"\s*_+\s*", " ", line)
            line = re.sub(r" +([.,!?;:])", r"\1", line)
        out.append(re.sub(r"[ \t]{2,}", " ", line).strip())
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
