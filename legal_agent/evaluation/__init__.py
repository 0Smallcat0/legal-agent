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
