"""Tests for the citation verifier (step 3b) — all THREE axes must fire.

Structural cases (fabricated / superseded) use small fixture corpora; the
content-mismatch and correct cases run against the real 住宅噪音 corpus.

Run:  python -m pytest tests/test_verifier.py -q
"""
from __future__ import annotations

import pytest

from legal_agent.anti_hallucination.verifier import (
    VERIFIED_SCOPE_NOTE,
    verification_status_line,
    verify_answer,
)
from legal_agent.data.database import connect, init_db
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.evaluation.blindspots import load_blindspot_cases, load_positive_control_cases


@pytest.fixture
def real_conn(tmp_path):
    """Isolated copy of the hand-verified noise corpus (tests never write the
    live DB — that habit polluted it once corpus v2 outgrew these 11 rows)."""
    from tests.conftest import load_noise_fixture

    db = tmp_path / "t.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    load_noise_fixture(conn)
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


@pytest.fixture
def period_conn(tmp_path):
    """INVENTED corpus: one current article stating a 七日 period (plus a
    一個月 period), for the period-swap content pass."""
    db = tmp_path / "p.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.execute(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("期間測試法", "第1條",
         "消費者得於收受商品後七日內解除契約;保存期限為一個月。",
         "2010-01-01", None, "法律", None),
    )
    conn.commit()
    yield conn
    conn.close()


def test_period_swap_flagged(period_conn):
    # Corpus says 七日; claiming 十四日 is the period_swap blind spot the
    # mutation test exposed (0/602 before the check) — must flag.
    answer = "依期間測試法第1條,消費者得於十四日內解除契約。"
    r = verify_answer(answer, [], conn=period_conn)[0]
    assert r.exists is True
    assert r.content_match is False
    assert r.flagged is True
    assert "主張期間" in r.reason


def test_correct_period_not_flagged(period_conn):
    answer = "依期間測試法第1條,消費者得於七日內解除契約。"
    r = verify_answer(answer, [], conn=period_conn)[0]
    assert r.content_match is True
    assert r.flagged is False


def test_period_in_unstated_unit_not_flagged(period_conn):
    # The conservative rule only judges units the source itself states.
    # 「二週」: the source carries no 週-value — nothing to compare, must NOT
    # flag. (Known limit, documented in RESULTS: restating 一個月 as 三十日
    # NEXT TO a 七日 rule would flag, because the source does speak in 日 —
    # the price of catching 七日→十四日 without an LLM.)
    answer = "依期間測試法第1條,約二週內得解除契約。"
    r = verify_answer(answer, [], conn=period_conn)[0]
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


# ── False positives found by USING the assistant (six lived sessions) ────────
# Every case below is a CORRECT answer the verifier used to flag, or a real
# fabrication that must still be caught after the fix.
def test_common_abbreviation_resolves_to_corpus_name(real_conn):
    ans = ("依社維法第72條,製造噪音或深夜喧嘩,妨害公眾安寧,不聽禁止者,"
           "處新臺幣一萬元以下罰鍰。")
    [r] = verify_answer(ans, [], conn=real_conn, corpus_conn=real_conn)
    assert r.citation.statute_id == "社會秩序維護法"
    assert r.flagged is False


def test_cross_reference_inside_quoted_article_is_not_a_missing_source(real_conn):
    # 勞基§32-1's own text says 「雇主依第三十二條第一項…」. Read as a standalone
    # citation, the statute name became 「雇主依」 and the user got three scary
    # 「corpus 查無此法源」 warnings on a correct answer.
    ans = "依公寓大廈管理條例第47條,住戶違反第十六條第一項規定者,由主管機關處罰。"
    results = verify_answer(ans, [], conn=real_conn, corpus_conn=real_conn)
    assert [r.citation.article_no for r in results] == ["第47條", "第16條"]
    assert results[1].citation.inferred_id is True      # name inherited, not written
    assert not any(r.flagged for r in results)


def test_unnamed_reference_to_a_ghost_article_is_still_flagged(real_conn):
    ans = "依民法第184條負損害賠償責任,另依第9999條亦得請求。"
    results = verify_answer(ans, [], conn=real_conn, corpus_conn=real_conn)
    ghost = next(r for r in results if r.citation.article_no == "第9999條")
    assert ghost.citation.statute_id == "民法"          # inherited, then checked
    assert ghost.flagged is True


