"""Tests for the citation verifier (step 3b) — all THREE axes must fire.

Structural cases (fabricated / superseded) use small fixture corpora; the
content-mismatch and correct cases run against the real 住宅噪音 corpus.

Run:  python -m pytest tests/test_verifier.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.anti_hallucination.verifier import verify_answer  # noqa: E402
from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402


@pytest.fixture
def real_conn(tmp_path):
    """Isolated copy of the hand-verified noise corpus (tests never write the
    live DB — that habit polluted it once corpus v2 outgrew these 11 rows)."""
    from legal_agent.data.noise_seed import load_noise_statutes

    db = tmp_path / "t.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    load_noise_statutes(conn)
    yield conn
    conn.close()


@pytest.fixture
def superseded_conn(tmp_path):
    """INVENTED corpus: 測試法 第1條 exists only as a LAPSED slice (no current
    version); 測試法 第2條 is current (so the statute name resolves)."""
    db = tmp_path / "s.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第1條", "舊版條文內容。", "2010-01-01", "2020-01-01", "法律", "http://x/1"),
            ("測試法", "第2條", "現行條文內容。", "2010-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def suffix_conn(tmp_path):
    """INVENTED corpus: 測試法 has 第9條 and the DISTINCT sub-article 第9-1條
    (the corpus-normalized form of 第9條之1 — data/moj_xml.py convention)."""
    db = tmp_path / "sx.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("測試法", "第9條", "本條為母條。", "2010-01-01", None, "法律", "http://x/9"),
            ("測試法", "第9-1條", "本條為之一條。", "2010-01-01", None, "法律", "http://x/9-1"),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def test_suffix_citation_resolves_to_hyphen_form(suffix_conn):
    # 「第9條之1」 must hit the corpus row stored as 「第9-1條」 — not the parent.
    r = verify_answer("依測試法第9條之1,應予處理。", [], conn=suffix_conn)[0]
    assert r.citation.article_no == "第9-1條"
    assert r.exists is True
    assert r.verbatim_source == "本條為之一條。"


def test_hyphen_citation_parses_directly(suffix_conn):
    # The corpus-form spelling 「第9-1條」 in an answer must also verify.
    r = verify_answer("依測試法第9-1條,應予處理。", [], conn=suffix_conn)[0]
    assert r.citation.article_no == "第9-1條"
    assert r.exists is True


def test_ghost_suffix_not_laundered_into_parent(suffix_conn):
    # 「第9條之2」 does NOT exist; dropping 之2 would launder it into the real
    # 第9條 — the exact blind spot the ghost_suffix mutation exposed.
    r = verify_answer("依測試法第9條之2,應予處理。", [], conn=suffix_conn)[0]
    assert r.citation.article_no == "第9-2條"
    assert r.exists is False
    assert r.flagged is True


def _sem(consistent: bool):
    import json as _json
    return lambda p: _json.dumps({"consistent": consistent, "reason": "測試"})


def test_semantic_axis_flags_on_explicit_false(real_conn):
    answer = "依民法第793條,承租人於他人土地之喧囂侵入時,得禁止之。"
    r = verify_answer(answer, [], conn=real_conn, semantic_llm=_sem(False))[0]
    assert r.semantic_ok is False
    assert r.flagged is True
    assert "語意檢查" in r.reason


def test_semantic_axis_passes_on_true_and_stays_conservative_on_garbage(real_conn):
    answer = "依民法第793條,土地所有人於喧囂侵入時得禁止之。"
    ok = verify_answer(answer, [], conn=real_conn, semantic_llm=_sem(True))[0]
    assert ok.semantic_ok is True and ok.flagged is False
    # garbage output / infrastructure error -> NOT flagged (conservative)
    garbage = verify_answer(answer, [], conn=real_conn, semantic_llm=lambda p: "呃")[0]
    assert garbage.semantic_ok is True and garbage.flagged is False
    def boom(p):
        raise ConnectionError("model down")
    down = verify_answer(answer, [], conn=real_conn, semantic_llm=boom)[0]
    assert down.semantic_ok is True and down.flagged is False


def test_semantic_axis_skips_structurally_flagged_citations(real_conn):
    # wrong amount already flags on the structural axes — the model must NOT
    # be spent on it (and a lying "consistent" must not unflag it).
    calls = []
    def spy(p):
        calls.append(p)
        return '{"consistent": true}'
    answer = "依社會秩序維護法第72條,可處新臺幣十萬元以下罰鍰。"
    r = verify_answer(answer, [], conn=real_conn, semantic_llm=spy)[0]
    assert r.flagged is True and calls == []


def test_fabricated_article_number_flagged(real_conn):
    # 噪音管制法 exists but 第99條 does not.
    answer = "依噪音管制法第99條,住戶製造噪音應受處罰。"
    results = verify_answer(answer, [], conn=real_conn)
    assert len(results) == 1
    r = results[0]
    assert r.citation.statute_id == "噪音管制法"
    assert r.citation.article_no == "第99條"
    assert r.exists is False
    assert r.flagged is True


def test_content_mismatch_amount_flagged(real_conn):
    # Corpus §72 says 一萬元 (10,000); the answer claims NT$100,000.
    answer = "依社會秩序維護法第72條,製造噪音最高可罰新臺幣100,000元。"
    results = verify_answer(answer, [], conn=real_conn)
    r = next(x for x in results if x.citation.article_no == "第72條")
    assert r.exists is True
    assert r.content_match is False
    assert r.in_force is True
    assert r.flagged is True
    assert r.verbatim_source and "一萬元" in r.verbatim_source  # corpus original attached


def test_superseded_citation_not_in_force(superseded_conn):
    answer = "依測試法第1條,應予處理。"
    results = verify_answer(answer, [], conn=superseded_conn)  # as_of_date=None -> current
    r = results[0]
    assert r.exists is True
    assert r.in_force is False
    assert r.flagged is True
    assert r.verbatim_source == "舊版條文內容。"  # the superseded original is still attached


def test_correct_in_force_faithful_citation_not_flagged(real_conn):
    answer = "民法第793條規定,土地所有人對於他人土地散發的喧囂、振動侵入,得予禁止。"
    results = verify_answer(answer, [], conn=real_conn)
    r = next(x for x in results if x.citation.article_no == "第793條")
    assert r.exists is True
    assert r.content_match is True
    assert r.in_force is True
    assert r.flagged is False
    assert r.reason == ""


def test_unretrieved_but_real_article_says_so(real_conn):
    # retrieval-first is NOT relaxed: a citation outside the retrieved set is
    # still exists=False and flagged. But the REASON must not claim the corpus
    # has no such article when it plainly does — that misleads the reader.
    answer = "依社會秩序維護法第72條,可處罰鍰。"
    r = verify_answer(answer, [], conn=None, corpus_conn=real_conn)[0]
    assert r.exists is False and r.flagged is True
    assert "未出現在本次檢索結果中" in r.reason
    assert "確實存在於資料庫" in r.reason


def test_fabricated_article_is_named_as_absent_from_corpus(real_conn):
    answer = "依台灣安寧保障法第3條,住戶應保持安寧。"
    r = verify_answer(answer, [], conn=None, corpus_conn=real_conn)[0]
    assert r.exists is False and r.flagged is True
    assert "corpus 查無此法源" in r.reason


def test_without_corpus_conn_the_weaker_claim_is_made(real_conn):
    # no corpus connection -> the verifier genuinely cannot tell the two apart
    r = verify_answer("依社會秩序維護法第72條,可處罰鍰。", [])[0]
    assert r.flagged is True
    assert "確實存在於資料庫" not in r.reason


def test_direction_flip_flagged(real_conn):
    # Corpus §72 says 一萬元以下; claiming the SAME amount 以上 is the
    # direction_flip blind spot the mutation test exposed — must flag.
    answer = "依社會秩序維護法第72條,製造噪音可處新臺幣一萬元以上罰鍰。"
    r = verify_answer(answer, [], conn=real_conn)[0]
    assert r.exists is True
    assert r.content_match is False
    assert r.flagged is True
    assert "方向詞不符" in r.reason


def test_amount_without_direction_word_not_flagged(real_conn):
    # Paraphrase that keeps the amount but drops the direction word: the
    # conservative pass has nothing to compare — must NOT flag.
    answer = "依社會秩序維護法第72條,罰鍰上限為新臺幣一萬元。"
    r = verify_answer(answer, [], conn=real_conn)[0]
    assert r.content_match is True
    assert r.flagged is False


def test_supported_amount_is_not_flagged(real_conn):
    # Stating the CORRECT amount (一萬元) must NOT trip the content check.
    answer = "依社會秩序維護法第72條,製造噪音可處新臺幣一萬元以下罰鍰。"
    results = verify_answer(answer, [], conn=real_conn)
    r = next(x for x in results if x.citation.article_no == "第72條")
    assert r.content_match is True
    assert r.flagged is False


def test_chinese_numeral_and_particle_prefix_resolve(real_conn):
    # Chinese-numeral article no. + leading particle should still resolve + verify.
    answer = "按民法第七百九十三條,得禁止喧囂侵入。"
    results = verify_answer(answer, [], conn=real_conn)
    r = next(x for x in results if x.citation.statute_id == "民法")
    assert r.citation.article_no == "第793條"
    assert r.exists is True


def test_bad_as_of_date_raises(real_conn):
    with pytest.raises(ValueError):
        verify_answer("民法第793條。", [], as_of_date="2021/01/01", conn=real_conn)


@pytest.fixture
def practice_conn(tmp_path):
    """Corpus with a 行政實務見解 row keyed by 文號 (article_no='')."""
    db = tmp_path / "p.db"
    init_db(db)
    c = connect(db)
    seed_source_hierarchy(c)
    c.execute(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("司法院(81)廳刑一字第329號", "", "(測試)關於噪音案件之處理原則,應由警察機關處理。",
         "1992-05-01", None, "行政實務見解", "http://x/329"),
    )
    c.commit()
    yield c
    c.close()


def test_docnum_citation_extracted_and_verified(practice_conn):
    ans = ("實務見解:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。"
           "依司法院(81)廳刑一字第329號,應由警察機關處理。")
    r = next(x for x in verify_answer(ans, [], conn=practice_conn) if "第329號" in x.citation.raw)
    assert r.citation.statute_id == "司法院(81)廳刑一字第329號"
    assert r.citation.article_no == ""
    assert r.exists is True and r.flagged is False


def test_rank5_practice_in_law_section_flagged_as_misplaced(practice_conn):
    ans = ("法律明文:依司法院(81)廳刑一字第329號,應由警察機關處理。\n"
           "實務見解:(無)\n分析研判:僅供參考。")
    r = next(x for x in verify_answer(ans, [], conn=practice_conn) if "第329號" in x.citation.raw)
    assert r.exists is True
    assert r.flagged is True
    assert "位階誤植" in r.reason


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
