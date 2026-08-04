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
from itertools import pairwise

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
    # The insufficient floor is swept too: it was calibrated on the 11-article
    # corpus (scores 4-42) and left fixed while corpus v2 pushed the same scores
    # to 30-330, so out-of-scope questions sailed straight over a floor of 6.
    best_insufficient: float | None = None
    default_insufficient: float = INSUFFICIENT_SCORE_THRESHOLD

    def render(self) -> str:
        best_floor = (self.best_insufficient if self.best_insufficient is not None
                      else self.insufficient_threshold)
        lines = [
            "═══════ 誠實分級門檻校準(golden set 掃描) ═══════",
            f"樣本數:{len(self.points)}(含 expected_tier 的案例)",
            f"目前門檻 insufficient<{self.default_insufficient:g} / marginal<"
            f"{self.default_threshold:g} -> 分級正確率 {self.default_accuracy:.0%}",
            f"最佳門檻 insufficient<{best_floor:g} / marginal<{self.best_threshold:g}"
            f" -> 分級正確率 {self.best_accuracy:.0%}",
        ]
        by_tier: dict[str, list[float]] = {}
        for p in self.points:
            if p.top_score is not None:
                by_tier.setdefault(p.expected_tier, []).append(p.top_score)
        for tier in ("insufficient", "marginal", "normal"):
            scores = sorted(by_tier.get(tier, []))
            if scores:
                lines.append(
                    f"  預期 {tier:<12} top BM25 {scores[0]:.1f}–{scores[-1]:.1f}(n={len(scores)})"
                )
        lines.append("  (兩層範圍若重疊,代表絕對 BM25 切不開——訊號問題,不是常數問題)")
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


def _candidates(points: list[CalibrationPoint]) -> list[float]:
    """Every decision boundary the data can distinguish: midpoints between
    adjacent observed scores, plus the extremes."""
    scores = sorted({p.top_score for p in points if p.top_score is not None})
    out = [0.0]
    out += [(a + b) / 2 for a, b in pairwise(scores)]
    if scores:
        out += [scores[0] / 2, scores[-1] + 1.0]
    return out


def sweep_threshold(
    points: list[CalibrationPoint],
    default_threshold: float,
    insufficient_threshold: float = INSUFFICIENT_SCORE_THRESHOLD,
) -> CalibrationResult:
    """Sweep BOTH thresholds — the insufficient floor and the marginal band.

    Sweeping only the marginal threshold hid a live defect: the floor was
    calibrated at 6.0 on the 11-article corpus and never revisited, while
    corpus v2 lifted every score by an order of magnitude. Out-of-scope
    questions (商標搶註, 虛擬貨幣課稅) scored 30-40 — far over the floor — and
    were answered as if the corpus covered them.
    """
    candidates = _candidates(points)
    pairs = [
        (floor, marginal)
        for floor in candidates
        for marginal in candidates
        if marginal >= floor
    ]
    best_floor, best_marginal = max(
        pairs, key=lambda fm: (accuracy_at(points, fm[1], fm[0]), -fm[0], -fm[1])
    )
    return CalibrationResult(
        points=points,
        best_threshold=best_marginal,
        best_accuracy=accuracy_at(points, best_marginal, best_floor),
        default_threshold=default_threshold,
        default_accuracy=accuracy_at(points, default_threshold, insufficient_threshold),
        insufficient_threshold=insufficient_threshold,
        best_insufficient=best_floor,
        default_insufficient=insufficient_threshold,
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
