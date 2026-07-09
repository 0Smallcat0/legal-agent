"""Tests for the golden-set evaluation harness (step 5b-i): Tier 1 (statute
coverage, human-compared legal judgment) + Tier 2 (automated citation check).
Deterministic: a FAKE llm, no network, no Anthropic client.

Run:  python -m pytest tests/test_eval.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.dialogue import stage3  # noqa: E402
from legal_agent.evaluation.golden_set import run_golden_set  # noqa: E402
from legal_agent.evaluation.hallucination_check import check_answers  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "golden_noise_fixture.json"
FAKE_ANSWER = (
    "「法條依據」:依社會秩序維護法第72條,製造噪音可處新臺幣一萬元以下罰鍰。\n"
    "「分析研判」:僅供參考,建議先報警並反映管委會。"
)


@pytest.fixture
def real_conn():
    from legal_agent.config import DB_PATH
    from legal_agent.data.noise_seed import load_noise_statutes

    init_db(DB_PATH)
    conn = connect(DB_PATH)
    seed_source_hierarchy(conn)
    load_noise_statutes(conn)
    yield conn
    conn.close()


# ── Tier 1 ───────────────────────────────────────────────────────────────────
def test_tier1_scores_pass_and_miss_and_builds_no_client(real_conn, monkeypatch):
    boom = MagicMock(side_effect=AssertionError("no real client in tests"))
    monkeypatch.setattr(stage3, "default_anthropic_llm", boom)

    scorecard = run_golden_set(FIXTURE, llm=lambda p: FAKE_ANSWER, conn=real_conn)
    by_id = {c.id: c for c in scorecard.cases}

    # the case whose (fake) answer cites the expected §72 -> pass
    assert by_id["noise-pass"].statute_score == "pass"
    # the case whose expected §184 is neither cited nor retrieved -> miss
    assert by_id["noise-miss"].statute_score == "miss"
    assert scorecard.statute_pass == 1 and scorecard.statute_miss == 1
    assert boom.call_count == 0   # injected llm -> no real Anthropic client built


def test_tier1_scorecard_shows_answer_vs_expected_and_no_legal_autopass(real_conn):
    scorecard = run_golden_set(FIXTURE, llm=lambda p: FAKE_ANSWER, conn=real_conn)
    text = scorecard.render()
    # agent answer AND expected shown side by side
    assert "代理人回答" in text and "預期行動" in text
    # explicit: legal correctness is human-compared, NOT auto-passed
    assert "人工" in text and "不宣稱法律正確性自動通過" in text
    # the agent answer itself appears (so a human can compare)
    assert "社會秩序維護法第72條" in text


# ── Tier 2 ───────────────────────────────────────────────────────────────────
def test_tier2_counts_fabricated_as_flagged_faithful_as_clean(real_conn):
    faithful = "依社會秩序維護法第72條,可處新臺幣一萬元以下罰鍰。"
    fabricated = "依噪音管制法第99條,住戶製造噪音應受處罰。"
    report = check_answers([faithful, fabricated], conn=real_conn)

    assert report.total == 2
    assert report.flagged_answers == 1
    assert report.clean_answers == 1
    assert abs(report.flag_rate - 0.5) < 1e-9

    by_answer = {a.answer: a for a in report.per_answer}
    assert by_answer[fabricated].flagged is True
    assert by_answer[faithful].flagged is False


def test_tier2_empty_batch_is_zero_rate(real_conn):
    report = check_answers([], conn=real_conn)
    assert report.total == 0
    assert report.flag_rate == 0.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
