"""Gate 3 — three-tier honest response (spec §2.4).

Grade a retrieval result so the owner knows how much to trust the answer:
    nothing retrieved, OR the top hit is lexical noise
                              -> "insufficient"  (fixed text, LLM NOT called)
    retrieved, top score low  -> "marginal"      (prepend a 僅供參考 label)
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
# NOTE the measured gap (evals/RESULTS.md): on the current corpus, absolute BM25
# cannot separate marginal from normal (marginal cases score 15.4–29.4,
# interleaved with normal ones), so with these defaults the marginal band is
# effectively empty. Fixing that needs a better relevance signal (hybrid
# retrieval — the roadmap item), not a better constant.
MARGINAL_SCORE_THRESHOLD = 1.5

# CALIBRATED against golden set v1 (2026-07-15): a top score below this means
# the hits share only generic tokens with the question (樓上/鄰居/公寓…), i.e.
# lexical noise — grade "insufficient" and never call the LLM. Evidence: the
# one out-of-scope leak (oos-01 漏水) tops out at BM25 3.89 while the weakest
# in-scope case scores 9.65; 6.0 sits at the geometric midpoint of that gap.
# Re-check with evaluation/calibrate.py whenever the corpus changes.
INSUFFICIENT_SCORE_THRESHOLD = 6.0


def grade_honesty(
    retrieved: list[Statute],
    scores: list[float],
    threshold: float = MARGINAL_SCORE_THRESHOLD,
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD,
) -> str:
    """Return the honesty tier: "insufficient" | "marginal" | "normal"."""
    if not retrieved:
        return "insufficient"
    top = max(scores) if scores else 0.0
    if top < insufficient_threshold:
        return "insufficient"
    if top < threshold:
        return "marginal"
    return "normal"
