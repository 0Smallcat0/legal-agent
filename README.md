# Taiwan Legal Agent

[![CI](https://github.com/0Smallcat0/taiwan-legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/0Smallcat0/taiwan-legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Tests](https://img.shields.io/badge/tests-126%20passing-brightgreen)

> A personal-use legal assistant for Taiwan (R.O.C.) law, built around one hard
> problem: **making an LLM cite statutes it cannot hallucinate.**

A 2025 Stanford study measured hallucination rates of *professional* legal AI at
17–33% — funded products, with RAG. This project is an experiment in the opposite
discipline: a **retrieval-first** pipeline where the model may only cite what was
retrieved, every citation is verified against a **time-versioned** corpus, and
**when the system errs, the user is told exactly where.**

Scope is deliberately narrowed to one scenario — 住宅噪音糾紛 (residential noise
disputes) — so the corpus is small enough to hand-verify every article.

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
- **126 tests**, layered architecture, spec-driven. Full design in
  [`taiwan-legal-agent-spec.md`](taiwan-legal-agent-spec.md).

---

## Demo — the gates catching a real hallucination

A live run against a **free local `llama3.1` (8B)** model. The user describes the
problem in plain language; the model drives the intake, then answers under all
five gates. Being a small model, it over-reached — and the verifier caught it:

```text
你 > 樓上鄰居三更半夜一直搬東西、很大聲敲打，幾乎每天，我有錄影，報過警但沒用
…(model-driven intake collects the facts, then retrieves ONCE)…

══════════════ 診斷結果 ══════════════
法律明文: 社會秩序維護法第72條 …
實務見解: 以下為主管機關實務見解/處理原則，非法律明文，僅供參考 …

⚠ 引用查核(下列引用有疑慮,請對照條文原文):
  - 噪音管制法第8條: corpus 查無此法源
  - 噪音管制法第9條: corpus 查無此法源
  - 公寀大廈管理條例第16條: corpus 查無此法源      ← model even typo'd 公寓→公寀

建議處理順序(由低成本 → 高成本;打官司是最後手段):
  1. 反映管理委員會   [建議下一步]   免費 · 即時~數日
  2. 報警請警察到場   [已嘗試]       免費 · 即時
  3. 里長 / 調解委員會 調解 …
  4. 寄發存證信函 …
  5. 民事訴訟(最後手段) …
```

The 8B model cited 噪音管制法 §8/§9 (not in the retrieved corpus) and typo'd a
statute name. **Every one was flagged.** That is the entire thesis: *the model
errs; the user knows.* A stronger model (or the paid API) errs less — the gates
work identically regardless of backend.

---

## Quickstart

Requires **Python 3.10+**.

```bash
pip install -r requirements.txt

# build the SQLite schema + load the hand-verified noise corpus
python -c "from legal_agent.data.database import init_db; from legal_agent.config import DB_PATH; init_db(DB_PATH)"
python -m legal_agent.cli seed
python -m legal_agent.data.noise_seed
python -m legal_agent.data.source_ingest corpus/noise_routing_proposal.json

python -m pytest -q          # 126 passing

# talk to it (default backend: free local Ollama — https://ollama.com)
#   ollama pull llama3.1     # once
python -m legal_agent.run
```

Zero-setup alternative: set `LLM_PROVIDER = "manual"` in
[`legal_agent/config.py`](legal_agent/config.py) and the agent prints the
assembled prompt for you to paste into any chat — no local model, no API key.

---

## Architecture

Each spec layer maps to one package under `legal_agent/`:

| Layer | Package | What it does |
|---|---|---|
| Data | `data/` | time-sliced SQLite corpus + hand-entry / ingest tooling |
| Retrieval | `retrieval/` | BM25 (jieba + CJK bigrams); point-in-time filter before ranking |
| Anti-hallucination | `anti_hallucination/` | the five gates (verifier / honesty / structure / sycophancy) |
| Dialogue | `dialogue/` | four-stage clinic flow; LLM-driven + rule-based intake; solution ladder |
| Evaluation | `evaluation/` | Tier-1 golden-set runner + Tier-2 batch hallucination check |

The runtime backends live in `dialogue/{manual,ollama,stage3}_llm` and are chosen
by `config.LLM_PROVIDER`.

---

## Status & roadmap

**MVP complete and tested.** The full pipeline — data → retrieval → five gates →
dialogue → solution ladder → evaluation harness — is implemented and green
(126 tests), and runs end-to-end for free on a local model.

Scoped on purpose: one scenario, a hand-verified corpus of 11 statute articles, no
judgments yet. Roadmap: author the ~20–30 case golden set (Tier-1 baseline),
calibrate the honesty threshold, then expand scenarios and add judgment ingestion.

---

## Disclaimer

A personal-use engineering experiment. **Not legal advice**, not a substitute for
a lawyer, and not affiliated with any government body. Statute text is quoted
verbatim from the public database at law.moj.gov.tw.

## License

[MIT](LICENSE).
