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


def test_real_corpus_noise_query(tmp_path):
    """Smoke test over the hand-verified noise corpus (isolated copy — tests
    never write the live DB)."""
    from legal_agent.data.noise_seed import load_noise_statutes

    db = tmp_path / "t.db"
    init_db(db)
    seed_conn = connect(db)
    seed_source_hierarchy(seed_conn)
    load_noise_statutes(seed_conn)

    results = retrieve("鄰居半夜製造噪音", conn=seed_conn)  # as_of_date=None, K=5
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


# ── Lexicon phrases as a retrieval channel ───────────────────────────────────
@pytest.fixture
def gap_conn(tmp_path):
    """A corpus where the RIGHT article shares no word with how people talk.

    測試法 第1條 quotes the statutory phrase 社維§72 uses; 測試法 第2條 is the
    decoy that actually matches the user's words.
    """
    db = tmp_path / "gap.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第1條", "製造噪音或深夜喧嘩，妨害公眾安寧，不聽禁止者，處罰鍰。",
             "2010-01-01", None, "法律", "http://x/1"),
            ("測試法", "第2條", "樓上住戶應維持樓地板之使用狀態。",
             "2010-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def test_lexicon_phrase_pulls_in_an_article_the_users_words_never_reach(gap_conn):
    # 「樓上小孩跑跳、拖椅子」 shares no token with 第1條 — inclusion is decided by
    # the user's own words on purpose — so ranking alone can never surface it.
    # The lexicon's statutory side is verbatim article text, so a phrase hit is
    # an exact pointer.
    refs = [
        (s.statute_id, s.article_no)
        for s in retrieve("樓上小孩每天跑跳、拖椅子,受不了", conn=gap_conn)
    ]
    assert ("測試法", "第1條") in refs
    assert ("測試法", "第2條") in refs      # the decoy is not evicted


def test_promotion_never_evicts_an_article_the_same_phrases_point_at():
    # Measured on a stalking session: 家暴法§14 sat at rank 6 of an 8-slot
    # window, so it was 「already in the window」 and not promoted — and then
    # three promotions trimmed the window to five and dropped it.
    from legal_agent.data.models import Statute
    from legal_agent.retrieval import retriever as r

    def art(no, content):
        return Statute("測試法", no, content, "2010-01-01", None, "法律", "http://x")

    phrase = "為騷擾、接觸、跟蹤、通話、通信或其他非必要之聯絡行為"
    ranked = [(art(f"第{i}條", "無關內容"), float(20 - i)) for i in range(1, 6)]
    ranked.append((art("第6條", f"禁止相對人{phrase}。"), 14.0))       # phrase-matched, tail
    ranked += [(art(f"第{i}條", "無關內容"), float(20 - i)) for i in (7, 8)]
    candidates = [s for s, _ in ranked] + [art("第99條", f"…{phrase}…")]

    out = r._promote_lexicon_phrases("騷擾", candidates, ranked, k=8)
    refs = [s.article_no for s, _ in out]
    assert "第6條" in refs, refs      # protected: it matches the triggered phrase
    assert len(refs) == 8


def test_promotion_does_not_move_the_honesty_floor(gap_conn, monkeypatch):
    from legal_agent.retrieval import retriever

    query = "樓上小孩每天跑跳、拖椅子,受不了"
    pairs = retriever.retrieve_scored(query, conn=gap_conn)
    promoted = [sc for s, sc in pairs if s.article_no == "第1條"]
    assert promoted == [0.0]              # honest: no lexical match of its own

    # The honesty tier reads the TOP score: it must be identical to what it was
    # before any promotion, or 「資料不足」 would quietly change meaning.
    monkeypatch.setattr(retriever, "LEXICON_RESERVED_SEATS", 0)
    before = retriever.retrieve_scored(query, conn=gap_conn)
    assert max(sc for _s, sc in pairs) == max(sc for _s, sc in before)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
