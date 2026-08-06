"""The 4th axis answers 「consistent」 when it fails — so failures must be counted.

`semantic_consistent` is deliberately conservative: unreachable server,
unparseable reply, missing field all return (True, "") rather than flagging a
citation over the checker's own infrastructure. That is the right call and it
has a sharp edge — an outage is indistinguishable from a clean run, and the
direction is flattering.

It cost a real measurement on 2026-08-06: 9 planted subject swaps and 120
controls came back 0 flagged, which reads as a perfect false-positive record.
Ollama was down; not one of the 129 calls reached a model. These tests pin the
counter that makes that state visible, the way `real_recall` prints
`dense_fallbacks`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.anti_hallucination.semantic_check import (  # noqa: E402
    reset_semantic_unreached,
    semantic_consistent,
    semantic_unreached_count,
)


def _dead(_prompt):
    raise RuntimeError("connection refused")


@pytest.mark.parametrize("llm,label", [
    (_dead, "server unreachable"),
    (lambda p: "sorry, I cannot answer that", "no JSON in the reply"),
    (lambda p: '{"consistent": ', "JSON that does not parse"),
    (lambda p: '{"verdict": "fine"}', "valid JSON, wrong shape"),
])
def test_every_failure_path_is_counted_not_swallowed(llm, label):
    reset_semantic_unreached()
    consistent, reason = semantic_consistent("主張", "條文", llm)
    assert (consistent, reason) == (True, ""), f"{label} must not flag a citation"
    assert semantic_unreached_count() == 1, f"{label} must be counted"


def test_a_real_verdict_never_counts_as_unreached():
    """Only verdicts the model did NOT render are counted — otherwise the
    warning fires on every healthy run and gets ignored."""
    reset_semantic_unreached()
    assert semantic_consistent("主張", "條文", lambda p: '{"consistent": true}') == (True, "")
    ok, reason = semantic_consistent(
        "主張", "條文", lambda p: '{"consistent": false, "reason": "主體不符"}')
    assert ok is False
    assert "主體不符" in reason
    assert semantic_unreached_count() == 0


def test_the_mutation_report_says_so_when_the_axis_was_absent():
    """A number the model had no part in must not render as a clean scorecard."""
    from legal_agent.evaluation.mutation import MutationReport

    assert "語意軸" not in MutationReport([]).render()
    warned = MutationReport([], semantic_unreached=7).render()
    assert "語意軸" in warned and "7" in warned