def test_two_citations_in_one_sentence_are_not_graded_on_each_others_numbers(real_conn):
    ans = ("依社會秩序維護法第72條處新臺幣一萬元以下罰鍰,"
           "依民法第195條得請求非財產上之損害賠償。")
    results = verify_answer(ans, [], conn=real_conn, corpus_conn=real_conn)
    assert not any(r.flagged for r in results), [r.reason for r in results if r.flagged]


def test_cross_reference_quoted_from_a_retrieved_source_is_not_called_recall(real_conn):
    # The 警察分工原則 names 噪音管制法第8條/第9條 in its own body. When the model
    # quotes it, 「模型可能憑記憶補充」 is simply false — but the referenced article
    # was not retrieved, so its content stays unchecked. Both things must be said.
    from legal_agent.data.models import Statute

    routing = Statute(
        "分工原則", "",
        "環保主管機關受理:燃放爆竹(噪音管制法第8條);超過管制標準者(噪音管制法第九條)。",
        "2020-01-01", None, "行政實務見解", "http://x",
    )
    ans = ("實務見解:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。"
           "依噪音管制法第8條由環保機關處理,另噪音管制法第9條亦同。"
           "又依噪音管制法第99條,住戶應保持安寧。")
    results = {r.citation.article_no: r for r in
               verify_answer(ans, [routing], corpus_conn=real_conn)}
    assert results["第8條"].flagged is False and "交叉引用" in results["第8條"].reason
    assert results["第9條"].flagged is False        # written 第九條 in the source
    assert results["第99條"].flagged is True        # not in the quoted text -> recall
    # A citation resolved ONLY via the retrieved source's own quoted text was
    # never checked against the corpus, so it reads as unverified, not clean.
    assert results["第8條"].unverified is True
    assert results["第9條"].unverified is True
    # 第99條 is a genuine miss (exists=False, flagged=True), not merely unverified.
    assert results["第99條"].unverified is False
    line = verification_status_line(list(results.values()))
    assert "全數可回溯至資料庫" not in line, line
    assert line == (
        "引用查核:3 筆引用中 1 筆有疑慮,逐筆如下。" + VERIFIED_SCOPE_NOTE
    ), line


def test_bracketed_and_spaced_citation_forms_are_extracted(real_conn):
    # 「根據《民法》第9999條」 used to extract NOTHING — the verifier never saw a
    # pure fabrication because of how the model punctuated it.
    for form in ("根據《民法》第184條,負損害賠償責任。",
                 "(《民法》第184條)因故意或過失不法侵害他人之權利者。",
                 "依「民法」第184條規定。",
                 "民法 第184條 規定。"):
        [r] = verify_answer(form, [], conn=real_conn, corpus_conn=real_conn)
        assert (r.citation.statute_id, r.citation.article_no) == ("民法", "第184條"), form
        assert r.flagged is False, form

    [ghost] = verify_answer("根據《民法》第9999條,亦得請求。", [],
                            conn=real_conn, corpus_conn=real_conn)
    assert ghost.flagged is True


def test_amount_before_its_citation_is_still_checked(real_conn):
    # The clause clip must not become a hole: a claim written BEFORE its
    # citation still belongs to it.
    ans = "違者可處新臺幣999999元罰鍰,依社會秩序維護法第72條辦理。"
    [r] = verify_answer(ans, [], conn=real_conn, corpus_conn=real_conn)
    assert r.flagged is True and "999999" in r.reason


def test_status_line_still_claims_full_traceability_when_every_citation_is_verified_clean(
    real_conn,
):
    # Positive control for the A2 status-line rewrite: it only narrows WHEN
    # the green line prints (flagged AND unverified must both be empty), it
    # must not stop printing it for the case that genuinely earns it.
    ans = "民法第793條規定,土地所有人對於他人土地散發的喧囂、振動侵入,得予禁止。"
    results = verify_answer(ans, [], conn=real_conn)
    line = verification_status_line(results)
    assert line == (
        f"引用查核:{len(results)} 筆引用全數可回溯至資料庫。{VERIFIED_SCOPE_NOTE}"
    ), line


