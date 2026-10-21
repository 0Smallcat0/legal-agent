"""The shipped judgment corpus: what it redacts, and what it must never carry.

The contract is narrow on purpose. `redact()` may drop anything it likes, but
it may NOT change what the page renders — `citation()` and `awards()` have to
return the same values they returned on the full document — and it may not ship
a party's name.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from legal_agent.data.bootstrap import JUDGMENTS, ensure_corpus, judgment_count
from legal_agent.data.database import connect, init_db
from legal_agent.data.judgment_ingest import (
    MAIN_HEADING,
    load_judgments,
    names_in_main_text,
    party_names,
    redact,
    surfaceable,
)
from legal_agent.data.judgment_text import awards, citation

# A synthetic judgment in the shape the courts actually emit: ideographic
# spacing in the labels and the 主文 heading, a party block, a wrapped 主文,
# and a 理由 section that must never be shipped.
ROLE_JUDGMENT = """臺灣範例地方法院民事判決
999年度範訴字第1號
原      告  王測試
被      告  範例科技股份有限公司
            李助手
上列當事人間請求損害賠償事件,本院判決如下:
主　　文
被告應連帶給付原告新臺幣壹萬元,及自起訴狀繕本送達翌日起至清償日
    止,按年息百分之五計算之利息。
訴訟費用新臺幣壹仟元由被告負擔。
理　　由
原告主張其住於臺北市範例路一段一號,被告李助手於民國九十九年…
"""

# Same shape, but the 主文 itself names the defendant — this one must ship with
# its header only.
NAMED_IN_MAIN_TEXT = """臺灣範例地方法院民事判決
999年度範訴字第2號
原      告  陳範例
被      告  林樣本
上列當事人間請求給付借款事件,本院判決如下:
主　　文
被告林樣本應給付原告新臺幣貳萬元。
理　　由
兩造於民國九十九年間簽訂借據…
"""


def test_redaction_keeps_exactly_what_the_page_renders():
    trimmed = redact(ROLE_JUDGMENT)
    assert citation(trimmed) == citation(ROLE_JUDGMENT)
    assert awards(trimmed) == awards(ROLE_JUDGMENT) == (10000,)


def test_redaction_drops_the_party_block_and_the_reasoning():
    trimmed = redact(ROLE_JUDGMENT)
    assert "王測試" not in trimmed
    assert "李助手" not in trimmed
    assert "理　　由" not in trimmed
    assert "臺北市範例路一段一號" not in trimmed


def test_party_names_reads_the_judgment_s_own_block_not_a_surname_guess():
    names = party_names(ROLE_JUDGMENT)
    assert names == {"王測試", "李助手"}       # the company is not a person
    # 「連帶給付」 is surname-shaped and appears in the 主文; it is not a party.
    assert "連帶" not in names
    assert names_in_main_text(ROLE_JUDGMENT) == set()


def test_a_name_inside_the_main_text_costs_the_main_text_not_the_judgment():
    assert names_in_main_text(NAMED_IN_MAIN_TEXT) == {"林樣本"}
    trimmed = redact(NAMED_IN_MAIN_TEXT)
    assert "林樣本" not in trimmed
    assert "陳範例" not in trimmed
    assert MAIN_HEADING not in trimmed
    # It still identifies itself, so it can still surface beside the law.
    assert citation(trimmed) == citation(NAMED_IN_MAIN_TEXT)
    # And the award simply goes silent — the block already renders that case.
    assert awards(trimmed) == ()


SOCIAL_ORDER_RULING = (
    "臺灣範例地方法院簡易庭裁定\n115年度範秩字第1號\n"
    "移送機關\xa0 \xa0 範例市警察局\n被移送人\xa0 \xa0 林樣本\n"
    "上列被移送人因違反社會秩序維護法案件,本院裁定如下:\n"
    "　　主　文\n林樣本無正當理由攜帶具有殺傷力之器械,處罰鍰新臺幣8000元。\n"
    "　　理　由\n一、被移送人林樣本違法之事實如下。\n"
)
NON_PARTY_IN_MAIN_TEXT = (
    "臺灣範例地方法院民事判決\n114年度訴字第1號\n原      告  範例銀行股份有限公司\n"
    "上列當事人間請求履行保證債務事件,本院判決如下:\n主　　文\n"
    "被告於原告對訴外人陳範例之財產執行無效果時,應給付原告新臺幣10萬元。\n"
    "事實及理由\n略。\n"
)


def test_a_social_order_ruling_names_its_person_as_被移送人():
    """社維法 rulings carry no 原告/被告; the person fined is 被移送人, and the
    主文 opens with that name (two backfilled rulings did, unmasked)."""
    assert names_in_main_text(SOCIAL_ORDER_RULING) == {"林樣本"}
    assert "林樣本" not in redact(SOCIAL_ORDER_RULING)


def test_a_non_party_named_in_the_main_text_withholds_it_too():
    assert names_in_main_text(NON_PARTY_IN_MAIN_TEXT) == {"陳範例"}
    assert "陳範例" not in redact(NON_PARTY_IN_MAIN_TEXT)
    masked = NON_PARTY_IN_MAIN_TEXT.replace("陳範例", "陳○○")
    assert names_in_main_text(masked) == set()


def _seed(conn: sqlite3.Connection, jid: str, full_text: str, cited: list[dict]) -> None:
    conn.execute(
        "INSERT INTO judgments (jid, court, year, case_type, cited_articles, full_text)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (jid, "臺灣範例地方法院", 999, "損害賠償",
         json.dumps(cited, ensure_ascii=False), full_text),
    )


def test_only_judgments_citing_a_corpus_statute_are_shipped(tmp_path):
    path = tmp_path / "t.db"
    ensure_corpus(str(path))                     # gives us a real statute corpus
    conn = connect(str(path))
    conn.execute("DELETE FROM judgments")
    _seed(conn, "IN,1", ROLE_JUDGMENT, [{"statute_id": "民法", "article_no": "第184條"}])
    _seed(conn, "OUT,1", ROLE_JUDGMENT,
          [{"statute_id": "票據法", "article_no": "第1條"}])   # not in the corpus
    conn.commit()

    shipped = surfaceable(conn)
    assert [r["jid"] for r in shipped] == ["IN,1"]
    assert shipped[0]["cited_articles"] == [{"statute_id": "民法", "article_no": "第184條"}]


def test_load_judgments_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    init_db(str(path))
    conn = connect(str(path))
    shipped = tmp_path / "j.json"
    shipped.write_text(json.dumps([{
        "jid": "X,1", "court": "臺灣範例地方法院", "year": 999,
        "case_type": "損害賠償",
        "cited_articles": [{"statute_id": "民法", "article_no": "第184條"}],
        "full_text": redact(ROLE_JUDGMENT),
    }], ensure_ascii=False), encoding="utf-8")

    assert load_judgments(shipped, conn) == 1
    assert load_judgments(shipped, conn) == 0
    assert judgment_count(conn) == 1


def test_load_judgments_rejects_a_record_with_no_jid(tmp_path):
    path = tmp_path / "t.db"
    init_db(str(path))
    conn = connect(str(path))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"court": "臺灣範例地方法院"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="jid"):
        load_judgments(bad, conn)


def test_a_fresh_clone_gets_the_reference_judgments(tmp_path):
    """The defect this whole module exists to close: statutes shipped, judgments
    did not, so the README's screenshot was unreproducible."""
    path = tmp_path / "fresh.db"
    ensure_corpus(str(path))
    conn = connect(str(path))
    assert judgment_count(conn) > 0


def test_the_shipped_file_carries_no_party_name():
    """Guards the file itself, not just the function that wrote it."""
    from legal_agent import config

    shipped = config.CORPUS_DIR / JUDGMENTS
    records = json.loads(shipped.read_text(encoding="utf-8"))
    assert records, "shipped judgment corpus is empty"
    for record in records:
        text = record["full_text"]
        assert names_in_main_text(text) == set()
        # The party block is the other place a name could ride in.
        assert party_names(text) == set()
