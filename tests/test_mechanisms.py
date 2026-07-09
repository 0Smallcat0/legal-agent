"""Unit tests for Mechanisms 3/4/5 (step 4d): three-tier honesty, 法條/研判
separation, and anti-sycophancy premise detection. Deterministic, no LLM.

Run:  python -m pytest tests/test_mechanisms.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.anti_hallucination.answer_structure import split_sections  # noqa: E402
from legal_agent.anti_hallucination.honesty import grade_honesty  # noqa: E402
from legal_agent.anti_hallucination.sycophancy import check_premise  # noqa: E402
from legal_agent.data.models import Statute  # noqa: E402

_STUB = Statute("民法", "第793條", "土地所有人...", "2009-07-23", None, "法律", "http://x")


# ── Mechanism 3: three-tier honesty ──────────────────────────────────────────
def test_grade_insufficient_when_nothing_retrieved():
    assert grade_honesty([], []) == "insufficient"


def test_grade_normal_when_top_score_high():
    assert grade_honesty([_STUB], [10.0], threshold=1.0) == "normal"


def test_grade_marginal_when_top_score_below_threshold():
    assert grade_honesty([_STUB], [0.5], threshold=1.0) == "marginal"


# ── Mechanism 4: 法條/研判 separation ────────────────────────────────────────
def test_split_parses_three_sections():
    answer = (
        "法律明文:社會秩序維護法第72條……\n"
        "實務見解:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。……\n"
        "分析研判:僅供參考。"
    )
    law, practice, analysis = split_sections(answer)
    assert law is not None and "第72條" in law
    assert practice is not None and "非法律明文" in practice          # 實務見解 disclaimer
    assert analysis is not None and "分析研判" in analysis


def test_split_missing_sections_flagged_not_crashed():
    # old two-section (法條依據/分析研判) format: new headings mostly absent, no crash
    law, practice, analysis = split_sections("法條依據:X。分析研判:Y。")
    assert law is None and practice is None      # new 法律明文/實務見解 absent -> flagged
    assert analysis is not None                  # 分析研判 still parsed
    assert split_sections("只有一句話,沒有分段。") == (None, None, None)


# ── Mechanism 5: anti-sycophancy premise detection ───────────────────────────
def test_check_premise_flags_asserted_legal_conclusion():
    assert check_premise("鄰居走路有聲音,這構成恐嚇罪吧") is True


def test_check_premise_ignores_neutral_factual_description():
    assert check_premise("鄰居每天晚上走路很大聲,已經持續好幾個月了") is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
