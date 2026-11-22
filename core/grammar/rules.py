"""문법 교정 규칙 (모든 기능이 같이 쓰는 부분).

"틀린 것만 고치고 아이가 쓴 표현은 그대로 둔다"는 원칙을 여기 한 곳에서 관리한다.
에세이 첨삭(programs/essay/prompt.py)이 이 규칙을 가져다 쓴다.
"""

FIX_RULES = """- Fix ONLY real errors: grammar, spelling, capitalization, punctuation, and missing or
  wrong small words (articles, prepositions, verb forms) that make a sentence incorrect.
- Do NOT rewrite or "improve" sentences that are already correct.
  Keep the student's own words, word choices, and ideas. Do not replace a correct word with a
  "better" one, and do not add new sentences or new information.
  Example: "I visited Guam in U.S.A." -> "I visited Guam in the U.S.A." (add only "the";
  do NOT change it to "Guam, America").
- NEVER replace names of people, places, schools, or classes (e.g., "Tom", "Navy 1M",
  "샘물3M", "Jeju"). You may only fix their capitalization and spacing
  (e.g., "navy1m" -> "Navy 1M"). Never insert the student's grade level into the essay.
- When a sentence is unclear, make the smallest change that makes it grammatical."""
