# Contributing

The bar here is unusual and worth reading before you spend time: **a change
ships when a number moves, and the number is published either way.**

Working through a coding agent? [`AGENTS.md`](AGENTS.md) is the same rules in one
screen, plus the seven measurement traps that have each produced a wrong number
here — an agent that skips it will publish one too.

## The rule

Every published figure in [`evals/RESULTS.md`](evals/RESULTS.md) has a harness
behind it that you can run:

```bash
python -m legal_agent.evaluation.mutation                          # verifier recall
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # statute coverage
python -m legal_agent.evaluation.real_recall                       # 168 real sessions
python -m legal_agent.evaluation.honesty_probe                     # refuse / false-refuse
python -m legal_agent.evaluation.judgment_relevance                # reference tier
```

If your change moves one of those, say which and by how much. If it moves none,
that is a fine thing to report — RESULTS.md has a whole section of changes that
looked obviously right and lost, and those entries are more useful than the wins.
What does not happen is a change shipping on the grounds that it is clearly
better.

Three consequences people run into:

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

## Running it

```bash
pip install -r requirements.txt
python -m pytest -q                 # 433 tests, no network, no API key
python app.py                       # web demo, builds the corpus on first run
```

Tests run against a fake model, so nothing here needs Ollama, a GPU, or a key.
Lint with `ruff check .` — the rules live in `pyproject.toml` and CI enforces
them.

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
[`corpus/README.md`](corpus/README.md) before touching it.

MIT licensed. By contributing you agree your work ships under the same terms.
