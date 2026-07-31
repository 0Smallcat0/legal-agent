# Legal Agent

[![CI](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-403%20passing-brightgreen)

Legal Q&A where **every citation is machine-verified** against a time-versioned
statute corpus — and the verifier is itself graded by injecting errors:
**10,435/10,435 caught, 0 false positives.** Taiwan law, 2,560 articles +
1,367 real judgments, free on a local model.

<p align="center">
  <img src="docs/demo_web.png" alt="A real consultation: the model's analysis, the judgments citing those same articles with what each court ordered paid, and the action ladder" width="840">
</p>

<sub>The 8B model calls 民法§18/§195 irrelevant; right below it, three real judgments
decided under those very articles — one awarding 2,150,000–5,134,300 元, read
verbatim from its 主文. The weakest part is the model; the parts that must be
right are not left to it.</sub>

```bash
pip install -r requirements.txt
python app.py     # web demo — builds the corpus on first run, no API key
```

| measured, reproducible | |
|---|---|
| seeded defects caught (whole corpus) | **10,435/10,435, 0 false positives** |
| statute coverage, 30-case golden set | **100% pass+partial** (73% strict) |
| retrieval recall, real user wording | **336/341** |
| honesty tier / wrong-premise detection | **84% / 100%** |

Three things you can lift: a pure-code
[citation verifier](legal_agent/anti_hallucination/verifier.py) ·
[mutation-tested guardrails](legal_agent/evaluation/mutation.py) ·
[time-sliced retrieval](legal_agent/retrieval/retriever.py) that filters by date
before ranking.

[SPEC.md](SPEC.md) design · [RESULTS.md](evals/RESULTS.md) every number, method,
and the ones that went down · [DEPLOY_SPACES.md](docs/DEPLOY_SPACES.md) hosting

Personal engineering experiment, **not legal advice**. [MIT](LICENSE).
