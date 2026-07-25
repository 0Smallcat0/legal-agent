"""Unit tests for Mechanisms 3/4/5 (step 4d): three-tier honesty, 法條/研判
separation, and anti-sycophancy premise detection. Deterministic, no LLM.

Run:  python -m pytest tests/test_mechanisms.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.anti_hallucination.answer_structure import (  # noqa: E402
    PRACTICE_HEADING,
    is_empty_section,
    split_sections,
)
from legal_agent.anti_hallucination.honesty import grade_honesty  # noqa: E402
from legal_agent.anti_hallucination.sycophancy import check_premise  # noqa: E402
from legal_agent.data.models import Statute  # noqa: E402

_STUB = Statute("民法", "第793條", "土地所有人...", "2009-07-23", None, "法律", "http://x")


# ── Mechanism 3: three-tier honesty ──────────────────────────────────────────
def test_grade_insufficient_when_nothing_retrieved():
    assert grade_honesty([], []) == "insufficient"


def test_grade_normal_when_top_score_high():
    assert grade_honesty([_STUB], [10.0], threshold=1.0,
                         insufficient_threshold=0.5) == "normal"


def test_grade_marginal_when_top_score_below_threshold():
    # explicit low floor: the marginal band sits between the two thresholds
    assert grade_honesty([_STUB], [0.5], threshold=1.0, insufficient_threshold=0.2) == "marginal"


def test_grade_insufficient_when_top_score_is_lexical_noise():
    # calibrated floor (recalibrated to 70.0 on golden v2): hits that share only
    # generic tokens with the question are not an answer
    assert grade_honesty([_STUB], [3.89]) == "insufficient"


def test_grade_floor_is_inclusive_lower_bound():
    # exactly at the floor -> NOT insufficient (half-open band, mirrors slices).
    # Sits at the calibrated floor, above the marginal band, so: normal.
    from legal_agent.anti_hallucination.honesty import (
        INSUFFICIENT_SCORE_THRESHOLD,
        MARGINAL_SCORE_THRESHOLD,
    )

    assert grade_honesty([_STUB], [INSUFFICIENT_SCORE_THRESHOLD]) == "marginal"
    assert grade_honesty([_STUB], [MARGINAL_SCORE_THRESHOLD]) == "normal"


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


def test_check_premise_does_not_fire_on_the_question_itself():
    # Measured on a lived session: 「這樣有沒有違法?」 tripped the flag, so a user
    # asking the exact question the tool answers was told they had 「先下了
    # 法律判斷」. Asking is not asserting.
    assert check_premise("老闆說準備時間不算錢,這樣有沒有違法?") is False
    assert check_premise("房東這樣做算不算違法?") is False
    assert check_premise("公司說責任制所以沒有加班費,這樣合法嗎?") is False


def test_check_premise_still_fires_on_agreement_seeking_tag():
    # 「對吧?」 has a question mark but wants a yes — that is the sycophancy risk.
    assert check_premise("小孩白天在家跑跳就是違法,對吧?") is True
    assert check_premise("他這樣就是犯法。") is True


# ── Section decoration / empty sections ──────────────────────────────────────
def test_split_strips_markdown_decoration_around_headings():
    # Local models write 「**法律明文**」; splitting on the bare heading used to
    # leave a stray 「**」 on its own line between every section.
    answer = "**法律明文**\n民法第793條:…\n\n**實務見解**\n(無)\n\n**分析研判**\n僅供參考。"
    law, practice, analysis = split_sections(answer)
    assert not law.rstrip().endswith("*")
    assert law.splitlines()[0] == "法律明文"
    assert "**" not in law and "**" not in practice and "**" not in analysis


def test_empty_practice_section_is_recognised():
    assert is_empty_section("實務見解\n(無)", PRACTICE_HEADING) is True
    assert is_empty_section("實務見解\n無", PRACTICE_HEADING) is True
    assert is_empty_section("實務見解\n依內政部函釋…", PRACTICE_HEADING) is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
