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


def test_a_broad_phrase_does_not_outrank_one_that_identifies_a_single_article():
    """Measured: 民法§354 and 刑§309 each had a phrase matching exactly one
    article and still lost their reserved seat, because seats were spent in
    table order and 「負損害賠償責任」 (18 articles) / 「土地所有人」 (33) fired
    first. A phrase that matches half a chapter points nowhere."""
    from legal_agent.data.models import Statute
    from legal_agent.retrieval import retriever as r

    def statute(no: str, content: str) -> Statute:
        return Statute(
            statute_id="測試法", article_no=no, content=content,
            effective_from="2010-01-01", effective_to=None,
            hierarchy_level="法律", source_url=f"http://x/{no}",
        )

    # 「共通語」 is in three articles; 「唯一語」 is in one. Only one seat exists.
    broad = [statute(f"第{i}條", "共通語 之規定") for i in (1, 2, 3)]
    precise = statute("第9條", "唯一語 之規定")
    candidates = [*broad, precise]
    ranked = [(statute("第7條", "窗內"), 5.0)]

    monkey = r.LEXICON_RESERVED_SEATS
    try:
        r.LEXICON_RESERVED_SEATS = 1
        import legal_agent.retrieval.lexicon as lexicon
        real_expansions, real_expansion = lexicon.expansions, r.config.QUERY_EXPANSION
        lexicon.expansions = lambda _q: ["共通語", "唯一語"]   # broad first, as the table would
        r.config.QUERY_EXPANSION = "on"
        out = r._promote_lexicon_phrases("q", candidates, ranked, k=2)
    finally:
        r.LEXICON_RESERVED_SEATS = monkey
        lexicon.expansions, r.config.QUERY_EXPANSION = real_expansions, real_expansion

    promoted = [s.article_no for s, score in out if score == 0.0]
    assert promoted == ["第9條"], f"the one seat went to a phrase pointing nowhere: {promoted}"


