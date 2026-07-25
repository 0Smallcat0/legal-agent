# Legal Agent

[![CI](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-238%20passing-brightgreen)

Ask a legal question in plain Chinese. Every citation in the answer is
**machine-verified against a time-versioned statute corpus** — it exists, the
claim matches its verbatim text, it was in force — and the guardrails doing that
checking are themselves graded by injecting errors on purpose:
**10,435/10,435 seeded defects caught, 0 false positives.**

Professional legal AI hallucinates 17–33% of the time (Stanford, 2025). The bet
here isn't zero errors — it's **errors you can see.**

Taiwan law: 2,560 articles across 11 everyday statutes, plus 1,367 real court
judgments as reference. Runs free on a local model. The engine is
jurisdiction-agnostic — swap the data, keep the gates.

<p align="center">
  <img src="docs/demo_web.png" alt="A real consultation: the model's analysis, the reference judgments citing the same articles with what each court ordered paid, and the low-cost-first action ladder" width="840">
</p>

<sub>A real consultation. The 8B model's prose (marked 模型推論) waves 民法§18/§195
away as 「似乎與噪音問題無直接關係」 — and directly beneath it the deterministic layer
lists three actual judgments decided under those very articles, one awarding
2,150,000–5,134,300 元, read verbatim from its 主文. The weakest component is the
model; the parts that must be right are not left to it.</sub>

## Try it

```bash
pip install -r requirements.txt
python app.py                 # web demo — builds the corpus on first run, no API key
python -m legal_agent.run     # or the terminal version
```

A free local model via [Ollama](https://ollama.com) (`ollama pull llama3.1`) is
the default: it conducts the interview and writes the 分析研判 narrative. Without
one, everything deterministic — retrieval, the gates, verbatim statutes, the
action ladder — still runs.

## What's different

**Citations are verified by code, not by another model.**
[`verifier.py`](legal_agent/anti_hallucination/verifier.py) is a pure function:
exists / content-matches / in-force, per citation, with the corpus text attached
to anything it flags.

**The guardrails are mutation-tested.**
[`mutation.py`](legal_agent/evaluation/mutation.py) plants fabricated statutes,
ghost article numbers, wrong amounts, swapped periods and out-of-force dates
across the whole corpus and measures the catch rate. Three defect classes each
started at 0% — finding that is the point of running the exam.

**Retrieval is time-sliced.** Statutes are keyed by
`(statute_id, article_no, effective_from)` and the point-in-time filter runs
*before* ranking, so a repealed version is never even a candidate.

## Measured (local models, $0 — all reproducible)

| | |
|---|---|
| Seeded-defect catch rate, every article in the corpus | **10,435/10,435 (100%), 0/2,560 false positives** |
| Statute coverage, 30-case golden set (llama3.1 8B, gated) | **100% pass+partial** (73% strict) |
| Retrieval recall on nine problems typed the way people type them | **19/20 (95%)** |
| Honesty tier / wrong-premise detection | **90% / 100%** |

[`evals/RESULTS.md`](evals/RESULTS.md) has the method, the failures, and the
numbers that went *down* — including the week the insufficiency gate was dead and
answered a crypto-tax question with 刑法§196 (行使偽造貨幣).

```bash
python -m legal_agent.evaluation.mutation                          # catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # golden set
python -m legal_agent.evaluation.real_recall                       # lived sessions
```

## More

[`SPEC.md`](SPEC.md) — design, architecture, scope ·
[`evals/RESULTS.md`](evals/RESULTS.md) — every number and how it was taken ·
[`docs/DEPLOY_SPACES.md`](docs/DEPLOY_SPACES.md) — free hosting

## Disclaimer

A personal-use engineering experiment. **Not legal advice**, not a substitute for
a lawyer, not affiliated with any government body. Statute text is quoted
verbatim from official public sources.

## License

[MIT](LICENSE).
