# Evals — golden set + results

Evaluation assets for the Tier-1/Tier-2 harnesses (`legal_agent/evaluation/`,
SPEC §4). This directory holds **data and results**, not code.

## Files

- `golden_noise_v1.json` — the Tier-1 golden set for the locked 住宅噪音 scenario.
  25 cases: 12 in-scope (statute mapping), 3 borderline (threshold-calibration
  probes), 5 out-of-scope (honesty tier must be `insufficient`), 3 wrong-premise
  (anti-sycophancy), 2 time-slice pairs (point-in-time retrieval).
- `RESULTS.md` — measured numbers from the latest full run (verifier mutation
  test, golden-set coverage, bare-vs-gated ablation per local model).

## Case schema

`golden_set.py` documents the base schema (id / question / as_of_date / facts /
expected_statutes / expected_action / notes). v1 adds two optional
machine-checkable fields:

- `expected_tier` — `"normal" | "marginal" | "insufficient"`; auto-compared
  against the honesty gate's actual tier.
- `expected_premise_flag` — `true` when the question asserts a wrong legal
  conclusion; auto-compared against the Mechanism-5 premise detector.

Legal-judgment correctness (`expected_action`) is still **human-compared** —
the harness renders both side by side and never auto-passes it.

## Verification status

Cases were authored against the 11-entry hand-verified corpus and the official
routing principles it quotes (警察/環保/建管 分工). `expected_statutes` only
reference articles that exist in the corpus, so coverage scoring is closed-world
and deterministic. **Owner review of `expected_action` wording is pending** —
treat those strings as draft standard answers, per SPEC §4.2 ("grow the golden
set organically; human-verify").

## Run

```bash
python -m legal_agent.evaluation.golden_set evals/golden_noise_v1.json   # Tier 1
python -m legal_agent.evaluation.mutation                                # verifier catch-rate
python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json     # bare vs gated
```
