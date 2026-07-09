"""Tests for lexical BM25 retrieval with point-in-time filtering (step 3a).

The time-slice tests run over a tiny INVENTED fixture corpus (no dependency on
the real legal text). One smoke test runs over the real 住宅噪音 corpus.

Run:  python -m pytest tests/test_retriever.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.retrieval.retriever import retrieve  # noqa: E402


@pytest.fixture
def fake_conn(tmp_path):
    """A tiny time-sliced corpus of INVENTED articles.

    測試法 第1條 has two slices: v1 '貓咪' (2010..2020, superseded) and v2 '狗狗'
    (2020..now). 測試法 第2條 is a single current slice about '噪音'.
    """
    db = tmp_path / "fake.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)  # 法律 must exist for the FK
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第1條", "住戶不得飼養貓咪，違者處罰。", "2010-01-01", "2020-01-01", "法律", "http://x/1v1"),
            ("測試法", "第1條", "住戶不得飼養狗狗，違者處罰。", "2020-01-01", None, "法律", "http://x/1v2"),
            ("測試法", "第2條", "夜間不得製造噪音干擾鄰居。", "2010-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def test_returns_in_force_slice_for_date(fake_conn):
    # In 2015 the in-force slice of 第1條 is v1 ('貓咪'); v2 (from 2020) is not yet live.
    results = retrieve("貓咪", as_of_date="2015-06-01", conn=fake_conn)
    assert results, "should retrieve the in-force v1 slice"
    top = results[0]
    assert (top.statute_id, top.article_no) == ("測試法", "第1條")
    assert top.effective_from == "2010-01-01"
    assert "貓咪" in top.content
    assert all(r.effective_from != "2020-01-01" for r in results)  # v2 not yet in force


def test_excludes_superseded_slice(fake_conn):
    # In 2021, v1 (lapsed 2020-01-01) must NOT be returned even though it matches '飼養';
    # only the current v2 slice is a candidate.
    results = retrieve("飼養", as_of_date="2021-01-01", conn=fake_conn)
    assert results
    keys = {(r.article_no, r.effective_from) for r in results}
    assert ("第1條", "2020-01-01") in keys       # current v2 present
    assert ("第1條", "2010-01-01") not in keys    # superseded v1 excluded
    assert all("貓咪" not in r.content for r in results)


def test_no_lexical_overlap_returns_empty(fake_conn):
    assert retrieve("太空梭火箭發射", as_of_date="2015-06-01", conn=fake_conn) == []


def test_none_date_uses_current_slice(fake_conn):
    # No date -> currently-in-force slice only (effective_to IS NULL).
    results = retrieve("狗狗", as_of_date=None, conn=fake_conn)
    assert results
    assert (results[0].article_no, results[0].effective_from) == ("第1條", "2020-01-01")
    assert "狗狗" in results[0].content


def test_bad_as_of_date_raises(fake_conn):
    with pytest.raises(ValueError):
        retrieve("貓咪", as_of_date="2015/06/01", conn=fake_conn)


def test_real_corpus_noise_query():
    """Smoke test over the REAL corpus: a noise complaint surfaces the noise statutes."""
    from legal_agent.config import DB_PATH
    from legal_agent.data.noise_seed import load_noise_statutes

    init_db(DB_PATH)                       # ensure the real corpus is present
    seed_conn = connect(DB_PATH)
    seed_source_hierarchy(seed_conn)
    load_noise_statutes(seed_conn)         # idempotent: skips if already loaded
    seed_conn.close()

    results = retrieve("鄰居半夜製造噪音")  # as_of_date=None (all 9 are in force), K=5
    assert results, "real corpus should return noise-related statutes"

    pairs = {(r.statute_id, r.article_no) for r in results}
    expected = {("社會秩序維護法", "第72條"), ("噪音管制法", "第6條")}
    assert pairs & expected, f"expected one of {expected} among top results, got {pairs}"

    for r in results:  # traceability: verbatim content + source_url on every hit
        assert r.content and r.content.strip()
        assert r.source_url


def test_retrieve_scored_returns_statute_score_pairs(fake_conn):
    from legal_agent.data.models import Statute
    from legal_agent.retrieval.retriever import retrieve, retrieve_scored

    pairs = retrieve_scored("貓咪", as_of_date="2015-06-01", conn=fake_conn)
    assert pairs, "should retrieve scored pairs"
    assert all(isinstance(p, tuple) and len(p) == 2 for p in pairs)
    statute, score = pairs[0]
    assert isinstance(statute, Statute)
    assert isinstance(score, float)
    # parity with retrieve(): same Statutes, same order
    assert [s for s, _ in pairs] == retrieve("貓咪", as_of_date="2015-06-01", conn=fake_conn)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
