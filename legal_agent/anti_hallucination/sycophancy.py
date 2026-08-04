"""Gate 5 — anti-sycophancy / premise correction (spec §2.6).

The most dangerous failure for a layperson owner: asking with a wrong legal
premise ("鄰居走路有聲音,這構成恐嚇罪吧") and the model agreeing + fabricating
support. The system prompt (dialogue/stage3) instructs the model that correcting
a wrong premise takes priority over agreeing; check_premise is a heuristic
detector that FLAGS an asserted legal conclusion so the flag can be surfaced.
"""
from __future__ import annotations

import re

# Assertions that stay assertions however they are punctuated — 「一定告得成」
# is a claim even with a question mark bolted on.
_STRONG_PATTERNS = [
    r"告得成", r"告得贏", r"一定.{0,3}告", r"告死",   # 一定告得成 / 我一定要告
    r"一定.{0,4}賠", r"一定要賠", r"必須賠",           # 他一定要賠
    r"一定.{0,2}贏", r"穩贏",
]
# Conclusion words that flip meaning with the sentence frame: 「就是違法」 asserts,
# 「有沒有違法?」 asks. Measured on a real session — 「這樣有沒有違法?」 tripped the
# flag and the user was told they had 「先下了法律判斷」 for asking the very
# question the tool exists to answer.
_WEAK_PATTERNS = [
    r"構成.{0,8}罪",          # 這構成恐嚇罪 / 算不算構成傷害罪
    r"違法", r"犯法", r"觸法",
]
_STRONG_RE = re.compile("|".join(_STRONG_PATTERNS))
_WEAK_RE = re.compile("|".join(_WEAK_PATTERNS))

# Genuine question frames (suppress) vs. agreement-seeking tags (still an
# assertion — 「就是違法,對吧?」 wants a yes, it is not asking).
_INTERROGATIVE = ("有沒有", "是不是", "是否", "算不算", "會不會", "能不能",
                  "可不可以", "該不該", "嗎", "?", "？", "呢")
_AGREEMENT_TAG = ("對吧", "對不對", "吧", "沒錯吧", "難道不")
_CLAUSE_BOUNDARY = "。！!\n；;"


def _clause_around(text: str, start: int, end: int) -> str:
    left = max((text.rfind(ch, 0, start) for ch in _CLAUSE_BOUNDARY), default=-1)
    right = min(
        (pos for pos in (text.find(ch, end) for ch in _CLAUSE_BOUNDARY) if pos != -1),
        default=len(text),
    )
    return text[left + 1:right]


def check_premise(user_text: str) -> bool:
    """True if the user ASSERTS a legal conclusion (e.g. 「這構成…罪」、
    「我一定告得成」、「他一定要賠」) — a sycophancy risk the model must CORRECT
    rather than agree with. False for a neutral description, and false for the
    same words asked as a real question (「這樣有沒有違法?」)."""
    text = user_text or ""
    if _STRONG_RE.search(text):
        return True
    for m in _WEAK_RE.finditer(text):
        clause = _clause_around(text, m.start(), m.end())
        if any(tag in clause for tag in _AGREEMENT_TAG):
            return True
        if not any(q in clause for q in _INTERROGATIVE):
            return True
    return False
