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
