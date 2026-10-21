"""Numbers written into prose must match the thing they describe.

Every measured figure in this project has a harness behind it. The numbers
COPIED out of those harnesses into README badges, the demo's hero line and the
CLI greeting have nothing behind them, and on 2026-08-06 that cost four separate
rounds of fixes in one day: the greeting still said 「11 部民生法規」 and the demo
footer 「2,560 條」 long after the corpus reached 16 statutes and 2,921 articles;
the Space advertised 10,437/10,437 after the mutation denominators were
re-measured; the tests badge and the demo hero each lagged a commit behind twice.

None of it was caught by a test, because presentation strings are not code. They
are now: this file derives the counts from the live corpus and fails when a
sentence disagrees with it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _corpus_counts(conn) -> tuple[int, int, int]:
    """(statutes, articles, judgments) as the prose counts them.

    The prose says 「16 部民生法規 2,921 條現行條文+1 個歷史版本+警察分工實務指引」.
    The police routing note is described SEPARATELY, so it is excluded from both
    counts here rather than the numbers being hardcoded to match. 15 法律 + 1 命令
    = 16. Articles are counted as distinct CURRENT articles (`effective_to IS
    NULL`), not rows: 違反社會秩序維護法案件處理辦法§11 also carries one repealed
    historical slice, and counting rows called that one article two — the prose
    said 「2,922 條」 while `mutation` said 2,921 in force.
    """
    statutes, articles = conn.execute(
        "SELECT COUNT(DISTINCT statute_id), "
        "COUNT(DISTINCT statute_id || '|' || article_no) FROM statutes "
        "WHERE hierarchy_level != '行政實務見解' AND effective_to IS NULL"
    ).fetchone()
    # The prose counts the SHIPPED judgments; a machine that has also harvested
    # more holds extra rows, which is legal (CorpusFingerprint: above the floor).
    from legal_agent.data.bootstrap import shipped_judgment_ids

    jids = shipped_judgment_ids()
    (judgments,) = conn.execute(
        f"SELECT COUNT(*) FROM judgments WHERE jid IN ({','.join('?' * len(jids))})", jids
    ).fetchone()
    return statutes, articles, judgments


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_every_prose_corpus_count_matches_the_corpus(shipped_conn):
    """The first sentence a user reads is the one that rots first.

    Both the CLI greeting and the demo footer are what a person sees BEFORE
    anything else, and both were three statutes and 362 articles out of date.
    """
    statutes, articles, judgments = _corpus_counts(shipped_conn)
    expected = [
        # README — the sentence that frames the whole worked example
        ("README.md", f"{articles:,} articles across {statutes} everyday statutes"),
        ("README.md", f"{judgments} real court judgments"),
        # SPEC.md — the scope paragraph
        ("SPEC.md", f"{articles:,} articles across {statutes} everyday"),
        # the CLI's opening line
        ("legal_agent/run.py", f"語料為 {statutes} 部民生法規"),
        # the demo: footer disclaimer, 法規檢索 tab, hero line
        ("app.py", f"{statutes} 部民生法規 {articles:,} 條現行條文"),
        ("app.py", f"{statutes} 部民生法規、{articles:,} 條現行條文"),
        ("app.py", f"{judgments} 篇實際判決佐證"),
    ]
    wrong = [(name, text) for name, text in expected if text not in _read(name)]
    assert not wrong, (
        "these sentences no longer match the corpus "
        f"({statutes} 部 / {articles} 條 / {judgments} 判決): {wrong}"
    )


# ── the mutation / blindspots headline, held to the same rule ───────────────
# 11,904/11,904 was typed by hand into four files and drifted. Its replacement,
# the per-kind table, is recomputed here from the shipped corpus: every figure
# must appear verbatim in the table evals/RESULTS.md publishes.
def test_the_mutation_and_blindspots_numbers_match_a_live_run(shipped_conn):
    from legal_agent.evaluation.blindspots import score_blindspots
    from legal_agent.evaluation.mutation import (
        _ALWAYS_NONEMPTY_ON_FULL_CORPUS,
        run_mutation_test,
    )

    report = run_mutation_test(shipped_conn)
    blindspots = score_blindspots(shipped_conn)
    results = _read("evals/RESULTS.md")

    # Per kind, next to its own name: a bare substring passed a regressed
    # alias_typo (1/2) because 「1/2」 appears elsewhere in the file. Iterating
    # the gated list, not report.kinds, catches a kind that generated nothing.
    missing = []
    for kind in dict.fromkeys((*_ALWAYS_NONEMPTY_ON_FULL_CORPUS, *report.kinds)):
        bucket = report._bucket(kind)
        needle = f"{sum(1 for o in bucket if o.ok):,}/{len(bucket):,}"
        if not bucket or not re.search(rf"`{kind}`[\s|]*\*\*{re.escape(needle)}\*\*", results):
            missing.append((kind, needle))
    if blindspots.target_headline not in results:
        missing.append(("blindspots", blindspots.target_headline))
    assert not missing, f"live numbers not found verbatim in evals/RESULTS.md: {missing}"
