"""Evaluation layer (spec §4) — converts "feels about right" into numbers.

Even professional legal tools hallucinate 17-33%; without measurement you cannot
know whether YOUR rate is 20% or 60%. Fluency and correctness are uncorrelated,
so "it answers fluently" is the most dangerous state.

    Tier 1  Golden Set ............ golden_set.py          (mandatory)
    Tier 2  Hallucination check ... hallucination_check.py (strongly recommended;
                                     reuses anti_hallucination/verifier.py)
    Tier 3  Red-teaming ........... ad hoc (spec §4.2), no module

STATUS: Tier 1 & 2 harness implemented; the golden-set CONTENT (~20-30 verified
Q&A) is still to be authored.
"""
from __future__ import annotations

import contextlib
import sys


def enable_utf8_stdout() -> None:
    """Make CJK and box-drawing output safe on a cp950/cp1252 console.

    Every harness here prints Chinese, and the scorecards carry 「⚠」. On a
    Windows console the golden-set runner completed a full ten-minute evaluation
    and then died with `UnicodeEncodeError: 'cp950' codec can't encode character
    '\\u26a0'` — the work done, the number lost, on a command both README and
    CONTRIBUTING tell people to run. `cli.py` and `run.py` already did this; the
    eval entry points did not.
    """
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def assert_nonzero_scan(count: int, label: str) -> None:
    """Abort when a scan found ZERO of what it was looking for.

    Every harness added for the blind-spot round walks some corpus / answer /
    journal text and counts a token — citations, paragraph markers, item
    markers, rejected Tier-3 qualifiers, mutants generated for a new class...
    A regex or a generation condition that quietly breaks does not raise; it
    just returns nothing, and an empty result renders as a perfect, if
    fictitious, 100%/0-false-positive scorecard. This project already lost one
    measurement to exactly that shape of silence (see `require_floor` above,
    and the mutation-test docstring's note on `semantic_unreached`), so zero
    is never read as "no anomalies" here — it is read as "the scan itself is
    broken" and must stop the run, not pass it.

    Args:
        count: how many tokens the scan found.
        label: what was being scanned, for the error message.

    Raises:
        ValueError: if `count` is 0.
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
