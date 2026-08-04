"""Taiwan Legal Agent — a personal-use R.O.C. (Taiwan) legal assistant.

Package layout mirrors the layers in SPEC.md, which carries the full mapping:

    data/               §1   time-sliced statute corpus + judgment harvester
    retrieval/          §2.2 hybrid retrieval, point-in-time filtered
    anti_hallucination/ §2   the five-gate defense
    dialogue/           §3   four-stage clinic flow
    evaluation/         §4   golden set, mutation test, calibration, recall
"""
