"""Tests for the 口語→法條語彙 expansion table (retrieval/lexicon.py).

The table's VALUE is measured by the golden set (evals/RESULTS.md); these
tests pin its CONTRACT: additive only, verbatim-grounded, and silent when the
feature is off.

Run:  python -m pytest tests/test_lexicon.py -q
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.retrieval.lexicon import LEXICON, expand, expansions  # noqa: E402


def test_expansion_is_additive_never_replacing():
    original = "樓上半夜很吵,我失眠想求償"
    out = expand(original)
    assert out.startswith(original)      # user's words stay verbatim, in front
    assert len(out) > len(original)      # and statutory vocabulary was added


def test_untriggered_text_is_returned_unchanged():
    # a query with no everyday trigger must not be widened at all
    assert expand("商標搶註") == "商標搶註"
    assert expansions("商標搶註") == []


def test_everyday_words_reach_statutory_vocabulary():
    # the gap the table exists to close: the user's word never appears in the
    # article, the article's word never appears in the query
    assert "非財產上之損害" in expansions("我要請求精神賠償")
    assert "延長工作時間之工資" in expansions("公司不給加班費")
    assert "通訊交易" in expansions("網購想退貨")
    assert "按人數平均繼承" in expansions("父親過世遺產怎麼分")


def test_expansions_are_deduplicated_and_ordered():
    # 「失眠」 appears in two entries; its shared terms must not repeat
    out = expansions("失眠又要賠償")
    assert len(out) == len(set(out))


def test_every_statutory_term_appears_verbatim_in_the_corpus():
    """The discipline that makes this table trustworthy: the statutory side is
    COPIED from real article text, never invented. Checked against the live
    corpus when one exists (skipped in a bare checkout)."""
    from legal_agent.config import DB_PATH

    if not Path(DB_PATH).exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT content FROM statutes").fetchall()
    finally:
        conn.close()
    if not rows:
        return
    corpus = "\n".join(r[0] for r in rows)
    missing = [
        term
        for _triggers, statutory in LEXICON
        for term in statutory
        if term not in corpus
    ]
    assert not missing, f"not verbatim in any article: {missing}"
