"""Tests for the measurement suite: verifier mutation test, threshold
calibration, bare-vs-gated ablation, and the golden-set auto-score extensions
(expected_tier / expected_premise_flag / top_score). Deterministic: fake llms,
no network, no real model.

Run:  python -m pytest tests/test_eval_suite.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.noise_seed import load_noise_statutes  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.evaluation.ablation import run_ablation, strip_think  # noqa: E402
from legal_agent.evaluation.calibrate import (  # noqa: E402
    CalibrationPoint,
    collect_points,
    predict_tier,
    sweep_threshold,
)
from legal_agent.evaluation.golden_set import run_golden_set  # noqa: E402
from legal_agent.evaluation.mutation import run_mutation_test  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "golden_noise_fixture.json"
GOLDEN_V1 = ROOT / "evals" / "golden_noise_v1.json"

# All three Mechanism-4 headings so the pipeline runs cleanly; text content is
# irrelevant to the deterministic checks below.
STUB_ANSWER = "「法律明文」:(無)\n「實務見解」:(無)\n「分析研判」:(無)"


@pytest.fixture
def real_conn():
    from legal_agent.config import DB_PATH

    init_db(DB_PATH)
    conn = connect(DB_PATH)
    seed_source_hierarchy(conn)
    load_noise_statutes(conn)
    yield conn
    conn.close()


# ── mutation: the verifier's own recall is measured, not assumed ─────────────
def test_mutation_catches_all_planted_errors_no_false_positives(real_conn):
    report = run_mutation_test(real_conn)
    assert report.mutation_total >= 20          # 9+ articles x 3 mutations + fake statute
    assert report.catch_rate == 1.0, report.render()
    assert report.false_positive_rate == 0.0, report.render()


def test_mutation_render_shows_rates(real_conn):
    text = run_mutation_test(real_conn).render()
    assert "catch rate" in text and "false-positive" in text


# ── calibration sweep ────────────────────────────────────────────────────────
def test_sweep_finds_a_separating_threshold():
    points = [
        CalibrationPoint("a", 5.0, "normal"),
        CalibrationPoint("b", 4.0, "normal"),
        CalibrationPoint("c", 0.5, "marginal"),
        CalibrationPoint("d", None, "insufficient"),
    ]
    result = sweep_threshold(points, default_threshold=1.5)
    assert result.best_accuracy == 1.0
    assert 0.5 < result.best_threshold <= 4.0
    assert predict_tier(None, result.best_threshold) == "insufficient"
    assert "門檻" in result.render()


# ── golden set v1 + auto-score extensions ────────────────────────────────────
def test_golden_v1_loads_and_autoscores(real_conn):
    scorecard = run_golden_set(GOLDEN_V1, llm=lambda _p: STUB_ANSWER, conn=real_conn)
    assert scorecard.total == 25
    # every v1 case carries both machine-checkable expectations
    assert scorecard.tier_checked == 25
    assert scorecard.premise_checked == 25

    by_id = {c.id: c for c in scorecard.cases}
    # out-of-scope questions short-circuit to "insufficient" BEFORE the LLM
    assert by_id["oos-02-inheritance"].honesty_tier == "insufficient"
    assert by_id["oos-02-inheritance"].tier_ok is True
    # Mechanism-5 premise detector: fires on asserted conclusions only
    assert by_id["wp-01-intimidation"].premise_flag is True
    assert by_id["in-01-midnight-quarrel"].premise_flag is False
    # time-slice pair: the 2025-06-11 社維法§72 slice IS surfaced today...
    assert "社會秩序維護法第72條" in by_id["ts-02-dispute-now"].matched_statutes
    # ...and calibration points come out of the same run
    points = collect_points(scorecard)
    assert len(points) == 25


def test_golden_render_includes_new_scores(real_conn):
    scorecard = run_golden_set(FIXTURE, llm=lambda _p: STUB_ANSWER, conn=real_conn)
    text = scorecard.render()
    # fixture has no expected_tier fields -> nothing checked, render still works
    assert scorecard.tier_checked == 0
    assert "誠實分級正確率" in text


# ── ablation: bare vs gated with an injected fake model ──────────────────────
FAKE_ANSWER = (
    "<think>試著混入一條不存在的法源。</think>"
    "「法律明文」:依社會秩序維護法第72條,製造噪音不聽禁止得處罰鍰。"
    "另依噪音管制法第99條,亦應受管制。\n"
    "「實務見解」:以下為主管機關實務見解/處理原則,非法律明文,僅供參考:(無)\n"
    "「分析研判」:僅供參考。"
)


def test_ablation_counts_unverifiable_citations_and_strips_think(real_conn):
    factory = lambda model: (lambda _p: FAKE_ANSWER)  # noqa: E731
    report = run_ablation(FIXTURE, models=["fake-a"], llm_factory=factory, conn=real_conn)

    # 2 fixture cases x 2 conditions
    assert len(report.runs) == 4
    assert all("<think>" not in r.answer for r in report.runs)

    bare = report.aggregate("fake-a", "bare")
    gated = report.aggregate("fake-a", "gated")
    # each answer carries 2 citations: §72 (real) + 噪音管制法§99 (planted fake)
    assert bare.total == 4 and bare.missing == 2 and bare.flagged == 2
    assert gated.total == 4 and gated.missing == 2 and gated.flagged == 2
    # gated runs carry an honesty tier; bare runs never do
    assert report.tier_distribution("fake-a")
    assert all(r.honesty_tier is None for r in report.runs if r.condition == "bare")

    text = report.render()
    assert "fake-a" in text and "bare" in text and "gated" in text


def test_strip_think_plain_passthrough():
    assert strip_think("<think>abc</think>答案") == "答案"
    assert strip_think("答案") == "答案"


def test_ablation_records_model_errors_without_losing_batch(real_conn, monkeypatch):
    import legal_agent.evaluation.ablation as ab

    monkeypatch.setattr(ab.time, "sleep", lambda _s: None)   # retry backoff off in tests

    def dying_llm(_prompt: str) -> str:
        raise ConnectionResetError("simulated Ollama reset")

    report = run_ablation(
        FIXTURE, models=["dead-model"], llm_factory=lambda m: dying_llm, conn=real_conn
    )
    # every run recorded as [ERROR]; nothing crashed, aggregates stay empty
    assert report.errors == 4
    assert all(r.answer.startswith("[ERROR]") for r in report.runs)
    assert report.aggregate("dead-model", "bare").total == 0
    assert "未計入" in report.render()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
