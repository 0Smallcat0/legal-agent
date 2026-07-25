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
# Says what the band actually means. The old wording claimed 「未找到直接對應的
# 法條」, which is false in the common case: a 資遣費 question scoring 97.8 lands
# in the band and DOES retrieve 勞基法§17. Low relevance score, not no article.
MARGINAL_PREFIX = "以下僅供參考:檢索相關度偏低,請務必對照下方條文原文,必要時諮詢律師"

# RECALIBRATED 2026-07-25 against golden v2 (30 cases), sweeping BOTH thresholds:
#   floor 6 / marginal 1.5   -> tier accuracy 77%   (the pair shipped since v1)
#   floor 70 / marginal 106  -> tier accuracy 90%
# Observed top-BM25 ranges behind those numbers:
#   expected insufficient  31.6–40.5 (n=3)
#   expected marginal      85.4–268.1 (n=4)
#   expected normal       126.4–330.6 (n=23)
# The marginal band still overlaps normal — absolute BM25 genuinely cannot
# separate 「邊緣相關」 from 「相關」, a signal problem rather than a constant
# problem — so 106 recovers one of four marginal cases and no more.
MARGINAL_SCORE_THRESHOLD = 106.0

# The floor is the one that was silently broken. It was calibrated at 6.0 on the
# 11-article corpus (top scores 4–42) and never revisited while corpus v2 lifted
# the same scores to 30–330 — so EVERY out-of-scope question cleared it. Measured
# live: 「虛擬貨幣獲利怎麼課稅」 scored 37.5, was graded 「normal」, and the system
# answered a tax question with 中華民國刑法§196 (行使偽造貨幣). That is the exact
# failure this project exists to prevent, and it shipped for a week.
# 70 sits INSIDE the golden gap (40.5 … 85.4) rather than at its midpoint, so it
# also refuses two out-of-corpus questions a real session produced (商標搶註 62.9,
# 虛擬貨幣課稅 37.5) with margin to spare; golden accuracy is identical anywhere
# in 60–80. Re-check with evaluation/calibrate.py after any corpus or retrieval
# change — this constant goes stale silently.
INSUFFICIENT_SCORE_THRESHOLD = 70.0


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
