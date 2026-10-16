"""Gate 3 — three-tier honest response (spec §2.4).

Grade a retrieval result so the owner knows how much to trust the answer:
    nothing retrieved, OR the top hit is lexical noise
                              -> "insufficient"  (fixed text, LLM NOT called)
    retrieved, top score low  -> "marginal"      (prepend a 僅供參考 label)
    otherwise                 -> "normal"
Never fabricate to fill a gap. Wired into dialogue/stage3.run_stage3.
"""
from __future__ import annotations

from legal_agent.anti_hallucination.coverage import absent_domain
from legal_agent.data.models import Statute
from legal_agent.retrieval.lexicon import expansions

# Fixed text when the corpus covers nothing — the LLM is short-circuited (spec §2.4).
INSUFFICIENT_TEXT = "這個問題我的資料庫沒有涵蓋,建議諮詢律師或換個描述方式"


def insufficient_text(query: str = "") -> str:
    """The refusal, naming the missing body of law when the coverage table can.

    Still a closed-world statement: the statute exists, this corpus lacks it.
    """
    found = absent_domain(query)
    if not found:
        return INSUFFICIENT_TEXT
    statute, _trigger = found
    return (
        f"這個問題屬於{statute},不在我的資料庫涵蓋的法規內,所以我不回答。"
        "建議諮詢律師或洽法律扶助基金會"
    )
# Prepended to a low-confidence answer. It says "low relevance score", not "no
# article found": a band answer often DOES retrieve the right article (a 資遣費
# question scoring 97.8 still gets 勞基法§17).
MARGINAL_PREFIX = "以下僅供參考:檢索相關度偏低,請務必對照下方條文原文,必要時諮詢律師"

# Both thresholds calibrated against golden v2 (sweep and observed score ranges
# in evals/HISTORY.md). The marginal band overlaps normal: absolute BM25 cannot
# separate 「邊緣相關」 from 「相關」, so this recovers only one of four cases.
MARGINAL_SCORE_THRESHOLD = 106.0

# The floor sits inside the golden gap between insufficient and marginal scores.
# It goes stale silently when the corpus or retrieval changes (it once let every
# out-of-scope question through for a week): re-run evaluation/calibrate.py.
INSUFFICIENT_SCORE_THRESHOLD = 70.0


def lexicon_hit(retrieved: list[Statute], query: str) -> bool:
    """Did a curated 口語→法條 phrase for `query` land verbatim on a retrieved
    article? The coverage evidence `grade_honesty` takes as `lexicon_hit`."""
    phrases = expansions(query or "")
    return any(p in (s.content or "") for s in retrieved for p in phrases)


def grade_honesty(
    retrieved: list[Statute],
    scores: list[float],
    threshold: float = MARGINAL_SCORE_THRESHOLD,
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD,
    lexicon_hit: bool = False,
    query: str = "",
) -> str:
    """Return the honesty tier: "insufficient" | "marginal" | "normal".

    `lexicon_hit` — a curated 口語→法條 phrase matched a retrieved article
    verbatim. BM25 scales with query length, so a short complaint scores low
    even when retrieval nailed it (「樓上小孩每天晚上跑跳…」 tops out at 28.8 yet
    gets 社維§72). It floors the tier at 「marginal」 instead of refusing; it
    never raises anything to 「normal」.

    `query` — the assembled fact string. If it names a body of law the corpus
    does not carry (coverage.py), the answer is refused outright. This veto
    only ever refuses; it cannot raise a tier.
    """
    if absent_domain(query):
        return "insufficient"
    if not retrieved:
        return "insufficient"
    top = max(scores) if scores else 0.0
    if top < insufficient_threshold:
        return "marginal" if lexicon_hit else "insufficient"
    if top < threshold:
        return "marginal"
    return "normal"
