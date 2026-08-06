"""Numbers written into prose must match the thing they describe.

Every measured figure in this project has a harness behind it. The numbers
COPIED out of those harnesses into README badges, the demo's hero line and the
CLI greeting have nothing behind them, and on 2026-08-06 that cost four separate
rounds of fixes in one day: the greeting still said 「11 部民生法規」 and the demo
footer 「2,560 條」 long after the corpus reached 16 statutes and 2,922 articles;
the Space advertised 10,437/10,437 after the mutation denominators were
re-measured; the tests badge and the demo hero each lagged a commit behind twice.

None of it was caught by a test, because presentation strings are not code. They
are now: this file derives the counts from the live corpus and fails when a
sentence disagrees with it.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _corpus_counts() -> tuple[int, int, int] | None:
    """(statutes, articles, judgments) as the prose counts them, or None.

    The prose says 「16 部民生法規 2,922 條+警察分工實務指引」 — the police routing
    note is described SEPARATELY, so it is excluded from both counts here rather
    than the numbers being hardcoded to match. 15 法律 + 1 命令 = 16.
    """
    from legal_agent.config import DB_PATH

    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        statutes, articles = conn.execute(
            "SELECT COUNT(DISTINCT statute_id), COUNT(*) FROM statutes "
            "WHERE hierarchy_level != '行政實務見解'"
        ).fetchone()
        (judgments,) = conn.execute("SELECT COUNT(*) FROM judgments").fetchone()
    finally:
        conn.close()
    if not articles:
        return None
    return statutes, articles, judgments


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_every_prose_corpus_count_matches_the_corpus():
    """The first sentence a user reads is the one that rots first.

    Both the CLI greeting and the demo footer are what a person sees BEFORE
    anything else, and both were three statutes and 362 articles out of date.
    """
    counts = _corpus_counts()
    if counts is None:
        pytest.skip("no corpus in this checkout")
    statutes, articles, judgments = counts
    expected = [
        # README — the sentence that frames the whole worked example
        ("README.md", f"{articles:,} articles across {statutes} everyday statutes"),
        ("README.md", f"{judgments} real court judgments"),
        # SPEC.md — the scope paragraph
        ("SPEC.md", f"{articles:,} articles across {statutes} everyday"),
        # the CLI's opening line
        ("legal_agent/run.py", f"語料為 {statutes} 部民生法規"),
        # the demo: footer disclaimer, 法規檢索 tab, hero line
        ("app.py", f"{statutes} 部民生法規 {articles:,} 條"),
        ("app.py", f"{statutes} 部民生法規、{articles:,} 條條文"),
        ("app.py", f"{judgments} 篇實際判決佐證"),
    ]
    wrong = [(name, text) for name, text in expected if text not in _read(name)]
    assert not wrong, (
        "these sentences no longer match the corpus "
        f"({statutes} 部 / {articles} 條 / {judgments} 判決): {wrong}"
    )


_BADGE = re.compile(r"tests-(\d+)%20passing")
_HERO = re.compile(r"(\d+) 項測試通過")


def _stated_test_counts() -> dict[str, int]:
    badge = _BADGE.search(_read("README.md"))
    hero = _HERO.search(_read("app.py"))
    assert badge and hero, "the tests badge or the demo hero line moved"
    return {"README.md badge": int(badge.group(1)), "app.py hero": int(hero.group(1))}


def test_the_two_stated_test_counts_agree():
    """Cheap half of the check, and it runs even on a partial suite: the badge
    and the hero are updated by hand in two files, so they drift apart first."""
    stated = _stated_test_counts()
    assert len(set(stated.values())) == 1, f"stated test counts disagree: {stated}"


def test_the_stated_test_count_is_not_behind_reality(request):
    """The expensive half: compare against what pytest actually collected.

    Only meaningful on a full run — a subset collects fewer tests, and failing
    then would punish `pytest tests/test_x.py`. So this asserts one direction:
    the stated number may not be LOWER than the collected one, which is exactly
    the way it rots (someone adds tests and the badge stays put).
    """
    collected = request.session.testscollected
    stated = _stated_test_counts()
    value = next(iter(stated.values()))
    if collected < value:
        pytest.skip(f"partial run ({collected} collected) — nothing to compare")
    assert value == collected, (
        f"{collected} tests collected but the prose says {value}: {stated}"
    )
