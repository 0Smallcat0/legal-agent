"""Taiwan Legal Agent — a personal-use R.O.C. (Taiwan) legal assistant.

Package layout mirrors the layers in the engineering spec
(taiwan-legal-agent-spec.md); see README.md for the full mapping:

    data/               §1   data layer — time-sliced corpus     [built · data loaded]
    retrieval/          §2.2 Mechanism 1 / build step 2          [built]
    anti_hallucination/ §2   the five-gate defense (Mech. 2-5)   [built]
    dialogue/           §3   four-stage "clinic-style" flow      [built]
    evaluation/         §4   golden set + hallucination check    [harness built]

STATUS: all six build steps implemented and unit-tested (see README.md). Not yet
run live: the runtime model is dependency-injected but config.MODEL is still a
placeholder, and the corpus holds a small single-scenario (住宅噪音) dataset.
"""
