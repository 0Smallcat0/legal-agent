"""Gate 3 — three-tier honest response (spec §2.4).

Grade a retrieval result so the owner knows how much to trust the answer:
    nothing retrieved        -> "insufficient"  (fixed text, LLM NOT called)
    retrieved, top score low  -> "marginal"     (prepend a 僅供參考 label)
    otherwise                 -> "normal"
Never fabricate to fill a gap. Wired into dialogue/stage3.run_stage3.
"""
from __future__ import annotations

from legal_agent.data.models import Statute

# Fixed text when the corpus covers nothing — the LLM is short-circuited (spec §2.4).
INSUFFICIENT_TEXT = "這個問題我的資料庫沒有涵蓋,建議諮詢律師或換個描述方式"
# Prepended to a low-confidence answer.
MARGINAL_PREFIX = "以下僅供參考,未找到直接對應的法條"

# TUNABLE: a retrieval whose TOP BM25 score is below this is graded "marginal".
# This is an UNCALIBRATED placeholder — BM25 magnitudes depend on the corpus;
# calibrate it against the golden set (spec §4) once that exists.
MARGINAL_SCORE_THRESHOLD = 1.5


def grade_honesty(
    retrieved: list[Statute],
    scores: list[float],
    threshold: float = MARGINAL_SCORE_THRESHOLD,
) -> str:
    """Return the honesty tier: "insufficient" | "marginal" | "normal"."""
    if not retrieved:
        return "insufficient"
    top = max(scores) if scores else 0.0
    if top < threshold:
        return "marginal"
    return "normal"
