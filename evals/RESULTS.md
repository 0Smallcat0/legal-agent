# Measured results

Local, zero paid API. Models via Ollama on an RTX 4060 (8 GB). Corpus: 2,560
articles across 11 everyday-law statutes + 1,367 harvested judgments.
Last full run: 2026-07-25.

**Closed-world caveat**: "not traceable to the corpus" is exactly the promise the
system makes — it never means "this statute does not exist."

## Current numbers

| what | number | harness |
|---|---|---|
| seeded defects caught, every article | **10,435/10,435 (100%), 0/2,560 false positives** | `evaluation/mutation.py` |
| statute coverage, 30-case golden set | **pass 19 / partial 7 / miss 0** of 26 scorable — 100% pass+partial, 73% strict | `evaluation/golden_set.py` |
| honesty tier | **27/30 (90%)** | same run (decided from retrieval scores, so model-independent) |
| wrong-premise detection | **30/30 (100%)** | same run |
| retrieval recall, real user wording | **19/20 (95%)** | `evaluation/real_recall.py`, 9 lived problems |
| reference judgments beside an answer | 11/30 cases, 10 carrying a 主文 award figure | counted, never scored |
| bare model vs gated, memory-cited statutes traceable | 0–5% → 30–40% flagged | **STALE** — measured on the 11-article corpus, not re-run at v2 scale |

```bash
python -m legal_agent.evaluation.mutation                          # catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # golden set
python -m legal_agent.evaluation.real_recall                       # lived sessions
python -m legal_agent.evaluation.calibrate evals/golden_v2.json    # threshold sweep
```

## What each harness refuses to measure

- **Mutation test** grades the *verifier's* recall, not the model's. Errors are
  planted in otherwise-correct answers over every article in the corpus.
- **Golden set** auto-scores statute coverage only. Legal correctness is printed
  side by side for a human — a harness that auto-passed legal judgement would be
  the same sin the project exists to avoid.
- **Real-session recall** measures retrieval alone, from the user's own words, so
  the number does not depend on how well the intake performed that day.
- **Judgments** are counted, never scored: there is no ground truth for "the
  right judgment," and inventing one would poison the layer.

## Honest limits

- **marginal vs normal is not separable by BM25.** The score ranges overlap
  (marginal 85–268, normal 126–331), and all three remaining tier misses are
  this. That needs a better relevance signal, not a better constant — dense
  cosine was measured as a candidate and interleaves the same way.
- **Judgment coverage is thin exactly where it matters.** Of 1,367 harvested,
  386 (28%) cite an article in our corpus, and the thinnest domains are the
  everyday ones (租賃住宅條例 2, 消保法 4). A day's civil feed is 交通損賠 /
  票款 / 借款.
- **Historical statute versions**: the corpus carries one true historical slice.
  "Which version applied in 2024?" is answerable in mechanism, not yet in data.
- **The 8B model is the weakest component** and is treated that way: it repeats
  itself on long article lists and uses only part of what it is given. What must
  be right — citations, judgments, the tier — is not left to it.
- **The ablation row is stale** (see the table).

## Measured, then NOT shipped

Each of these looked obviously right and lost on the numbers:

- **per-statute cap on the retrieval window** — one statute really does flood it
  (7 of 8 seats), but capping loses on both harnesses, because real answers
  legitimately cluster inside one code (民法§354+§359).
- **dense cosine as the insufficiency signal** — scale-comparable across queries,
  so it should have beaten raw BM25; the out-of-scope cases are the three lowest
  but the weakest in-scope case sits between them.
- **「同法第X條」 anaphora resolution in judgments** — 61 of 425 resolve, and
  **0 judgments become newly usable**.
- **query-term weighting**, and the **first lexicon design** (expansion terms
  entering the match decision, which manufactured false hits).

## More

[`HISTORY.md`](HISTORY.md) — how each number was arrived at: the three defect
classes that started at 0%, the data bug the exam caught before a human did, and
the week the insufficiency gate was dead. ·
[`golden_v2.json`](golden_v2.json) · [`real_sessions.json`](real_sessions.json) ·
[`README.md`](README.md) — case schema and provenance.
