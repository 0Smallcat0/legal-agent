"""Evaluation harnesses — every published number in evals/RESULTS.md has one here.

Deterministic, no model: mutation, blindspots, qualifier_audit, real_recall,
honesty_probe, judgment_relevance, realworld, calibrate (stub answers).
Call a real model: golden_set, ablation, mutation --semantic, realworld --answers.
"""
from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator


def enable_utf8_stdout() -> None:
    """Make CJK and box-drawing output safe on a cp950/cp1252 Windows console,
    which otherwise dies with UnicodeEncodeError at the end of a long run."""
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def assert_nonzero_scan(count: int, label: str) -> None:
    """Raise ValueError when a scan found ZERO of what it counts.

    A regex that quietly breaks returns nothing, and an empty result renders as
    a perfect 100%/0-false-positive scorecard. Zero means the scan is broken.
    """
    if count == 0:
        raise ValueError(
            f"{label}: 掃到 0 個 token — 一律視為腳本或正則壞掉,不得當成無異常通過"
        )


def print_corpus_fingerprint(db_path=None):
    """Say which corpus this run reads, and ABORT if it is below the floor.

    Every harness here prints a number, and a number is only as good as the
    corpus behind it. Two agents have already published figures computed
    against the wrong database, in both cases with nothing on screen naming
    which one they had opened.

    Below the floor aborts rather than warns, for the same reason
    `realworld.check_labels` does: a corpus that cannot hold the article and a
    label the corpus cannot match are one failure, and it renders as a
    confident wrong number, not as an error. Above the floor is fine and
    prints as-is — an overnight harvest legitimately accumulates judgments.
    """
    from legal_agent.data.bootstrap import corpus_fingerprint, ensure_corpus

    ensure_corpus(db_path)
    fingerprint = corpus_fingerprint(db_path)
    print(fingerprint.render())
    return fingerprint.require_floor()


@contextlib.contextmanager
def corpus_connection(conn=None) -> Iterator:
    """Yield `conn` as given, or a connection to the default corpus that is
    closed afterwards when none was passed."""
    if conn is not None:
        yield conn
        return
    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    own = connect(DB_PATH)
    try:
        yield own
    finally:
        own.close()
