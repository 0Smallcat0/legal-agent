"""Offline tests for the dense/hybrid retrieval module — the pure-function
parts only (RRF fusion). Embedding calls need a live Ollama and are exercised
by the measurement scripts, not by CI.

Run:  python -m pytest tests/test_dense.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.retrieval.dense import rrf_fuse  # noqa: E402

A = ("甲法", "第1條", "2020-01-01")
B = ("乙法", "第2條", "2020-01-01")
C = ("丙法", "第3條", "2020-01-01")


def test_rrf_rewards_agreement():
    # B appears at #2 in BOTH rankings; A and C appear only once (at #1).
    # 2/(60+2) > 1/(60+1): showing up in both lists beats one solo #1.
    fused = rrf_fuse([[A, B], [C, B]])
    assert fused[0] == B


def test_rrf_handles_disjoint_rankings():
    # keys missing from one ranking simply score nothing from it
    fused = rrf_fuse([[A], [B]])
    assert set(fused) == {A, B}


def test_rrf_is_deterministic_on_ties():
    # identical contributions -> stable tie-break by key, run to run
    assert rrf_fuse([[A], [B]]) == rrf_fuse([[A], [B]])
