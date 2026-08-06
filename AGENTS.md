# Working on this repo as an agent

Read this before running anything. It is short on purpose; the long version is
[`CONTRIBUTING.md`](CONTRIBUTING.md) (the rules) and
[`evals/RESULTS.md`](evals/RESULTS.md) (every number and every failure).

## What this project is

A RAG pipeline whose citations are checked by code, where the checker itself has
a measured recall. Taiwan law is the worked example, not the point. Every
published figure has a runnable harness behind it, and **a change ships when a
number moves**.

## The rule that governs every change

1. Say which published number your change moves, and by how much.
2. If it moves none, that is a fine result — write it into `evals/RESULTS.md`
   under "Measured, then NOT shipped" and do not ship it.
3. Never edit an expected value to make a case pass.
4. **Measure the instrument's own spread before publishing a delta.** A number
   from one sample of a noisy harness is not an effect. This file exists partly
   because that mistake reached the README once.

## Setup

```bash
pip install .          # library: verify + retrieval. 3 deps, no GPU, ~30s
pip install .[dev]     # + pytest and ruff
python -m pytest -q    # 474 tests, ~45s
```

The corpus ships inside the package and the database builds itself on first
call. No key, no model, no network needed for the library or the tests.

`LEGAL_AGENT_PROVIDER=manual` runs the CLI with no model at all (it prints the
assembled prompt for you to paste into any chat). The default is `ollama`.

## Traps that have each cost a day

Every one of these produced a wrong number that was believed for a while.

1. **The database is NOT in the repo.** It lives at `LEGAL_AGENT_HOME` (default:
   the platform per-user data dir). Deleting the repo does not reset it, and a
   test run and a CLI run share it.
2. **Dense retrieval fails SILENTLY.** Without Ollama + `bge-m3` +
   `python -m legal_agent.retrieval.dense`, hybrid retrieval degrades to pure
   BM25 and recall drops 348/356 → 320/356 with no error. The harnesses print
   `dense_fallbacks`; **confirm it is 0 before comparing any number to a
   published one.**
3. **The golden-set grader must run at temperature 0.** At 0.2 the same code
   scored 73.1–80.8% across five runs — a spread larger than any effect worth
   measuring. One of those rolls was published and had to be retracted.
4. **`DEFAULT_K` is bound at function definition time.** Reassigning the module
   constant at runtime is a no-op; edit the source.
5. **Statutory vocabulary must be copied verbatim from the corpus.**
   `test_every_statutory_term_appears_verbatim_in_the_corpus` enforces it for
   `retrieval/lexicon.py`. The coverage table in
   `anti_hallucination/coverage.py` holds the INVERSE invariant — every statute
   it names must be absent from the corpus — so it self-destructs when the
   corpus catches up.
6. **The ablation harness's 「未回溯」 column is not comparable across rows.** The
   bare arm is scored against the whole corpus, the gated arm against that run's
   retrieval window. Only the `flagged` column can be compared directly.
7. **Check that a harness is reading a populated field.** A held-out check once
   scored a clean 0/386 against a column that is empty in all 386 rows. It was
   measuring nothing.
8. **The semantic 4th axis fails in the FLATTERING direction.** It answers
   「consistent」 on every failure path — including an Ollama that is not running
   — so an outage renders as 0 false positives, not as an error. A measurement
   of 9 planted subject swaps and 120 controls came back 0/0 that way.
   `semantic_unreached_count()` now counts those and `mutation --semantic`
   prints a warning; **confirm it is 0 before believing any 4th-axis number.**

## The harnesses

```bash
python -m legal_agent.evaluation.mutation                          # verifier recall
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # statute coverage (needs a model)
python -m legal_agent.evaluation.real_recall                       # 168 real sessions
python -m legal_agent.evaluation.honesty_probe                     # refuse / false-refuse
python -m legal_agent.evaluation.judgment_relevance                # reference tier
python -m legal_agent.evaluation.calibrate evals/golden_v2.json    # threshold sweep
```

`mutation`, `real_recall`, `honesty_probe` and `judgment_relevance` need no LLM
and are deterministic.
`golden_set` and `ablation` call a real model and are not.

## Before you propose a change

`CONTRIBUTING.md` calls this the scope check, and it is three questions:

- Is this a defect measured in real use, or a hunch?
- Which published number will move?
- Does it need a new file?

`evals/RESULTS.md` has a long list of changes that looked obviously right and
lost on the numbers. Read it before re-proposing one of them — dense cosine as
an out-of-scope signal, per-statute caps on the retrieval window, and telling
the model to walk the retrieved list are all in there, with the measurements
that killed them.
