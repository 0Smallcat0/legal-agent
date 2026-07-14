# Measured results — 2026-07-10

Environment: local, zero paid API. Models via Ollama on an RTX 4060 (8 GB);
corpus = the 11-entry hand-verified 住宅噪音 reference corpus; golden set =
[`golden_noise_v1.json`](golden_noise_v1.json) (25 cases).

**Closed-world caveat** (applies to every table): "unverifiable / corpus 查無"
means *not traceable to this corpus* — which is exactly the promise the system
makes ("every citation must be verifiable back to the corpus") — it does NOT
claim the statute doesn't exist in the real world.

---

## 1. Verifier mutation test — catch rate on planted errors

Deterministic (no LLM). Answers are generated from real corpus rows with one
planted defect each; the verifier must flag every defect and none of the
correct controls. `python -m legal_agent.evaluation.mutation`

| type | planted | caught | note |
|---|---|---|---|
| control (correct citation + correct amount) | 10 | — | **0 false positives** |
| nonexistent_article (第X+500條) | 10 | 10 | exists-axis |
| wrong_amount (×10 金額) | 10 | 10 | content-match axis |
| out_of_force (as-of 生效日前一天) | 10 | 10 | in-force axis |
| fake_statute (虛構法名) | 1 | 1 | exists-axis |
| **total mutations** | **31** | **31 (100%)** | false-positive rate **0%** |

## 2. Tier-1 golden set — llama3.1 8B through the full gated pipeline

`python -m legal_agent.evaluation.golden_set evals/golden_noise_v1.json`
(auto-scored axes only; legal-judgment wording is human-compared by design)

| axis | result |
|---|---|
| 法條涵蓋 (19 scorable cases) | **pass 11 / partial 5 / miss 3** — strict 58%, pass+partial 84% |
| 誠實分級 accuracy (25) | **21/25 (84%)** |
| 前提偵測 accuracy (25, Gate 5) | **25/25 (100%)** |
| out-of-scope refusal (5 cases) | **5/5** short-circuited to `insufficient` |

Coverage gaps (each missing statute was neither retrieved top-5 nor cited):
in-04 缺§3(定義條), in-05 缺§9, in-06 缺§195, in-12 缺§793, ts-01 缺§6;
mg-02 / wp-02 / wp-03 全缺。These are retrieval-recall gaps on sparse fact
wording — the documented next step is hybrid (dense) retrieval.

Tier misses: the 3 borderline probes (mg-01/02/03) and wp-03 scored BM25
15.4–29.4, interleaved with true in-scope cases → graded `normal`, not
`marginal`. (A previous fourth miss — **oos-01 漏水 leaking past the honesty
gate at top BM25 3.89** — is fixed by the calibrated `insufficient` floor
below.)

**What the golden set caught while being built:** out-of-scope questions
initially matched half the corpus through single-character function-word
tokens (的/與) in jieba's output — a real retriever defect, fixed in
`retriever._tokenize` (drop 1-char CJK word tokens; bigrams keep the signal),
all tests green after the fix.

## 3. Honesty-threshold calibration

`python -m legal_agent.evaluation.calibrate evals/golden_noise_v1.json`

The score distribution shows a clean gap at the bottom: the out-of-scope leak
(oos-01) tops out at BM25 **3.89** while the weakest in-scope case scores
**9.65**. `honesty.INSUFFICIENT_SCORE_THRESHOLD = 6.0` (the geometric midpoint)
now short-circuits anything below it as `insufficient` — out-of-scope refusal
5/5, no in-scope case affected.

Above that floor the sweep is unchanged: default marginal threshold 1.5 → 84%
tier accuracy; **best possible marginal threshold → also 84%**. The remaining
misses (marginal probes at 15.4–29.4, interleaved with true in-scope cases)
are not linearly separable by any BM25 cutoff — quantified evidence that the
marginal/normal distinction needs a better relevance signal (hybrid retrieval
/ score normalization), not more threshold tuning.

## 4. Ablation — bare (憑記憶引用) vs gated (五閘門), per model

`python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json --models llama3.1:latest qwen3:latest`

Same 25 questions. **bare** = the question sent straight to the model, asked to
cite applicable statutes from memory (what a raw chatbot gives you). **gated** =
the full five-gate pipeline. Every citation in both conditions is checked
against the corpus on all three axes.

| model | condition | citations | traceable to corpus | flagged & shown to user |
|---|---|---|---|---|
| llama3.1 8B | bare | 12 | 0 (**0%**) | — (no verifier in this condition) |
| llama3.1 8B | gated | 83 | 58 (70%) | **25 (30%), each with the verbatim article attached** |
| qwen3 8B | bare | 76 | 4 (**5%**) | — |
| qwen3 8B | gated | 126 | 76 (60%) | **50 (40%), each with the verbatim article attached** |

All flags in both conditions were exists-axis (corpus 查無); no wrong-amount or
out-of-force citations were produced this run. Honesty-tier distribution under
gated was **identical for both models** (insufficient 4 / normal 21) — the tier
is decided *before* the LLM runs, from retrieval scores alone, so it cannot
vary by model. Zero case-runs errored.

Reading the table:

- **Bare, the user has no trail.** 95–100% of memory-cited statutes cannot be
  traced to any vetted source. (Closed-world: some are real statutes outside
  the 11-entry corpus, some are fabrications — *the user cannot tell which*,
  and that indistinguishability is precisely the hallucination problem.)
- **Gated, small 8B models still over-reach** — 30–40% of their citations go
  beyond the supplied verbatim articles despite the "cite only what I supply"
  instruction. The pipeline does not pretend otherwise: every such citation is
  flagged inline with the corpus original for comparison. *The model errs; the
  user knows.* A stronger model lowers the flagged rate; the gates are
  identical regardless of backend.

---

## Reproduce

```bash
python -m pytest -q                                                    # 134 tests
python -m legal_agent.evaluation.mutation                              # table 1
python -m legal_agent.evaluation.golden_set evals/golden_noise_v1.json # table 2
python -m legal_agent.evaluation.calibrate evals/golden_noise_v1.json  # table 3
python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json --models llama3.1:latest qwen3:latest --out evals/ablation_raw.json
```

Raw per-run ablation data: [`ablation_raw.json`](ablation_raw.json).
