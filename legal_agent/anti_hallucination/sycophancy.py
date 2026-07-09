"""Gate 5 — anti-sycophancy / premise correction (spec §2.6).

The most dangerous failure for a layperson owner: asking with a wrong legal
premise ("鄰居走路有聲音,這構成恐嚇罪吧") and the model agreeing + fabricating
support. The system prompt (dialogue/stage3) instructs the model that correcting
a wrong premise takes priority over agreeing; check_premise is a heuristic
detector that FLAGS an asserted legal conclusion so the flag can be surfaced.
"""
from __future__ import annotations

import re

# Heuristic patterns for an ASSERTED legal conclusion (not a neutral description).
_PREMISE_PATTERNS = [
    r"構成.{0,8}罪",          # 這構成恐嚇罪 / 構成傷害罪
    r"告得成", r"告得贏", r"一定.{0,3}告", r"告死",   # 一定告得成 / 我一定要告
    r"一定.{0,4}賠", r"一定要賠", r"必須賠",           # 他一定要賠
    r"違法", r"犯法", r"觸法",
    r"一定.{0,2}贏", r"穩贏",
]
_PREMISE_RE = re.compile("|".join(_PREMISE_PATTERNS))


def check_premise(user_text: str) -> bool:
    """True if the user asserts a legal conclusion (e.g. 「這構成…罪」、
    「我一定告得成」、「他一定要賠」) — a sycophancy risk the model must CORRECT
    rather than agree with. False for a neutral factual description."""
    return bool(_PREMISE_RE.search(user_text or ""))
