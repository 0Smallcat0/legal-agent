# evals/ — case files and results

Data and write-ups for the harnesses in `legal_agent/evaluation/`; no code lives
here. The command for each harness, and which need a model, is in
[`CONTRIBUTING.md` → The harnesses](../CONTRIBUTING.md#the-harnesses).

## Write-ups

- [`RESULTS.md`](RESULTS.md) — the current numbers (§1 is the single source of
  truth), the limits, and the changes that were measured and NOT shipped.
- [`HISTORY.md`](HISTORY.md) — how each number was arrived at, in the order it
  happened.

## Case files

| file | what it holds | loaded by |
|---|---|---|
| `golden_v2.json` | the 32-case golden set: statute coverage, expected tier, wrong-premise flag | `golden_set`, `calibrate`, `ablation`; `tests/test_coverage_gate.py` |
| `golden_noise_v1.json` | the original 25-case 住宅噪音 set from the 11-article corpus, kept so the archive baselines in HISTORY.md still reproduce | `tests/test_eval_suite.py`; any harness taking a golden path |
| `real_sessions.json` | 168 problems typed the way people type them, each with its expected articles | `real_recall`, `judgment_relevance`; `tests/test_coverage_gate.py`, `tests/test_eval_suite.py`, `tests/test_judgment_relevance.py` |
| `honesty_probe_v1.json` | 35 cases: 20 out of scope (statute verified absent from the corpus), 15 in scope but lexically thin | `honesty_probe` |
| `realworld_v1.json` | 41 ended disputes from 4 government case tables, labelled by the deciding body's own 法令依據 column (or marked `derived`), with blind-coded `outcome_direction` where it exists | `realworld` |
| `realworld_answers_run1.json` | 24 generated answers (llama3.1, temperature 0) carrying deliberately no outcome — the input to the blind answer coding | nothing; kept as the record the coding was made from |
| `realworld_answer_coding_run1.json` | the blind coding of those 24 answers | `realworld --direction` |
| `blindspots_v1.json` | 25 frozen cases the seeded-error generator cannot express | `blindspots`; `tests/test_verifier.py` |
| `blindspots_positive_control_v1.json` | 6 positive controls for the same suite | `blindspots`; `tests/test_verifier.py` |
| `ablation_v2.json` | per-case output of the published bare-vs-gated run (llama3.1, golden_v2, 64 rows) | nothing; written by `ablation --out` |
| `ablation_raw.json` | the 11-article-era ablation (llama3.1 and qwen3 over golden_noise_v1, 100 rows) | nothing; written by `ablation --out` |

## Case schema

`golden_set.py` documents the base schema (id / question / as_of_date / facts /
expected_statutes / expected_action / notes) and two machine-checked fields:
`expected_tier` (`"normal" | "marginal" | "insufficient"`) and
`expected_premise_flag`. `expected_statutes` only name articles that exist in the
corpus, so coverage scoring is closed-world and deterministic.

Legal-judgment correctness (`expected_action`) is **human-compared** — the
harness prints both side by side and never auto-passes it.
