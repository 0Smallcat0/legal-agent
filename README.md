# Legal Agent

[![CI](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-134%20passing-brightgreen)

> A retrieval-first legal assistant built around one hard problem: **making an LLM
> cite statutes it cannot hallucinate.**

A 2025 Stanford study measured hallucination rates of *professional* legal AI at
17–33% — funded products, with RAG. This project is an experiment in the opposite
discipline: a **retrieval-first** pipeline where the model may only cite what was
retrieved, every citation is verified against a **time-versioned** corpus, and
**when the system errs, the user is told exactly where.**

The pipeline is **jurisdiction-agnostic** — the corpus, retriever, and verifier
know nothing about which country's law they hold. The **reference implementation**
covers **Taiwan (R.O.C.)** law, scoped to one scenario (住宅噪音糾紛 / residential
noise disputes) so the corpus is small enough to hand-verify every article. Adding
a jurisdiction means adding data, not rewriting the engine.

---

## Why it's interesting (engineering highlights)

- **Five-gate anti-hallucination pipeline.** retrieval-first prompt → citation
  verifier (*exists + content-match + in-force*) → three-tier honesty (answer /
  "marginal, for reference only" / "not in my corpus") → statute-vs-analysis
  separation → anti-sycophancy (correct a wrong premise instead of agreeing).
- **Time-sliced statute schema.** Primary key is `(statute_id, article_no,
  effective_from)` — a *time slice*, not an article number. The point-in-time
  filter runs **before** ranking, so a repealed version is never even a
  candidate. Answers *"for a dispute in 2023, which version applied?"*
- **Three swappable LLM backends behind one `str -> str` seam.** `manual` (free,
  paste into any chat you already have), `ollama` (free, local), `anthropic`
  (paid). Dependency-injected — the whole pipeline runs against a fake model in
  tests, no network, no key.
- **Clinic-style dialogue.** An LLM-driven intake collects facts conversationally,
  then retrieval fires **exactly once** on the complete fact set (multi-turn
  re-retrieval is the documented cause of RAG degradation) — enforced by a test.
- **Measured, not vibed.** A 25-case golden set, a seeded-error mutation test
  (verifier catch rate **31/31, 0 false positives**), a bare-vs-gated ablation
  across local models, and a data-driven honesty-threshold calibration — all
  reproducible offline for $0. Numbers in [`evals/RESULTS.md`](evals/RESULTS.md).
- **134 tests**, layered architecture, spec-driven. Full design in
  [`SPEC.md`](SPEC.md).

---

## Demo — the gates catching a real hallucination

<p align="center">
  <img src="docs/demo.svg" alt="Live demo: the verifier flags statutes the model hallucinated" width="840">
</p>

A live run against a **free local `llama3.1` (8B)** model. The user describes the
problem in plain language; the model drives the intake, then answers under all
five gates. Being a small model, it over-reached (it even typo'd 公寓→公寀) —
and the verifier caught every citation.
**Every one was flagged.** That is the entire thesis: *the model errs; the user
knows.* A stronger model (or the paid API) errs less — the gates work identically
regardless of backend.

**Try it yourself** — the same catch, interactive, no key needed:

```bash
python app.py   # Gradio demo: paste any "AI legal answer", watch the verifier flag it
```

<p align="center">
  <img src="docs/demo_web.png" alt="Web demo: paste an AI answer, the verifier flags the wrong amount, the out-of-corpus statute, and the typo'd statute name" width="840">
</p>

The first tab is the product: a clinic-style consultation — describe the
problem, answer the intake checklist, and on fact-completion the system
retrieves ONCE and returns the applicable statutes (verbatim, relevance-ranked),
the graded explanation, and the low-cost-first action ladder, with citation
verification as a quiet status line under the answer. Stages 1–2 and everything
deterministic run with no model at all; a local Ollama adds the 分析研判
narrative. Remaining tabs: the citation-check tool (pre-filled with a 3-defect
answer), the retrieval/time-slice explorer, and the measured numbers. Free
hosting recipe: [`docs/DEPLOY_SPACES.md`](docs/DEPLOY_SPACES.md).

---

## Measured results (local models, $0)

Full tables and method notes in [`evals/RESULTS.md`](evals/RESULTS.md); raw
per-run data in `evals/ablation_raw.json`. Headlines:

| what | number |
|---|---|
| Verifier catch rate on 31 seeded errors (fake statute / ghost article / wrong amount / out-of-force) | **31/31 (100%), 0/10 false positives** |
| Golden-set statute coverage (25 cases, llama3.1 8B, gated) | **84% pass+partial** (58% strict) |
| Honesty-tier accuracy / anti-sycophancy premise detection | **80% / 100%** |
| Out-of-scope questions refused instead of answered | **4/5** (the 1 leak is documented) |
| Bare model (no pipeline): memory-cited statutes traceable to a vetted source | **0–5%** (llama3.1 / qwen3) |
| Gated: every citation checked; small-model over-reach flagged inline with the verbatim article | **30–40% flagged** — *the model errs; the user knows* |

The golden set also caught a real retriever defect while being built
(single-character function-word tokens matched everything → fixed, tests
added), and the threshold-calibration sweep proved the current honesty signal
saturates at 80% — quantified motivation for the hybrid-retrieval roadmap item.

---

## Quickstart

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt

# build the SQLite schema + load the hand-verified reference corpus
python -c "from legal_agent.data.database import init_db; from legal_agent.config import DB_PATH; init_db(DB_PATH)"
python -m legal_agent.cli seed
python -m legal_agent.data.noise_seed
python -m legal_agent.data.source_ingest corpus/noise_routing_proposal.json

python -m pytest -q          # 134 passing

# measure it (no key, no cost — see evals/RESULTS.md for current numbers)
python -m legal_agent.evaluation.mutation                               # verifier catch rate
python -m legal_agent.evaluation.golden_set evals/golden_noise_v1.json  # Tier-1 golden set
python -m legal_agent.evaluation.calibrate evals/golden_noise_v1.json   # threshold sweep

# talk to it (default backend: free local Ollama — https://ollama.com)
#   ollama pull llama3.1     # once
python -m legal_agent.run
```

Zero-setup alternative: set `LLM_PROVIDER = "manual"` in
[`legal_agent/config.py`](legal_agent/config.py) and the agent prints the
assembled prompt for you to paste into any chat — no local model, no API key.

---

## Architecture

Each layer maps to one package under `legal_agent/`:

| Layer | Package | What it does |
|---|---|---|
| Data | `data/` | time-sliced SQLite corpus + hand-entry / ingest tooling |
| Retrieval | `retrieval/` | BM25 (jieba + CJK bigrams); point-in-time filter before ranking |
| Anti-hallucination | `anti_hallucination/` | the five gates (verifier / honesty / structure / sycophancy) |
| Dialogue | `dialogue/` | four-stage clinic flow; LLM-driven + rule-based intake; solution ladder |
| Evaluation | `evaluation/` | golden-set runner (auto-scored coverage/tier/premise) + batch hallucination check + seeded-error mutation test + bare-vs-gated ablation + threshold calibration |

The runtime backends live in `dialogue/{manual,ollama,stage3}_llm` and are chosen
by `config.LLM_PROVIDER`. Nothing above the data layer is jurisdiction-specific.

---

## Status & roadmap

**MVP complete, tested, and measured.** The full pipeline — data → retrieval →
five gates → dialogue → solution ladder — is implemented and green (134 tests),
runs end-to-end for free on a local model, ships an interactive demo (`app.py`),
and carries a reproducible evaluation suite with published numbers
([`evals/RESULTS.md`](evals/RESULTS.md)): 25-case golden set, seeded-error
verifier test, bare-vs-gated ablation, honesty-threshold calibration.

Scoped on purpose: one jurisdiction (Taiwan), one scenario, a hand-verified
corpus of 11 entries, no judgments yet. Roadmap — each item now motivated by a
measured gap: **hybrid (dense) retrieval** (coverage 84% pass+partial; honesty
signal saturates at 80% on BM25 alone), official-XML corpus ingestion at scale,
judgment ingestion, then more scenarios and jurisdictions on the same engine.

---

## Disclaimer

A personal-use engineering experiment. **Not legal advice**, not a substitute for
a lawyer, and not affiliated with any government body. Reference statute text is
quoted verbatim from official public sources.

## License

[MIT](LICENSE).