# ── A1 qualifier-gate regressions ────────────────────────────────────────────
# _resolve_id's plain `matches = [kid for kid in known_ids if
# name_run.endswith(kid)]` accepts the LONGEST suffix match unconditionally,
# which launders any country/era/region prefix in front of a real statute
# name (「德國民法」 -> 民法) — and a gate strict enough to reject those must not
# also reject ordinary Chinese legal prose (「房東依民法」、「查民法」…), which a
# verb-character allowlist design was measured to do on 24/31 real sentences.
@pytest.fixture
def particle_collision_conn(tmp_path):
    """INVENTED corpus: a law and the 「違反…辦法」 that is its OWN enforcement
    measure — both real corpus statute_ids (違反社會秩序維護法案件處理辦法 is
    the actual MOJ name of the 社會秩序維護法 enforcement measure). 「違反」 is
    itself one of the leading particles _strip_particle knows how to peel off,
    so a resolver that keeps stripping past a match already found (instead of
    short-circuiting the moment the CURRENT string is a known id) can shear
    違反社會秩序維護法案件處理辦法 down into 社會秩序維護法. real_conn (9 住宅噪音
    rows) does not carry the 辦法, hence this dedicated fixture."""
    db = tmp_path / "pcol.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("社會秩序維護法", "第72條", "測試用條文內容一。", "2010-01-01", None, "法律", None),
            ("違反社會秩序維護法案件處理辦法", "第3條", "測試用條文內容二。",
             "2010-01-01", None, "法律", None),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


def test_particle_collision_statute_and_its_own_processing_measure_do_not_launder(
    particle_collision_conn,
):
    a = verify_answer("依社會秩序維護法第72條,規定內容。", [], conn=particle_collision_conn)[0]
    assert a.citation.statute_id == "社會秩序維護法"
    assert a.exists is True and a.flagged is False

    b = verify_answer(
        "依違反社會秩序維護法案件處理辦法第3條,規定內容。", [], conn=particle_collision_conn,
    )[0]
    assert b.citation.statute_id == "違反社會秩序維護法案件處理辦法"
    assert b.exists is True and b.flagged is False


@pytest.fixture
def prefix_gate_conn(tmp_path):
    """INVENTED corpus for the qualifier-gate battery: 民法/噪音管制法/中華民國
    刑法/勞動基準法, each carrying an article a fabricated country/era/region
    prefix is planted against. 第440條 is the exact article number the A1 spec
    text uses for its 「民法 第440條」 spaced-citation regression form, so the
    prose-prefix cases below reuse the same row."""
    db = tmp_path / "pgate.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("民法", "第440條", "測試用條文內容(440)。", "2000-01-01", None, "法律", None),
            ("民法", "第441條", "測試用條文內容(441)。", "2000-01-01", None, "法律", None),
            ("噪音管制法", "第1條", "測試用條文內容(噪音)。", "2000-01-01", None, "法律", None),
            ("中華民國刑法", "第1條", "測試用條文內容(刑法)。", "2000-01-01", None, "法律", None),
            ("勞動基準法", "第24條", "測試用條文內容(勞基)。", "2000-01-01", None, "法律", None),
        ],
    )
    conn.commit()
    yield conn
    conn.close()


_PREFIX_LAUNDERING_CASES = [
    ("德國民法", "依德國民法第440條,規定內容。"),
    ("舊民法", "舊民法第440條,規定內容。"),
    ("中國民法", "中國民法第440條,規定內容。"),
    ("臺北市噪音管制法", "臺北市噪音管制法第1條,規定內容。"),
    ("美國中華民國刑法", "美國中華民國刑法第1條,規定內容。"),
]


@pytest.mark.parametrize(
    "label,answer", _PREFIX_LAUNDERING_CASES, ids=[c[0] for c in _PREFIX_LAUNDERING_CASES],
)
def test_country_era_region_prefixed_statute_names_are_flagged(label, answer, prefix_gate_conn):
    # Measured on today's unmodified _resolve_id (2026-08-17): all five
    # launder into the real statute via plain endswith and come back
    # flagged=False, exists=True — a fabricated statute name presented as if
    # the corpus actually had it. The planted article number is one that IS
    # real for the base statute (民法 第440條 / 噪音管制法 第1條 / 中華民國刑法
    # 第1條), so a laundering bug would ALSO get exists=True here — that is
    # what makes flagged=True below a genuine signal of the qualifier gate,
    # not an accident of citing an article nobody has.
    r = verify_answer(answer, [], conn=prefix_gate_conn)[0]
    assert r.flagged is True, (label, r.citation.statute_id, r.exists, r.reason)


