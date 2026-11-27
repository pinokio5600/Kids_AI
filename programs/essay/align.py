"""원문과 첨삭 글의 토큰 줄 맞춤 (guard·render·grammar 점수가 같이 쓴다).

difflib.SequenceMatcher는 "가장 긴 같은 구간"부터 잡는다. 아이 글은 첫 문장과 마지막 문장이 거의 같은 경우가 많아서
(주장 → 이유 → 같은 주장 반복), 원문 첫 문장에 오타가 있으면 원문 마지막 문장과 첨삭 글 첫 문장을 짝지어 버리고
그 사이 글 전체가 지우기+넣기 한 덩어리가 됐다 (2026-11-27 id 10670461: 안전장치가 글 전체를 되돌림).
여기서는 순서를 지키면서 같은 토큰 수가 가장 많은 짝(LCS)을 찾는다.
반환 형식은 SequenceMatcher.get_opcodes()와 같다: (tag, i1, i2, j1, j2), tag는 equal/replace/delete/insert.
"""
from array import array


def opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    n, m = len(a), len(b)
    # 앞뒤 공통 부분은 표 계산에서 뺀다 (대부분의 글이 빨라진다)
    p = 0
    while p < n and p < m and a[p] == b[p]:
        p += 1
    s = 0
    while s < n - p and s < m - p and a[n - 1 - s] == b[m - 1 - s]:
        s += 1
    ai, bi = a[p:n - s], b[p:m - s]
    N, M = len(ai), len(bi)
    # L[i][j] = ai[i:]와 bi[j:]의 LCS 길이 (행마다 array로 메모리 절약)
    L = [array("H", bytes(2 * (M + 1))) for _ in range(N + 1)]
    for i in range(N - 1, -1, -1):
        row, nxt, x = L[i], L[i + 1], ai[i]
        for j in range(M - 1, -1, -1):
            if x == bi[j]:
                row[j] = nxt[j + 1] + 1
            else:
                r, d = nxt[j], row[j + 1]
                row[j] = r if r >= d else d
    # 앞에서부터 따라가며 토큰별 짝 만들기
    pairs = []  # ("=", i, j) / ("-", i) / ("+", j)
    i = j = 0
    while i < N and j < M:
        if ai[i] == bi[j] and L[i][j] == L[i + 1][j + 1] + 1:
            pairs.append(("=", i, j)); i += 1; j += 1
        elif L[i + 1][j] >= L[i][j + 1]:
            pairs.append(("-", i, j)); i += 1
        else:
            pairs.append(("+", i, j)); j += 1
    while i < N:
        pairs.append(("-", i, j)); i += 1
    while j < M:
        pairs.append(("+", i, j)); j += 1

    ops: list[tuple[str, int, int, int, int]] = []

    def push(tag, i1, i2, j1, j2):
        if i1 == i2 and j1 == j2:
            return
        if ops and ops[-1][0] == tag:
            t, a1, _, b1, _ = ops.pop()
            ops.append((tag, a1, i2, b1, j2))
        else:
            ops.append((tag, i1, i2, j1, j2))

    push("equal", 0, p, 0, p)
    k = 0
    while k < len(pairs):
        if pairs[k][0] == "=":
            _, i, j = pairs[k]
            push("equal", p + i, p + i + 1, p + j, p + j + 1)
            k += 1
            continue
        # 같지 않은 토큰을 모아서 replace/delete/insert 한 덩어리로
        i1, j1 = pairs[k][1], pairs[k][2]
        di = dj = 0
        while k < len(pairs) and pairs[k][0] != "=":
            if pairs[k][0] == "-":
                di += 1
            else:
                dj += 1
            k += 1
        tag = "replace" if di and dj else "delete" if di else "insert"
        ops.append((tag, p + i1, p + i1 + di, p + j1, p + j1 + dj))
    push("equal", n - s, n, m - s, m)
    return ops