def test_trade_regulation_is_dropped_unless_the_question_is_about_the_trade(tmp_path):
    """Measured over the real sessions: 2-3 of 8 seats in EVERY landlord-tenant
    case went to 租賃住宅服務業 articles (營業保證金, 罰鍰) — the longest articles
    in that statute, which is exactly why BM25 kept handing them seats."""
    db = tmp_path / "trade.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第1條", "押金之金額，不得逾二個月之租金總額，出租人應返還押金。",
             "2010-01-01", None, "法律", "http://x/1"),
            ("測試法", "第2條", "租賃住宅服務業之營業保證金，應由全國聯合會繳存，押金不予退還。",
             "2010-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    try:
        tenant = [(s.statute_id, s.article_no) for s in retrieve("房東不退我押金", conn=conn)]
        assert ("測試法", "第1條") in tenant
        assert ("測試法", "第2條") not in tenant

        # …but someone dealing with a 包租業 still gets the trade's own rules.
        trade = [(s.statute_id, s.article_no) for s in retrieve("包租業不退我押金", conn=conn)]
        assert ("測試法", "第2條") in trade

        # 仲介 and 業者 were exception words for one round, and a 房仲 house
        # purchase pulled the rental trade's 營業保證金 article straight back —
        # a 不動產經紀業 is not a 租賃住宅服務業.
        broker = [(s.statute_id, s.article_no)
                  for s in retrieve("我透過房仲買房付的押金仲介不退", conn=conn)]
        assert ("測試法", "第2條") not in broker
    finally:
        conn.close()


def test_a_seat_finishes_the_topic_the_window_already_confirms():
    """Measured on 「付了十萬斡旋金,屋主不賣了」: 民法§249 was already in the
    window and 民法§248 — the other half of the same answer — never got a seat,
    because three equally-selective phrases from other rows came first in table
    order. Table order says nothing about what was asked; a row the ranking has
    already corroborated does."""
    from legal_agent.data.models import Statute
    from legal_agent.retrieval import lexicon
    from legal_agent.retrieval import retriever as r

    def statute(no: str, content: str) -> Statute:
        return Statute(
            statute_id="測試法", article_no=no, content=content,
            effective_from="2010-01-01", effective_to=None,
            hierarchy_level="法律", source_url=f"http://x/{no}",
        )

    in_window = statute("第1條", "甲語 之規定")      # row 0, already ranked
    same_row = statute("第2條", "乙語 之規定")       # row 0, the other half
    other_row = statute("第3條", "丙語 之規定")      # row 1, unrelated topic

    saved = (lexicon.LEXICON, lexicon.expansions, r.LEXICON_RESERVED_SEATS,
             r.config.QUERY_EXPANSION)
    try:
        lexicon.LEXICON = [(("t0",), ("甲語", "乙語")), (("t1",), ("丙語",))]
        lexicon.expansions = lambda _q: ["丙語", "甲語", "乙語"]   # 丙語 FIRST in order
        # TWO seats and an UNPROTECTED place in the window, so the corroborated
        # row can finish its topic without evicting anything phrase-matched.
        # (With no unprotected place only the new-topic seat survives — see
        # test_promotion_never_evicts_an_already_matched_window.)
        r.LEXICON_RESERVED_SEATS = 2
        r.config.QUERY_EXPANSION = "on"
        fillers = [statute("第8條", "無關內容"), statute("第7條", "也無關")]
        out = r._promote_lexicon_phrases(
            "q", [in_window, same_row, other_row],
            [(in_window, 9.0), (fillers[0], 2.0), (fillers[1], 1.0)], k=5,
        )
    finally:
        (lexicon.LEXICON, lexicon.expansions, r.LEXICON_RESERVED_SEATS,
         r.config.QUERY_EXPANSION) = saved

    promoted = [s.article_no for s, score in out if score == 0.0]
    assert "第2條" in promoted, f"the confirmed topic was never finished: {promoted}"
    assert promoted[0] == "第3條", f"the reserved first seat went elsewhere: {promoted}"


def test_an_owner_occupier_is_not_handed_a_landlords_repair_duty(tmp_path):
    """漏水 and 修繕 fire the tenancy vocabulary whoever is asking, so an
    owner-occupied flat flooded from upstairs got 民法§430/§437/§423 — measured
    at 4 of 8 seats there and 3 of 8 in a house-purchase session, neither of
    which mentions a landlord at all."""
    db = tmp_path / "owner.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第1條", "土地上之建築物漏水致他人權利之損害，由所有人負賠償責任。",
             "2010-01-01", None, "法律", "http://x/1"),
            ("測試法", "第2條", "租賃物如有修繕之必要，出租人應負責，承租人得催告之。",
             "2010-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    try:
        owner = [(s.statute_id, s.article_no)
                 for s in retrieve("自有住宅樓上漏水,修繕費誰負責", conn=conn)]
        assert ("測試法", "第1條") in owner
        assert ("測試法", "第2條") not in owner

        # A tenant — or a landlord asking about their own let flat — keeps them.
        tenant = [(s.statute_id, s.article_no)
                  for s in retrieve("我租的房子漏水,房東不修繕", conn=conn)]
        assert ("測試法", "第2條") in tenant
    finally:
        conn.close()


def test_the_succession_chapter_stays_out_while_the_person_is_alive(tmp_path):
    """「我爸失智,弟弟拿他的存摺把錢領走」 returned a window that was 8/8 繼承編.
    The father is alive; answering his family with the rules for dividing his
    estate is the wrong-premise failure this project exists to avoid."""
    db = tmp_path / "alive.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第1條", "受監護宣告之人，無行為能力，其存摺財產應由監護人管理。",
             "2010-01-01", None, "法律", "http://x/1"),
            ("測試法", "第2條", "遺產由繼承人按應繼分繼承，存摺財產亦同。",
             "2010-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    try:
        alive = [(s.statute_id, s.article_no)
                 for s in retrieve("我爸失智認不得人,弟弟把他存摺的財產領走", conn=conn)]
        assert ("測試法", "第1條") in alive
        assert ("測試法", "第2條") not in alive

        # An explicit death always wins — 「一人一半繼承了房子」 must still reach it.
        dead = [(s.statute_id, s.article_no)
                for s in retrieve("我爸過世了,存摺的財產要怎麼繼承", conn=conn)]
        assert ("測試法", "第2條") in dead
    finally:
        conn.close()


def test_one_seat_is_reserved_for_a_topic_the_window_lacks():
    """Corroboration was handing every seat to topics the ranking had already
    confirmed, so 民法§254 and §264 fired first and still lost. A corroborated row
    is by definition already represented; an uncorroborated one is a whole answer
    the window is missing, so the first seat goes to it."""
    from legal_agent.data.models import Statute
    from legal_agent.retrieval import lexicon
    from legal_agent.retrieval import retriever as r

    def statute(no: str, content: str) -> Statute:
        return Statute(
            statute_id="測試法", article_no=no, content=content,
            effective_from="2010-01-01", effective_to=None,
            hierarchy_level="法律", source_url=f"http://x/{no}",
        )

    in_window = statute("第1條", "甲語 之規定")      # row 0, already ranked
    same_row = statute("第2條", "乙語 之規定")       # row 0, corroborated
    new_topic = statute("第3條", "丙語 之規定")      # row 1, nothing in the window

    saved = (lexicon.LEXICON, lexicon.expansions, r.LEXICON_RESERVED_SEATS,
             r.config.QUERY_EXPANSION)
    try:
        lexicon.LEXICON = [(("t0",), ("甲語", "乙語")), (("t1",), ("丙語",))]
        lexicon.expansions = lambda _q: ["甲語", "乙語", "丙語"]
        r.LEXICON_RESERVED_SEATS = 1
        r.config.QUERY_EXPANSION = "on"
        out = r._promote_lexicon_phrases(
            "q", [in_window, same_row, new_topic], [(in_window, 9.0)], k=2,
        )
    finally:
        (lexicon.LEXICON, lexicon.expansions, r.LEXICON_RESERVED_SEATS,
         r.config.QUERY_EXPANSION) = saved

    promoted = [s.article_no for s, score in out if score == 0.0]
    assert promoted == ["第3條"], f"the seat completed a topic already present: {promoted}"


def test_promotion_never_evicts_an_already_matched_window():
    """Measured on an injury-dismissal session: the window already held 勞基§13 at
    rank 8 and §59 at rank 7, and three promotions — one of them 公寓大廈§16 —
    pushed both out. A reserved seat is for what the window LACKS."""
    from legal_agent.data.models import Statute
    from legal_agent.retrieval import lexicon
    from legal_agent.retrieval import retriever as r

    def statute(no: str, content: str) -> Statute:
        return Statute(
            statute_id="測試法", article_no=no, content=content,
            effective_from="2010-01-01", effective_to=None,
            hierarchy_level="法律", source_url=f"http://x/{no}",
        )

    # Every item in the window is matched by a fired phrase; the candidate the
    # promoter would add is not in it.
    in_window = [statute("第1條", "甲語 之規定"), statute("第2條", "乙語 之規定")]
    outsider = statute("第9條", "丙語 之規定")

    saved = (lexicon.LEXICON, lexicon.expansions, r.LEXICON_RESERVED_SEATS,
             r.config.QUERY_EXPANSION)
    try:
        lexicon.LEXICON = [(("t0",), ("甲語", "乙語")), (("t1",), ("丙語",))]
        lexicon.expansions = lambda _q: ["甲語", "乙語", "丙語"]
        r.LEXICON_RESERVED_SEATS = 3
        r.config.QUERY_EXPANSION = "on"
        out = r._promote_lexicon_phrases(
            "q", [*in_window, outsider], [(s, 9.0) for s in in_window], k=2,
        )
    finally:
        (lexicon.LEXICON, lexicon.expansions, r.LEXICON_RESERVED_SEATS,
         r.config.QUERY_EXPANSION) = saved

    kept = [s.article_no for s, _ in out]
    # One seat still opens the missing topic — that is the reserved first seat —
    # but only one, where the old code took three and dropped two right answers.
    assert "第1條" in kept, f"the top of a matched window was evicted: {kept}"
    assert kept.count("第9條") == 1, f"more than the one new-topic seat: {kept}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
