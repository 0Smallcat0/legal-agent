"""Anti-hallucination layer (spec §2) — the five-gate defense.

    Gate 1  Retrieval-first .......... retrieval/ (Mechanism 1)
    Gate 2  Citation verifier ........ verifier.py        (Mechanism 2)
    Gate 3  Three-tier honesty ....... honesty.py         (Mechanism 3)
    Gate 4  法條 / 研判 separation .... answer_structure.py (Mechanism 4)
    Gate 5  Anti-sycophancy .......... sycophancy.py      (Mechanism 5)

All tuned to the MOST conservative setting (spec §2.1): the achievable goal is
not zero errors but "when it errs, the user knows." STATUS: all five gates
implemented.
"""
