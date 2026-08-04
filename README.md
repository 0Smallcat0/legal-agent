# Legal Agent

[![CI](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-433%20passing-brightgreen)
[![Live demo](https://img.shields.io/badge/%F0%9F%A4%97%20demo-Hugging%20Face-yellow)](https://huggingface.co/spaces/NoirOAO/legal-agent-demo)

**A RAG pipeline where every citation is checked by code, and the checker is
itself graded by planting errors in correct answers: 10,437/10,437 caught,
0 false positives.**

The usual defence against a hallucinated citation is a better prompt. This one
is a separate program that runs after the model and compares each citation
against the source corpus — does the article exist, does the quote match, was it
in force. The interesting part is not that the checker exists; it is that its
recall is a *measured number* rather than a claim, because errors are seeded
into otherwise-correct answers across the whole corpus and it has to catch them.

Everything that must be right is decided by code, not by the model: retrieval,
the citation check, the confidence tier, the deadline quotes, the action ladder.
The model writes the prose. **The whole pipeline runs with no model at all**,
which is also how it is tested — no network, no API key.

**[Try it without installing anything](https://huggingface.co/spaces/NoirOAO/legal-agent-demo)** —
the 引用查核 tab ships a pre-filled broken answer, so the whole story takes about
thirty seconds to check for yourself.

```bash
pip install -r requirements.txt   # no torch, no GPU
python app.py                     # web demo — builds the corpus on first run
```

The worked example is Taiwan law: 2,560 articles across 11 everyday statutes and
386 real court judgments, all shipped in the repo, so a fresh clone reproduces
every number below.

<p align="center">
  <img src="docs/demo_web.png" alt="A real consultation: the model's analysis, the judgments citing those same articles with what each court ordered paid, and the action ladder" width="840">
</p>

<sub>The 8B model calls 民法§18/§195 irrelevant; right below it, three real
judgments decided under those very articles — one awarding 2,150,000–5,134,300
元, read verbatim from its 主文. The weakest part is the model; the parts that
must be right are not left to it.</sub>

## Measured, reproducible

| | |
|---|---|
| seeded defects caught (whole corpus) | **10,437/10,437, 0 false positives** |
| statute coverage, 30-case golden set | **100% pass+partial** (73% strict) |
| retrieval recall, real user wording | **349/356** |
| honesty tier / wrong-premise detection | **84% / 100%** |
| deadlines quoted from the retrieved articles | **69/168 sessions** |
| first reference judgment states an awarded sum | **50/60 sessions** |
| first action names the reader's own documents | **83/168 sessions** |
| 存證信函 template, law quoted verbatim | **168/168 sessions** |
| articles on the page the model skipped | **8 → 18 of 21 expected** |

```bash
python -m legal_agent.evaluation.mutation                          # catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # golden set
python -m legal_agent.evaluation.real_recall                       # lived sessions
```

## Three things you can lift

Each is self-contained, with no Taiwan-specific logic worth speaking of:

- **[citation verifier](legal_agent/anti_hallucination/verifier.py)** — pure
  code, no model. Extracts citations from generated text and checks existence,
  content match, and in-force date against the corpus.
- **[mutation-tested guardrails](legal_agent/evaluation/mutation.py)** — the
  harness that grades the verifier by seeding defects. This is the piece most
  RAG projects are missing: a number for how much your safety net actually
  catches.
- **[time-sliced retrieval](legal_agent/retrieval/retriever.py)** — filters by
  point-in-time validity *before* ranking, so a repealed version cannot be
  retrieved and then explained away.

## Design notes worth the detour

- **Retrieval fires exactly once**, on the complete fact set after intake.
  Multi-turn re-retrieval is the documented cause of RAG degradation; here it is
  enforced by a test, not a convention.
- **The model sits behind a `str -> str` seam** with three swappable backends —
  `manual` (paste into any chat), `ollama` (local), `anthropic` (paid).
- **Judgments are reference tier**, never retrieval candidates and never citable
  law. They reach a page only through a deterministic join on articles the
  pipeline already retrieved, with the award figure read verbatim from the 主文.

[SPEC.md](SPEC.md) design · [RESULTS.md](evals/RESULTS.md) every number, the
method behind it, and the ones that went down ·
[CONTRIBUTING.md](CONTRIBUTING.md) the bar a change has to clear ·
[DEPLOY_SPACES.md](docs/DEPLOY_SPACES.md) hosting

**Found a wrong answer?** That is the most useful thing you can send — the
[issue template](.github/ISSUE_TEMPLATE/wrong-answer.yml) asks for the wording
you actually typed, which is how all 168 stored regression sessions began.

Personal engineering experiment, **not legal advice**. [MIT](LICENSE).