_PREFIX_GATE_TRUE_POSITIVES = [
    ("依民法", "依民法第440條,規定內容。", "民法", "第440條"),
    ("按民法", "按民法第440條,規定內容。", "民法", "第440條"),
    ("根據《民法》", "根據《民法》第440條,規定內容。", "民法", "第440條"),
    ("民法 第440條(空格)", "民法 第440條 規定內容。", "民法", "第440條"),
    ("前開民法", "前開民法第440條,規定內容。", "民法", "第440條"),
    ("揆諸民法", "揆諸民法第440條,規定內容。", "民法", "第440條"),
    ("並依民法", "並依民法第440條,規定內容。", "民法", "第440條"),
    ("並依據民法", "並依據民法第440條,規定內容。", "民法", "第440條"),
    ("業依勞動基準法", "業依勞動基準法第24條,規定內容。", "勞動基準法", "第24條"),
]


@pytest.mark.parametrize(
    "label,answer,expected_id,expected_ano", _PREFIX_GATE_TRUE_POSITIVES,
    ids=[c[0] for c in _PREFIX_GATE_TRUE_POSITIVES],
)
def test_prose_prefixes_before_a_real_statute_name_still_resolve(
    label, answer, expected_id, expected_ano, prefix_gate_conn,
):
    # These forms exist ONLY to make sure a qualifier gate strict enough to
    # catch the five 「德國民法」-style cases above does not also reject
    # ordinary Chinese legal prose. Includes the original six 正例 forms
    # (依/按/根據《》/空格/前開/同法-in-a-dedicated-test-below) plus 揆諸 and the
    # 並依/並依據 multi-particle-stack cases the Tier2 check-after-each-strip
    # design exists to solve.
    r = verify_answer(answer, [], conn=prefix_gate_conn)[0]
    assert r.citation.statute_id == expected_id, (label, r.citation.statute_id)
    assert r.exists is True, (label, r.reason)
    assert r.flagged is False, (label, r.reason)


_REAL_CONN_PREFIX_TRUE_POSITIVES = [
    ("房東依民法", "房東依民法第184條,負損害賠償責任。", "民法", "第184條"),
    ("房客依民法", "房客依民法第184條,負損害賠償責任。", "民法", "第184條"),
    ("管委會依公寓大廈管理條例",
     "管委會依公寓大廈管理條例第16條,住戶不得任意棄置垃圾。", "公寓大廈管理條例", "第16條"),
    ("警察依社會秩序維護法",
     "警察依社會秩序維護法第72條,得依法處理。", "社會秩序維護法", "第72條"),
    ("本件民法", "本件民法第184條規定,負損害賠償責任。", "民法", "第184條"),
    ("系爭民法", "系爭民法第184條規定,負損害賠償責任。", "民法", "第184條"),
    ("被告依民法", "被告依民法第184條,負損害賠償責任。", "民法", "第184條"),
    ("查民法", "查民法第184條,負損害賠償責任。", "民法", "第184條"),
    ("爰依民法", "爰依民法第184條,負損害賠償責任。", "民法", "第184條"),
    ("被害人因具民法", "被害人因具民法第184條情事,得請求。", "民法", "第184條"),
    ("包括民法", "包括民法第184條,規定內容。", "民法", "第184條"),
    ("上開情形涉及社會秩序維護法",
     "上開情形涉及社會秩序維護法第72條,得依法處理。", "社會秩序維護法", "第72條"),
]


@pytest.mark.parametrize(
    "label,answer,expected_id,expected_ano", _REAL_CONN_PREFIX_TRUE_POSITIVES,
    ids=[c[0] for c in _REAL_CONN_PREFIX_TRUE_POSITIVES],
)
def test_prose_prefixes_found_in_real_corpus_text_still_resolve(
    label, answer, expected_id, expected_ano, real_conn,
):
    # 「被害人因具」 and 「包括」 are not invented for this test: they are the
    # actual prefixes in front of a 民法 cross-reference inside 家庭暴力防治法
    # 第58-2條 and 消費者保護法第50條's own text. CONTRIBUTING.md requires
    # verbatim statute text in answers ("Verbatim or nothing"), so sentences
    # exactly like these WILL reach the verifier unchanged — a qualifier gate
    # that rejects them turns a correct, verbatim answer into a false
    # 「corpus 查無此法源」 warning.
    r = verify_answer(answer, [], conn=real_conn)[0]
    assert r.citation.statute_id == expected_id, (label, r.citation.statute_id)
    assert r.citation.article_no == expected_ano, (label, r.citation.article_no)
    assert r.exists is True, (label, r.reason)
    assert r.flagged is False, (label, r.reason)


