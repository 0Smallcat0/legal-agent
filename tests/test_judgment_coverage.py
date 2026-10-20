"""`judgment_coverage` — what counts as a family's stock, and the target.

The stock rule has two halves and each one is load-bearing: a judgment counts
for a family only if its 案由 names the family AND it cites an article of that
family. Without the second half a case could be counted that the JOIN in
`related_judgments` can never bring to a page.
"""
from __future__ import annotations

import json
from pathlib import Path

from legal_agent.evaluation.judgment_coverage import (
    TARGET,
    CoverageReport,
    Row,
    nameable,
    serves_family,
    session_families,
    stock_by_family,
)

ROOT = Path(__file__).resolve().parents[1]


def _cite(sid, ano):
    return {"statute_id": sid, "article_no": ano}


def test_a_judgment_serves_a_family_only_through_an_article_of_it():
    assert serves_family("遷讓房屋等", [_cite("民法", "第455條")]) == "租賃"
    # 案由 says 租賃, but no 租賃 article — the JOIN can never surface it there.
    assert serves_family("遷讓房屋等", [_cite("民法", "第184條")]) is None


def test_a_generic_or_cross_cutting_case_type_serves_nothing():
    assert serves_family("損害賠償", [_cite("民法", "第184條")]) is None
    assert serves_family("履行契約", [_cite("民法", "第227條")]) is None
    assert serves_family(None, [_cite("民法", "第184條")]) is None


def test_session_families_drop_cross_cutting_rules():
    assert session_families(["民法第273條", "民法第474條"]) == ["消費借貸"]
    assert session_families(["民法第125條"]) == []


def test_target_is_one_page_of_judgments():
    """related_judgments shows three by default; the target is that page."""
    import inspect

    from legal_agent.retrieval.judgments import related_judgments

    assert inspect.signature(related_judgments).parameters["limit"].default == TARGET


def test_missing_counts_only_up_to_the_target():
    report = CoverageReport(families={
        "租賃": Row("租賃", stock=6),
        "贈與": Row("贈與", stock=0),
        "擔保物權": Row("擔保物權", stock=1),
    })
    assert report.deficits() == {"贈與": 3, "擔保物權": 2}
    assert report.at_target == 1
    assert report.missing == 5


def test_stock_reads_the_shipped_corpus(shipped_conn):
    stock = stock_by_family(shipped_conn)
    shipped = json.loads((ROOT / "legal_agent" / "corpus" / "judgments_v1.json")
                         .read_text(encoding="utf-8"))
    by_jid = {r["jid"]: r for r in shipped}
    for family, jids in stock.items():
        for jid in jids:
            row = by_jid[jid]
            assert serves_family(row["case_type"], row["cited_articles"]) == family


def test_the_harness_runs_end_to_end(tmp_path, shipped_conn):
    """A slice, as in test_judgment_relevance: retrieval is the slow part."""
    from legal_agent.evaluation.judgment_coverage import run_judgment_coverage

    sessions = json.loads(
        (ROOT / "evals" / "real_sessions.json").read_text(encoding="utf-8"))[:10]
    slice_path = tmp_path / "slice.json"
    slice_path.write_text(json.dumps(sessions, ensure_ascii=False), encoding="utf-8")

    report = run_judgment_coverage(slice_path)
    assert report.sessions == len(sessions)
    assert sum(r.sessions for r in report.triage.values()) == len(sessions)
    for row in [*report.families.values(), *report.triage.values()]:
        assert row.same_kind <= row.with_judgment <= row.sessions
    assert "達標" in report.render()


def test_families_no_case_type_can_name_are_reported_not_filled():
    """僱傭關係 is read as 勞動 and consumer cases are filed as 買賣/價金, so these
    two families stay at 0 whatever the corpus holds."""
    assert not nameable("僱傭") and not nameable("消費")
    assert nameable("使用借貸") and nameable("租賃")


def test_the_published_stock_column_matches_the_corpus(shipped_conn):
    """RESULTS §10's 庫存同類/待補 columns are recomputed here, as the mutation
    table is in test_published_numbers: a backfill that ships must move them."""
    import re

    text = (ROOT / "evals" / "RESULTS.md").read_text(encoding="utf-8")
    section = text[text.index("## §10"):text.index("## More")]
    rows = re.findall(r"^\| (\S+) \| \d+ \| \d+ \| \d+ \| (\d+) \| (\d+) \|$",
                      section, flags=re.M)
    assert len(rows) >= 20
    stock = stock_by_family(shipped_conn)
    for family, published_stock, published_missing in rows:
        live = len(stock.get(family, []))
        assert (int(published_stock), int(published_missing)) == (
            live, max(0, TARGET - live)), family
