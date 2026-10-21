# Legal Agent

[![CI](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![Live demo](https://img.shields.io/badge/%F0%9F%A4%97%20demo-Hugging%20Face-yellow)](https://huggingface.co/spaces/NoirOAO/legal-agent-demo)

**A RAG pipeline where every citation is checked by code — and the checker is
itself graded, by planting errors into correct answers and counting what it
catches.**

The usual defence against a hallucinated citation is a better prompt. Here it is
a separate program that runs after the model and compares each citation with the
source corpus: does the article exist, does the quote match, was it in force on
that date. Everything that must be right — retrieval, the citation check, the
confidence tier, the deadlines quoted — is decided by code; the model only
writes the prose, and the whole pipeline also runs with no model at all.

**[Try it in the browser](https://huggingface.co/spaces/NoirOAO/legal-agent-demo)** —
the 引用查核 tab ships a pre-filled broken answer; checking it takes thirty seconds.

```bash
pip install .                     # no torch, no GPU; the corpus ships inside
```

```python
import legal_agent

for r in legal_agent.verify("依社會秩序維護法第72條,深夜喧嘩可處新臺幣六萬元以下罰鍰。"):
    print(r.flagged, r.reason)
# True  主張金額 [60000] 元未見於條文(條文金額 [10000])
```

No clone, key, model or network: the database builds itself from the packaged
corpus on first call. `as_of="2024-06-01"` checks the law as it stood that day.
The worked example is Taiwan law — 3,758 articles across 18 everyday statutes
and 435 real court judgments, all in the repo, so a fresh clone reproduces every
number below.

## Four numbers, and what each does not say

| | measured | what it does NOT say |
|---|---|---|
| **The checker** — errors planted into correct answers, across the whole corpus | **100% caught in each of 24 kinds, 0/3,758 false positives** | Green means the article exists, is in force and was not misquoted. It never meant the article governs your problem. |
| **Against the bare model** — the same model with and without the pipeline | citations a reader would have to take on trust: **67% → 5%** (llama3.1, golden set) | The gated delta sits inside the harness's run-to-run spread; the 67% reproduces. qwen2.5:7b, one sample: 33% → 2.9%, and 13% of its bare citations name a law that does not exist. Not measured against a frontier model. |
| **On disputes it has never seen** — government case tables, governing article taken from the authority's own 法令依據 column, never tuned against | right article in the window **12/23**; answer points the opposite way to the recorded outcome **3/16** | On the case table it was tuned against, the same measure reads 25/27. 12/23 is the honest figure for new territory. |
| **Catching those wrong-way answers** — 5 blind-coded inversions vs 11 agreements, checker never sees the outcome | four local LLM judges (Prometheus 2, JudgeLM, Qwen2.5, Llama3.1): **0/5 caught, or 3–5/5 only by also flagging 8–11 of the 11 right answers**. No-model 主文/理由 direction-word check: **2/5 caught, 1/11 false** | Neither ships. The word check's split is within chance at this size (one-sided p = 0.21), and what it catches is the model mislabelling 對方, not wrong law. Nothing here catches a wrong-way answer yet. |

Every other number — retrieval recall 349/356 on 168 real sessions, honesty and
refusal rates, the reference-judgment acceptance set (87% of judgments shown are
ones the question should cite, 84% held out) — is in
[`evals/RESULTS.md` §1](evals/RESULTS.md), each with the harness that produces it
and the ones that went down. Retrieval reaches 349/356 only with the optional
bge-m3 index (`ollama pull bge-m3 && python -m legal_agent.retrieval.dense`);
a plain install is lexical only and reads 321/356.

<p align="center">
  <img src="docs/demo_web.png" alt="A real consultation: the model's analysis, the judgments citing those same articles with what each court ordered paid, and the action ladder" width="840">
</p>

<sub>The 8B model calls 民法§18/§195 irrelevant; right below it, three real
judgments decided under those very articles, the award read verbatim from the
主文. The weakest part is the model; the parts that must be right are not left
to it.</sub>

## Three things you can lift

- **[citation verifier](legal_agent/anti_hallucination/verifier.py)** — pure code,
  no model: extracts citations from generated text and checks existence, content
  and in-force date against the corpus.
- **[mutation-tested guardrails](legal_agent/evaluation/mutation.py)** — grades
  the verifier by seeding defects. The piece most RAG projects are missing: a
  number for how much the safety net actually catches.
- **[time-sliced retrieval](legal_agent/retrieval/retriever.py)** — filters by
  point-in-time validity *before* ranking, so a repealed version cannot be
  retrieved and then explained away.

## More

[RESULTS.md](evals/RESULTS.md) every number, its harness, and the ones that went
down · [SPEC.md](SPEC.md) design · [CONTRIBUTING.md](CONTRIBUTING.md) the bar a
change has to clear · [AGENTS.md](AGENTS.md) the same plus the measurement traps ·
[DEPLOY_SPACES.md](docs/DEPLOY_SPACES.md) hosting · [CHANGELOG.md](CHANGELOG.md)
what changed

```bash
pip install .[demo] && python app.py                     # the demo, locally
python -m legal_agent.evaluation.mutation                # the checker's catch rate
python -m legal_agent.evaluation.realworld --direction   # disputes it has never seen
```

**Found a wrong answer?** The [issue template](.github/ISSUE_TEMPLATE/wrong-answer.yml)
asks for the wording you actually typed — that is how all 168 stored regression
sessions began.

Personal engineering experiment, **not legal advice**. [MIT](LICENSE).
