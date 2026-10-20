"""The public 裁判書查詢 source: parsing, caching and manners — all offline.

The pages below are trimmed copies of the site's real markup with the text
replaced; no request leaves the machine.
"""
from __future__ import annotations

import json

import pytest

from legal_agent.data import fjud
from legal_agent.data.judicial_json import parse_judgment
from legal_agent.evaluation.judgment_relevance import case_type_family

LIST_PAGE = """
<span>共 1349 筆</span>
<tr><td width="1%" nowrap="nowrap">1.</td>
<td><a id="hlTitle" class="hlTitle_scroll" onClick="cookieId()"
 href="data.aspx?ty=JD&amp;id=KSDV%2c115%2c%e8%a8%b4%2c973%2c20261014%2c1&amp;ot=in">臺灣高雄地方法院 115 年度 訴 字第 973 號民事裁定</a>（2K）</td>
<td>115.10.14</td>
<td width="30%">返還寄託物</td></tr>
<tr><td width="1%" nowrap="nowrap">2.</td>
<td><a id="hlTitle" class="hlTitle_scroll" onClick="cookieId()"
 href="data.aspx?ty=JD&amp;id=TPHV%2c114%2c%e9%87%8d%e4%b8%8a%2c321%2c20260929%2c2&amp;ot=in">臺灣高等法院 114 年度 重上 字第 321 號民事判決</a>（60K）</td>
<td>115.09.29</td>
<td width="30%">返還寄託物</td></tr>
"""

# The newer layout: one <div> per line inside .htmlcontent, then an empty
# .text-pre that carries only upload metadata in HTML comments.
DOC_HTML_LAYOUT = """
<div class="col-th">裁判案由：</div>
<div class="col-td">返還寄託物</div>
<div class="htmlcontent"><div class="he-h1">臺灣高等法院民事判決</div><div>114年度重上字第321號</div>
<div>上　訴　人  王○○</div><div><div>被 上訴 人  李○○</div></div>
<div>上列當事人間請求返還寄託物事件，本院判決如下：</div>
<div>　　主　文</div><div>被上訴人應給付上訴人新臺幣壹拾萬元。</div>
<div>　　理　由</div><div>按寄託物返還之期限，雖經約定，寄託人仍得隨時請求返還，民法第597條定有明文。</div></div>
<div class="text-pre text-pre-in">
<!-- 主文：[被上訴人應給付上訴人新臺幣壹拾萬元。] --></div>
"""

# The older layout: the whole text preformatted.
DOC_PRE_LAYOUT = """
<div class="col-th">裁判案由：</div>
<div class="col-td">返還借用物</div>
<div class="text-pre text-pre-in">臺灣臺北地方法院民事判決
113年度訴字第1號
原　　　告  王○○
主　　文
被告應將房屋騰空返還原告。
事實及理由
按借用人應於契約所定期限屆滿時，返還借用物，民法第470條第1項定有明文。
</div>
"""

JID = "TPHV,114,重上,321,20260929,2"


def test_list_rows_carry_the_jid_the_api_uses():
    rows, total = fjud.parse_list(LIST_PAGE)
    assert total == 1349
    assert [r.jid for r in rows] == ["KSDV,115,訴,973,20261014,1", JID]
    assert [r.case_type for r in rows] == ["返還寄託物", "返還寄託物"]
    assert [r.is_judgment for r in rows] == [False, True]      # 裁定 is skipped


@pytest.mark.parametrize("page,case_type", [(DOC_HTML_LAYOUT, "返還寄託物"),
                                            (DOC_PRE_LAYOUT, "返還借用物")])
def test_both_page_layouts_yield_the_importer_record(page, case_type):
    record = fjud.parse_document(page, JID)
    assert record["JID"] == JID and record["JYEAR"] == "114"
    assert record["JTITLE"] == case_type
    text = record["JFULL"]
    assert "主文：[" not in text            # upload metadata is not judgment text
    assert "\n\n" not in text               # nested </div>s leave no blank lines
    assert text.splitlines()[0].endswith("判決")


def test_a_fetched_record_goes_through_the_unchanged_importer():
    record = fjud.parse_document(DOC_HTML_LAYOUT, JID)
    row, warnings = parse_judgment(record, {"民法"})
    assert not warnings
    assert json.loads(row["cited_articles"]) == [{"statute_id": "民法", "article_no": "第597條"}]

    from legal_agent.data.judgment_text import citation, main_text

    assert citation(row["full_text"]) == "臺灣高等法院民事判決 114年度重上字第321號"
    assert main_text(row["full_text"]) == "被上訴人應給付上訴人新臺幣壹拾萬元。"


def test_an_empty_page_is_no_record():
    assert fjud.parse_document("<html></html>", JID) is None


def test_every_family_query_reads_back_as_its_family():
    """A 案由 query whose results the family table cannot read as that family
    could never fill it."""
    for family, queries in fjud.FAMILY_QUERIES.items():
        for query in queries:
            assert case_type_family(query) == family, query


def test_the_delay_cannot_be_set_below_three_seconds():
    assert fjud.Client(delay=0.1).delay == fjud.MIN_DELAY == 3.0


def test_cached_documents_are_never_fetched_again(tmp_path):
    cache = fjud.Cache(tmp_path)
    record = fjud.parse_document(DOC_HTML_LAYOUT, JID)
    cache.doc_path(JID).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    class NoNetwork(fjud.Client):
        def get(self, *a, **kw):
            raise AssertionError("cache hit must not touch the network")

    assert fjud.document(NoNetwork(), cache, JID) == record


def test_cached_list_pages_resume_without_a_search(tmp_path):
    cache = fjud.Cache(tmp_path)
    rows, total = fjud.parse_list(LIST_PAGE)
    cache.list_path("返還寄託物", "", 1).write_text(json.dumps(
        {"title": "返還寄託物", "sys": "", "page": 1, "total": total,
         "rows": [r.__dict__ for r in rows]}, ensure_ascii=False), encoding="utf-8")

    class NoNetwork(fjud.Client):
        def get(self, *a, **kw):
            raise AssertionError("a cached page must not touch the network")

    # Fewer than 20 rows on page 1 = the last page, so no second request either.
    got = list(fjud.list_rows(NoNetwork(), cache, "返還寄託物", pages=3))
    assert [r.jid for r in got] == [r.jid for r in rows]


def test_an_article_is_searched_the_way_judgments_write_it():
    assert fjud._site_term("民法第429條") == "第429條"
    assert fjud._site_term("民法第753-1條") == "第753條之1"


def test_a_full_text_term_gets_its_own_cache_entry(tmp_path):
    cache = fjud.Cache(tmp_path)
    assert cache.list_path("租賃", "", 1) != cache.list_path("租賃", "", 1, kw="第429條")


def test_questions_without_judgments_reads_family_and_article(tmp_path):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE judgments (jid TEXT, case_type TEXT, cited_articles TEXT)")
    conn.execute("INSERT INTO judgments VALUES ('J1', '返還寄託物', ?)",
                 (json.dumps([{"statute_id": "民法", "article_no": "第597條"}]),))
    path = tmp_path / "qa.json"
    path.write_text(json.dumps({"questions": [
        {"id": "has", "family": "寄託", "expected_statutes": ["民法第597條"]},
        {"id": "other-article", "family": "寄託", "expected_statutes": ["民法第602條"]},
        {"id": "other-family", "family": "使用借貸", "expected_statutes": ["民法第597條"]},
    ]}, ensure_ascii=False), encoding="utf-8")
    assert [q["id"] for q in fjud.questions_without_judgments(conn, path)] == [
        "other-article", "other-family"]