def test_anaphoric_same_law_reference_after_a_named_citation_resolves(real_conn):
    # 「同法第X條」 — the sixth of the six original 正例 forms. inferred_id must
    # be True (its content is not graded against the wrong sentence) and it
    # must still resolve to the SAME statute as the citation named before it.
    ans = "依民法第184條,負損害賠償責任;同法第195條,情節重大者得請求非財產上損害賠償。"
    results = verify_answer(ans, [], conn=real_conn)
    assert [r.citation.article_no for r in results] == ["第184條", "第195條"]
    named, anaphoric = results
    assert named.citation.inferred_id is False
    assert anaphoric.citation.statute_id == "民法"
    assert anaphoric.citation.inferred_id is True
    assert not any(r.flagged for r in results), [r.reason for r in results]


# ── A7 bare penalty amount scanner (masked scan) ─────────────────────────────
def _bare_penalty_amounts_fn():
    from legal_agent.anti_hallucination.verifier import _bare_penalty_amounts

    return _bare_penalty_amounts


def test_bare_penalty_amounts_does_not_swallow_article_numbers_or_fractions():
    # The literal A7 spec example, kept as the reviewed (not the originally
    # proposed) expected value: reusing _YUAN_RE's comma-bearing character
    # class for the masked scan turns the isolated clause commas this sentence
    # leaves behind into a phantom {0} — the fix must anchor on a
    # 罰鍰/罰金/科處/併科 keyword and a numeral class WITHOUT the comma.
    bare = _bare_penalty_amounts_fn()
    result = bare("依中華民國刑法第七十七條規定,累犯逾三分之二,得許假釋出獄,另可處罰鍰十萬。")
    assert result == {100000}, result


def test_bare_penalty_amounts_does_not_treat_a_lone_comma_as_a_zero_amount():
    # Reviewed evidence: masking citations out of 「依中華民國刑法第223條,其規範
    # 內容如條文所示。」 leaves an isolated 「,」 behind; scanning it with _YUAN_RE's
    # comma-bearing character class parses that comma as a bare 0-yuan amount.
    # 169/2921 real corpus control sentences false-positive this way if the
    # scanner is not keyword-anchored. Must be empty.
    bare = _bare_penalty_amounts_fn()
    assert bare("依中華民國刑法第223條,其規範內容如條文所示。") == set()


def test_bare_penalty_amounts_still_catches_a_real_bare_penalty():
    bare = _bare_penalty_amounts_fn()
    assert 1000000 in bare("違者處罰鍰最高一百萬,並得按次處罰。")


# ── A8 period-direction / fraction axes, against the LIVE shipped corpus ────
# 消保法§19 and 民法§1144 are not in the small real_conn fixture (9 住宅噪音
# rows) — these are regressions against the actual corpus, same skip-if-absent
# guard every other live-DB test in this suite already uses.
@pytest.fixture
def live_conn(shipped_conn):
    return shipped_conn


def test_correct_seven_day_restatement_of_consumer_protection_act_19_not_flagged(live_conn):
    # Real corpus text: 「…得於收受商品或接受服務後七日內…解除契約…」
    answer = "依消費者保護法第19條,消費者得於收受商品後七日內解除契約。"
    r = verify_answer(answer, [], conn=live_conn)[0]
    assert r.exists is True and r.content_match is True and r.flagged is False


def test_period_direction_axis_flags_a_flipped_seven_day_window(live_conn):
    # Measured on today's verifier (2026-08-17): flagged=False — _periods()
    # only ever compares the NUMBER (7), never the direction word, so 七日內
    # flipped to 七日以上 passes silently. Period-axis twin of the amount
    # direction_flip check that already exists.
    answer = "依消費者保護法第19條,消費者得於收受商品後七日以上始得解除契約。"
    r = verify_answer(answer, [], conn=live_conn)[0]
    assert r.flagged is True, r.reason


def test_correct_inheritance_fraction_restatement_of_civil_code_1144_not_flagged(live_conn):
    # Real corpus text: 「…其應繼分為遺產二分之一。…其應繼分為遺產三分之二。」
    answer = "依民法第1144條,與第二順序繼承人同為繼承時,應繼分為遺產二分之一。"
    r = verify_answer(answer, [], conn=live_conn)[0]
    assert r.exists is True and r.content_match is True and r.flagged is False


def test_fraction_axis_flags_a_share_the_article_never_states(live_conn):
    # 四分之三 appears NOWHERE in 民法第1144條 (only 二分之一 and 三分之二 do) —
    # chosen specifically so this is not the 三分之一<->三分之二-style equivalent
    # mutant the fraction-tamper generator has to guard against (that article
    # states BOTH of those values, so swapping one for the other is still
    # "supported" and proves nothing about the axis).
    answer = "依民法第1144條,與第二順序繼承人同為繼承時,應繼分為遺產四分之三。"
    r = verify_answer(answer, [], conn=live_conn)[0]
    assert r.flagged is True, r.reason


