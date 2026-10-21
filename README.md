---
title: Legal Agent Demo
emoji: ⚖️
colorFrom: indigo
colorTo: gray
sdk: gradio
sdk_version: 6.20.0
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
short_description: Legal RAG with a citation verifier graded on 24 error kinds
startup_duration_timeout: 1h
preload_from_hub:
  - Qwen/Qwen2.5-7B-Instruct
  - BAAI/bge-m3
---

# Legal Agent

[![CI](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![Live demo](https://img.shields.io/badge/%F0%9F%A4%97%20demo-Hugging%20Face-yellow)](https://huggingface.co/spaces/NoirOAO/legal-agent-demo)

**A RAG pipeline where every citation is checked by code, and the checker is
itself graded by planting errors in correct answers: 100% caught across
twenty-four error kinds, 0/2,921 false positives — with the kinds it cannot plant
named rather than left out of the denominator.**

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
pip install .                     # no torch, no GPU; the corpus ships inside
```

```python
import legal_agent

for r in legal_agent.verify("依社會秩序維護法第72條,深夜喧嘩可處新臺幣六萬元以下罰鍰。"):
    print(r.flagged, r.reason)
# True  主張金額 [60000] 元未見於條文(條文金額 [10000])
```

That is the whole setup. The database builds itself from the corpus inside the
package on first call — no clone, no key, no model, no network. `verify` is pure
Python, so it cannot be argued out of a verdict. Pass `as_of="2024-06-01"` to
check the law as it stood on a date rather than today.

To run the demo from a clone instead:

```bash
pip install .[demo] && python app.py
```

The worked example is Taiwan law: 2,921 articles across 16 everyday statutes, all
in force (plus one repealed historical version, kept for point-in-time queries),
and 386 real court judgments, all shipped in the repo, so a fresh clone
reproduces every number below.

<p align="center">
  <img src="https://raw.githubusercontent.com/0Smallcat0/legal-agent/main/docs/demo_web.png" alt="A real consultation: the model's analysis, the judgments citing those same articles with what each court ordered paid, and the action ladder" width="840">
</p>

<sub>The 8B model calls 民法§18/§195 irrelevant; right below it, three real
judgments decided under those very articles — one awarding 2,150,000–5,134,300
元, read verbatim from its 主文. The weakest part is the model; the parts that
must be right are not left to it.</sub>

## Measured, reproducible

A subset of the table in [`evals/RESULTS.md` §1](evals/RESULTS.md), copied from
it; that table also names the harness behind every row.

| what | number |
|---|---|
| seeded defects caught | **100% in each of 24 kinds, 0/2,921 false positives** — per-kind denominators in RESULTS §4 |
| statute coverage, 32-case golden set | **pass 19 / partial 7 / miss 0** of 26 scorable — 100% pass+partial, 73% strict |
| retrieval recall, real user wording | **348/356 (98%)**, 5.9 unexpected articles per session |
| honesty tier | **29/32 (91%)** |
| wrong-premise detection | **32/32 (100%)** |
| out-of-scope refused / in-scope falsely refused | **18/20 · 2/15** — both directions, because only measuring the first hid the second |
| deadlines quoted from the retrieved articles | **69/168 sessions** |
| first reference judgment states an awarded sum | **50/60 sessions** (shipped corpus; 54/60 on the full local harvest) |
| that judgment is the same KIND of dispute as the question | **51/88 scorable (58%)**, 146/168 sessions carry one, 58/146 案由 too generic to tell |
| first action names the reader's own documents | **83/168 sessions** |
| 存證信函 template, law quoted verbatim | **168/168 sessions** |
| articles on the page the model skipped | **8 → 18 of 21 expected** |
| the article the AUTHORITY cited — cases tuned on | **25/27**, 0 of 16 answered with none of them (first run, before tuning: 7/27 and 9/16) |
| the same thing, on 17 cases **held out** | **12/23**, 5 of 17 answered with none of them |

```bash
python -m legal_agent.evaluation.mutation                          # catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # golden set
python -m legal_agent.evaluation.real_recall                       # lived sessions
python -m legal_agent.evaluation.judgment_relevance                # reference tier
python -m legal_agent.evaluation.realworld                         # already-ended disputes
```

Every harness, and which ones need a model:
[CONTRIBUTING.md → The harnesses](CONTRIBUTING.md#the-harnesses).

**Read the last two rows before you trust the first one.** Every other number here
is measured against expectations this project wrote — the same hand built the
retriever and the answer key. These two are not: the cases are government
dispute-resolution case tables, the input is the party's opening description, and
the governing article is the one the deciding body printed in its own 法令依據
column. On the first such table the right article reached the window 7 times out
of 27, with 9 of 16 cases answered anyway with none of them and no refusal. The
governance half of that domain had simply never been in the vocabulary table; two
passes of curated rows took it to 25/27 with no case left answering on nothing,
while every other figure in this table stayed exactly where it was.

**Then two more tables of the same kind were added, and nothing was tuned against
them: 12/23, with 5 of 17 cases answered on none of the governing articles.**
That is the honest figure for a dispute the project has not seen. 25/27 is not
withdrawn and is not wrong — it is the number on the set it was curated against,
and it is labelled as such from here on. Three of the five silent misses want the
same article (共用部分的修繕與費用分擔) and get its neighbours instead. Those rows
are deliberately NOT being added to the vocabulary table: curating until they pass
would move 52% toward 93% and destroy the only held-out number in the project.
RESULTS.md §7 has the full breakdown.

The verifier stayed green through all of it, and that is not a malfunction:
**green means the cited article exists, is in force, and was not misquoted — it
has never meant the article governs your problem.** The seeded-defect figure measures the
first sentence. The second now has a number of its own, blind-coded and
re-runnable: over the 24 ended disputes, the answer points the OPPOSITE way to
the recorded outcome in **3 of 16** on the externally-labelled set and **2 of 8**
on the derived one — and `flagged_count` is 0 on all five. The five cases that
did draw a flag are not the five that pointed the wrong way; on this set the two
do not overlap at all.

```bash
python -m legal_agent.evaluation.realworld --direction
```

Both codings are blind — the answers are coded from a file that carries no
outcome, the outcomes from the case record afterwards, and the comparison is
arithmetic. No model grades legal reasoning here, and none will. See
[`evals/RESULTS.md`](evals/RESULTS.md) §7.

**Two of those rows need a second half a plain install does not have.** The
retriever is BM25 plus a hand-written vocabulary table plus optional bge-m3
embeddings, and the embeddings need a local index that is built rather than
shipped — it is derived from your corpus and it is ~12 MB of floats. Straight
after `pip install .` the retrieval half is lexical only: **recall 321/356
rather than 348/356**, measured. To reach the published figure:

```bash
ollama pull bge-m3                        # ~1.2 GB, once
python -m legal_agent.retrieval.dense     # builds the index beside your corpus
```

The verifier, the corpus, the honesty tier, the ladder and the 存證信函 template
never touch it and are unaffected. `real_recall` now prints whether the dense
half actually participated, so a number measured without it says so.

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
  `manual` (paste into any chat), `ollama` (local, the default), `anthropic`
  (paid). Pick one with `LEGAL_AGENT_PROVIDER=manual`, no source edit: measured
  on a clean venv, that was the only step in the documented path that left a
  first-time reader stuck, because `pip install` puts `config.py` in
  site-packages. **Swapping the model is measured, not assumed**: llama3.1:8B
  and qwen3:4b score identically on the golden set — pass 19 / partial 7 /
  miss 0, tier 29/32, premise 32/32 — because those are decided by retrieval and
  by code. The model changes the prose and nothing that is scored.
- **Judgments are reference tier**, never retrieval candidates and never citable
  law. They reach a page only through a deterministic join on articles the
  pipeline already retrieved, with the award figure read verbatim from the 主文.

[SPEC.md](SPEC.md) design · [RESULTS.md](evals/RESULTS.md) every number, the
method behind it, and the ones that went down ·
[CONTRIBUTING.md](CONTRIBUTING.md) the bar a change has to clear ·
[AGENTS.md](AGENTS.md) the same bar plus the measurement traps, for coding agents ·
[DEPLOY_SPACES.md](docs/DEPLOY_SPACES.md) hosting

**Found a wrong answer?** That is the most useful thing you can send — the
[issue template](.github/ISSUE_TEMPLATE/wrong-answer.yml) asks for the wording
you actually typed, which is how all 168 stored regression sessions began.

Personal engineering experiment, **not legal advice**. [MIT](LICENSE).
