"""The proviso marker: a verbatim slice of 但…不在此限, and nothing more.

Run:  python -m pytest tests/test_statute_text.py -q
"""
from __future__ import annotations

from html import escape

import legal_agent
from legal_agent.data.statute_text import mark_provisos, proviso_spans

# Verbatim from the corpus — the article the respondent's side turns on.
_793 = (
    "土地所有人於他人之土地、建築物或其他工作物有瓦斯、蒸氣、臭氣、煙氣、熱氣、"
    "灰屑、喧囂、振動及其他與此相類者侵入時，得禁止之。但其侵入輕微，或按土地形狀、"
    "地方習慣，認為相當者，不在此限。"
)


def test_the_proviso_is_sliced_verbatim():
    (start, end), = proviso_spans(_793)
    assert _793[start:end] == "但其侵入輕微，或按土地形狀、地方習慣，認為相當者，不在此限"


def test_an_article_with_no_proviso_yields_nothing():
    assert proviso_spans("因故意或過失，不法侵害他人之權利者，負損害賠償責任。") == []


def test_a_but_in_an_earlier_sentence_is_not_swallowed():
    """Otherwise the span runs from a 但 three sentences up to the proviso, and
    the emphasis lands on text that is not the proviso at all."""
    text = "第一項但書不適用之。第二項另有規定，但其情形輕微者，不在此限。"
    (start, end), = proviso_spans(text)
    assert text[start:end] == "但其情形輕微者，不在此限"


def test_marking_wraps_only_the_proviso_and_escapes_the_rest():
    out = mark_provisos(_793, "<mark>", "</mark>", escape)
    assert out.count("<mark>") == 1
    assert "得禁止之。<mark>但其侵入輕微" in out
    assert out.endswith("不在此限</mark>。")


def test_marking_is_lossless():
    """Verbatim or nothing: the text must survive the round trip unchanged."""
    assert mark_provisos(_793, "", "") == _793


def test_the_corpus_counts_behind_this_choice_still_hold():
    """The pattern is the PAIR because either half alone is imprecise or noise:
    「者」 is 71% of the corpus, and 但 alone runs to a different terminator in 312
    articles. Numbers measured 2026-08-15; a drift means the tradeoff needs
    re-reading, not that the test should be edited."""
    conn = legal_agent.open_corpus()
    try:
        def count(sql):
            return conn.execute(sql).fetchone()[0]

        live = "SELECT COUNT(*) FROM statutes WHERE effective_to IS NULL"
        assert count(f"{live} AND content LIKE '%不在此限%'") == 223
        assert count(f"{live} AND content LIKE '%但%' AND content NOT LIKE '%不在此限%'") == 312
        # 「…者」 was measured and rejected: register, not marker.
        assert count(f"{live} AND content LIKE '%者%'") == 2066
    finally:
        conn.close()


def test_the_two_exceptions_are_missed_and_never_mis_marked():
    """刑法§266 III and 強制汽車責任保險法§23 carry 不在此限 with no 但 (the second
    uses 惟). Both are real provisos this marker declines to find — the failure
    direction it wants."""
    conn = legal_agent.open_corpus()
    try:
        rows = conn.execute(
            "SELECT content FROM statutes WHERE effective_to IS NULL "
            "AND content LIKE '%不在此限%' AND content NOT LIKE '%但%'"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    for row in rows:
        assert proviso_spans(row["content"]) == []
