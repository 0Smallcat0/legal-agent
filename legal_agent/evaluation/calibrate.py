"""Honesty-threshold calibration (SPEC roadmap: "calibrate the honesty
threshold" against the golden set).

`MARGINAL_SCORE_THRESHOLD` ships as an uncalibrated placeholder — BM25
magnitudes depend on the corpus. This module turns the golden set into the
calibration signal: for every case with an `expected_tier`, take the observed
top BM25 score, sweep candidate thresholds, and report the threshold that
maximizes tier accuracy.

The honesty tier is decided BEFORE the LLM runs (retrieval scores only), so
calibration needs NO real model: the CLI runs the golden set with a trivial
stub llm and only uses (top_score, expected_tier) pairs.

Run:  python -m legal_agent.evaluation.calibrate evals/golden_noise_v1.json
"""
from __future__ import annotations

from dataclasses import dataclass

from legal_agent.anti_hallucination.honesty import INSUFFICIENT_SCORE_THRESHOLD

# A stub answer with all three Mechanism-4 headings, so the pipeline runs
# cleanly; its text is irrelevant to tier grading.
_STUB_ANSWER = "「法律明文」:(無)\n「實務見解」:(無)\n「分析研判」:(無)"


@dataclass(frozen=True)
class CalibrationPoint:
    case_id: str
    top_score: float | None      # None = nothing retrieved (tier insufficient)
    expected_tier: str


@dataclass
class CalibrationResult:
    points: list[CalibrationPoint]
    best_threshold: float
    best_accuracy: float
    default_threshold: float
    default_accuracy: float
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD

    def render(self) -> str:
        lines = [
            "═══════ 誠實分級門檻校準(golden set 掃描) ═══════",
            f"樣本數:{len(self.points)}(含 expected_tier 的案例)",
            f"insufficient 下限(固定):{self.insufficient_threshold:g}",
            f"目前 marginal 門檻 {self.default_threshold:g} -> 分級正確率 {self.default_accuracy:.0%}",
            f"最佳 marginal 門檻 {self.best_threshold:g} -> 分級正確率 {self.best_accuracy:.0%}",
        ]
        return "\n".join(lines)


def predict_tier(
    top_score: float | None,
    threshold: float,
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD,
) -> str:
    """Mirror of honesty.grade_honesty over a bare top score (None = no hits)."""
    if top_score is None or top_score < insufficient_threshold:
        return "insufficient"
    return "marginal" if top_score < threshold else "normal"


def accuracy_at(
    points: list[CalibrationPoint],
    threshold: float,
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD,
) -> float:
    if not points:
        return 0.0
    hits = sum(
        1 for p in points
        if predict_tier(p.top_score, threshold, insufficient_threshold) == p.expected_tier
    )
    return hits / len(points)


def sweep_threshold(
    points: list[CalibrationPoint],
    default_threshold: float,
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD,
) -> CalibrationResult:
    """Sweep the MARGINAL threshold (the insufficient floor stays fixed).
    Candidate thresholds = midpoints between adjacent observed scores (plus
    the extremes), i.e. every decision boundary the data can distinguish."""
    scores = sorted({p.top_score for p in points if p.top_score is not None})
    candidates = [0.0]
    candidates += [(a + b) / 2 for a, b in zip(scores, scores[1:])]
    if scores:
        candidates += [scores[0] / 2, scores[-1] + 1.0]
    best = max(candidates, key=lambda t: (accuracy_at(points, t, insufficient_threshold), -t))
    return CalibrationResult(
        points=points,
        best_threshold=best,
        best_accuracy=accuracy_at(points, best, insufficient_threshold),
        default_threshold=default_threshold,
        default_accuracy=accuracy_at(points, default_threshold, insufficient_threshold),
        insufficient_threshold=insufficient_threshold,
    )


def collect_points(scorecard) -> list[CalibrationPoint]:
    """Extract (top_score, expected_tier) pairs from a golden-set Scorecard."""
    return [
        CalibrationPoint(c.id, c.top_score, c.expected_tier)
        for c in scorecard.cases
        if c.expected_tier is not None
    ]


if __name__ == "__main__":  # python -m legal_agent.evaluation.calibrate <golden.json>
    import sys as _sys

    if len(_sys.argv) < 2:
        print("用法:python -m legal_agent.evaluation.calibrate <golden.json>")
        raise SystemExit(2)

    from legal_agent.anti_hallucination.honesty import MARGINAL_SCORE_THRESHOLD
    from legal_agent.evaluation.golden_set import run_golden_set

    _scorecard = run_golden_set(_sys.argv[1], llm=lambda _p: _STUB_ANSWER)
    print(sweep_threshold(collect_points(_scorecard), MARGINAL_SCORE_THRESHOLD).render())