# ── evals/blindspots_v1.json + the positive-control file ───────────────────
# The same cases `python -m legal_agent.evaluation.blindspots` scores, with the
# same calling convention (full-corpus conn, empty retrieved_context).

# The four cases the structural axes still cannot see. Three are a modal or
# proviso changed inside a real, correctly-cited article (得→應, 得禁止→不得禁止,
# an inverted 但書); the fourth is a 同法 reference whose inherited citation is
# never compared against its article. Catching them needs a semantic axis, and
# the one this repo has misfires on 43% of correct citations.
#
# strict=True on purpose: if a later change catches one of these, this test
# goes red and says so. That is how the published 21/25 stays honest in both
# directions.
_STILL_BLIND = {
    "modal_de_to_ying",
    "modal_full_negation",
    "proviso_reversal",
    "anaphora_tong_fa_20",
}


def _blindspot_param(case):
    if case.id in _STILL_BLIND:
        return pytest.param(
            case,
            id=f"{case.id}-{case.category}",
            marks=pytest.mark.xfail(strict=True, reason=f"{case.id}: counted as a miss in 21/25"),
        )
    return pytest.param(case, id=f"{case.id}-{case.category}")


@pytest.mark.parametrize("case", [_blindspot_param(c) for c in load_blindspot_cases()])
def test_blindspots_case_agrees_with_the_frozen_json(case, live_conn):
    results = verify_answer(case.answer, [], conn=live_conn)
    flagged = any(r.flagged for r in results)
    assert flagged == case.expect_flag, (
        f"{case.id} [{case.category}]: expected flag={case.expect_flag}, got "
        f"{flagged} — reasons={[r.reason for r in results]}"
    )


@pytest.mark.parametrize(
    "case", [pytest.param(c, id=f"{c.id}-{c.label}") for c in load_positive_control_cases()]
)
def test_positive_control_case_agrees_with_the_frozen_json(case, live_conn):
    results = verify_answer(case.answer, [], conn=live_conn)
    flagged = any(r.flagged for r in results)
    assert flagged is False, (
        f"{case.id} [{case.label}]: expected flag=False, got {flagged} — "
        f"reasons={[r.reason for r in results]}"
    )


# ── numerals and 文號 adjacency (found by audit, 2026-10-16) ──────────────────
@pytest.mark.parametrize("text, value", [
    ("一〇〇〇〇", 10000),     # positional digits used to read as 0
    ("二〇二三", 2023),
    ("一〇五", 105),
    ("一千零五", 1005),       # a 零 after a unit is still a placeholder
    ("三萬零五百", 30500),
    ("萬", None),             # 「數萬元」 states no amount (used to read as 0)
    ("十", 10),
    ("壹拾萬伍仟伍佰伍拾陸", 105556),
])
def test_parse_number_reads_positional_digits_and_refuses_a_bare_big_unit(text, value):
    from legal_agent.anti_hallucination.verifier import _parse_number

    assert _parse_number(text) == value


def test_a_positional_amount_that_matches_the_article_is_not_flagged(live_conn):
    r = verify_answer("依社會秩序維護法第72條,最高處新臺幣一〇〇〇〇元罰鍰。", [], conn=live_conn)[0]
    assert r.flagged is False, r.reason


def test_a_docnum_after_the_citation_does_not_switch_off_the_amount_check(live_conn):
    answer = "依社會秩序維護法第72條及內政部台內警字第123號函,處九萬元以下罰鍰。"
    by_raw = {r.citation.raw: r for r in verify_answer(answer, [], conn=live_conn)}
    assert by_raw["依社會秩序維護法第72條"].flagged is True
    assert "90000" in by_raw["依社會秩序維護法第72條"].reason
    assert "及內政部台內警字第123號" in by_raw      # the 文號 is still extracted on its own


def test_a_multi_list_article_flags_only_an_item_above_every_list(live_conn):
    """民法§129 has two lists (一~三, then 一~五). Which one 「第4款」 means is
    undecidable, so it stays unverified; 「第6款」 is in neither and is a ghost."""
    above = verify_answer("依民法第129條第6款,時效中斷。", [], conn=live_conn)[0]
    assert above.flagged is True and "第5款" in above.reason
    within = verify_answer("依民法第129條第4款,時效中斷。", [], conn=live_conn)[0]
    assert within.flagged is False and within.unverified is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
