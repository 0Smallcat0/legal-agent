# Contributing

The bar here is unusual and worth reading before you spend time: **a change
ships when a number moves, and the number is published either way.**

Working through a coding agent? [`AGENTS.md`](AGENTS.md) is the same rules in one
screen, plus the measurement traps that have each produced a wrong number
here — an agent that skips it will publish one too.

## The rule

Every published figure in [`evals/RESULTS.md`](evals/RESULTS.md) has a harness
behind it that you can run ([the list](#the-harnesses) is below).

If your change moves one of those numbers, say which and by how much. If it
moves none, that is a fine thing to report — RESULTS.md has a whole section of changes that
looked obviously right and lost, and those entries are more useful than the wins.
What does not happen is a change shipping on the grounds that it is clearly
better.

Consequences people run into:

- **Do not relabel an expectation to make a case pass.** If a stored session
  expects an article and the change does not deliver it, the case stays failing
  and the reason gets written down. An expectation that was *wrong when written*
  is a different thing — correct it, and say which it was.
- **A retrieval trigger earns its place by the query it expands, not the articles
  it names.** Narrowing one without an A/B has twice removed something that was
  quietly holding a right answer up.
- **Verbatim or nothing.** Statute text and 主文 slices are never paraphrased,
  summarised, or masked. If a transformation would help, it belongs beside the
  verbatim text, not instead of it.
- **`qualifier_audit` is a standing gate, not a one-off.** Any change to
  `_resolve_id` or the Tier-3 name-qualifier set must be re-swept with
  `python -m legal_agent.evaluation.qualifier_audit` before it ships, and the
  false-reject count (expected: 0) gets logged in RESULTS.md either way — a
  gate tuned against today's probes can still launder tomorrow's prefix shape
  (「涉嫌X」「疑似X」「當地」…), and a rerun is the only thing that would
  catch it. CI runs it on every push, but CI catching it later is not a
  substitute for running it yourself first.

## The harnesses

This is the one canonical list; README, AGENTS.md and RESULTS.md link here. Every
harness is `python -m legal_agent.evaluation.<name>`, prints the corpus
fingerprint first, and reads its cases from `evals/` (see
[`evals/README.md`](evals/README.md)).

**No model — deterministic, re-runs identically:**

```bash
python -m legal_agent.evaluation.mutation                          # verifier recall, 19 seeded kinds
python -m legal_agent.evaluation.mutation --retrieval-first        # same, production call shape
python -m legal_agent.evaluation.blindspots                        # structural blind spots (frozen 25-case set)
python -m legal_agent.evaluation.qualifier_audit                   # Tier-3 name-qualifier gate, standing check
python -m legal_agent.evaluation.paragraph_bounds_audit            # 款 upper-bound upgrade path, not a judging criterion
python -m legal_agent.evaluation.real_recall                       # retrieval recall, 168 stored sessions
python -m legal_agent.evaluation.honesty_probe                     # refuse / false-refuse, 35 cases
python -m legal_agent.evaluation.judgment_relevance                # reference-judgment tier, 168 sessions
python -m legal_agent.evaluation.realworld                         # already-ended disputes, retrieval + refusal
python -m legal_agent.evaluation.realworld --direction             # answer vs recorded outcome, from stored blind codings
python -m legal_agent.evaluation.calibrate evals/golden_v2.json    # honesty-threshold sweep (stub answer, retrieval only)
```

The retrieval harnesses are deterministic only with the dense half present:
without Ollama + bge-m3 + `python -m legal_agent.retrieval.dense` they silently
measure BM25 alone. Each prints `dense_fallbacks`; it must be 0 before a number
is compared with a published one.

**Call a real model (Ollama) — not deterministic:**

```bash
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # statute coverage, tier, premise; grader at temperature 0
python -m legal_agent.evaluation.ablation evals/golden_v2.json     # bare model vs gated pipeline (--models, --out)
python -m legal_agent.evaluation.mutation --semantic               # the semantic 4th axis; semantic_unreached must be 0
python -m legal_agent.evaluation.realworld --answers               # prints answers beside outcomes for a human; scores nothing
```

## Running it

```bash
pip install -r requirements.txt
python -m pytest -q                 # no network, no API key
python app.py                       # web demo, builds the corpus on first run
```

Tests run against a fake model, so nothing here needs Ollama, a GPU, or a key.
Lint with `ruff check .` — the rules live in `pyproject.toml` and CI enforces
them.

**Windows: one-off scripts need UTF-8 output set explicitly.** Every harness
above prints Chinese text — mutation type names, verifier reasons, statute
content — and a default Windows console is on a legacy codepage (cp950 /
cp1252) that turns that into `UnicodeEncodeError` or silent mojibake, which
then reads like a program bug rather than a console setting. `mutation.py`,
`blindspots.py`, `qualifier_audit.py`, and `paragraph_bounds_audit.py` all
call `legal_agent.evaluation.enable_utf8_stdout()` at the top of their
`__main__` already — call the same function at the top of any new one-off
verification script you write, or set `PYTHONIOENCODING=utf-8` before running
an existing one.

## What is welcome

- **A session where the answer was wrong or the window was off-topic.** This is
  the most valuable thing you can send, and the issue template asks for the
  wording you actually used. Every one of the 168 stored sessions started this
  way.
- Bugs in the deterministic layers — verifier, retrieval filters, 主文 parsing,
  the ladder. These are code, so they are testable, so they are fixable.
- Portability work: the engine is jurisdiction-agnostic, and only the corpus and
  the 口語→法條 lexicon are Taiwan-specific.

## What is out of scope

- **Making the model smarter by prompting.** Two measured attempts are recorded
  in RESULTS.md; both made it worse. The design routes around the model rather
  than arguing with it.
- **New corpus domains or data sources** without a session that needed them.
- **Anything that makes the system sound more confident.** The three-tier honesty
  gate exists to say 「資料不足」 and must stay willing to.

## Legal

This is a personal engineering experiment and **not legal advice** — that framing
is load-bearing, not boilerplate, and contributions should not erode it. Shipped
judgment data is redacted to the header and 主文, and carries no party names; see
[`legal_agent/corpus/README.md`](legal_agent/corpus/README.md) before touching it.

MIT licensed. By contributing you agree your work ships under the same terms.
