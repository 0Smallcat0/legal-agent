"""`judgment_backfill` — takes only official records, only for short families.

The records below are test inputs with obviously fake JIDs (court 「TSTV」);
they exercise the selection, never reach the shipped corpus, and the shipped
file is checked separately to carry none of them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from legal_agent.data.judgment_backfill import (
    _api_candidate,
    backfill,
    deficits,
    records_from_paths,
)

ROOT = Path(__file__).resolve().parents[1]


def _record(jid, title, body):
    return {"JID": jid, "JYEAR": "114", "JTITLE": title,
            "JFULL": f"臺灣測試地方法院民事判決\n主　　文\n原告之訴駁回。\n理由\n{body}"}


LOAN_NEW = _record("TSTV,114,訴,2,20250302,1", "返還借用物", "依民法第470條規定")
LOAN_OLD = _record("TSTV,113,訴,1,20240101,1", "返還借用物", "依民法第470條規定")
LOAN_NO_ARTICLE = _record("TSTV,114,訴,3,20250401,1", "返還借用物", "依民法第184條規定")
GENERIC = _record("TSTV,114,訴,4,20250501,1", "損害賠償", "依民法第470條規定")


@pytest.fixture(scope="module")
def statutes_db(tmp_path_factory):
    """Statutes only, built once: the selection reads their ids, nothing else."""
    from legal_agent.data.database import connect, init_db
    from legal_agent.data.seed import seed_source_hierarchy
    from legal_agent.data.source_ingest import load_proposals

    db = tmp_path_factory.mktemp("backfill") / "statutes.db"
    init_db(db)
    c = connect(db)
    seed_source_hierarchy(c)
    load_proposals(ROOT / "legal_agent" / "corpus" / "moj_bulk_v1_proposal.json", c)
    c.close()
    return db


@pytest.fixture
def conn(tmp_path, statutes_db):
    import shutil

    from legal_agent.data.database import connect

    db = tmp_path / "b.db"
    shutil.copy(statutes_db, db)
    c = connect(db)
    yield c
    c.close()


def _jids(conn):
    return {r[0] for r in conn.execute("SELECT jid FROM judgments")}


def test_takes_newest_first_up_to_the_shortfall(conn):
    result = backfill(conn, [LOAN_OLD, LOAN_NEW], {"使用借貸": 1})
    assert [r["jid"] for r in result.chosen["使用借貸"]] == [LOAN_NEW["JID"]]
    assert _jids(conn) == {LOAN_NEW["JID"]}
    assert result.still_missing() == {}


def test_only_records_that_can_reach_a_page_are_taken(conn):
    """案由 names the family but no article of it is cited: the JOIN could
    never surface it, so it does not fill the gap. A generic 案由 neither."""
    result = backfill(conn, [LOAN_NO_ARTICLE, GENERIC], {"使用借貸": 3})
    assert result.chosen == {}
    assert result.still_missing() == {"使用借貸": 3}
    assert _jids(conn) == set()


def test_families_already_at_target_take_nothing(conn):
    result = backfill(conn, [LOAN_NEW], {"寄託": 2})
    assert result.chosen == {} and _jids(conn) == set()


def test_dry_run_writes_nothing(conn):
    result = backfill(conn, [LOAN_NEW], {"使用借貸": 3}, dry_run=True)
    assert len(result.chosen["使用借貸"]) == 1
    assert result.inserted == 0 and _jids(conn) == set()


def test_a_jid_already_stored_is_not_taken_again(conn):
    backfill(conn, [LOAN_NEW], {"使用借貸": 3})
    again = backfill(conn, [LOAN_NEW], {"使用借貸": 3})
    assert again.chosen == {}


def test_reads_bulk_files_lists_and_jdoc_responses(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.json").write_text(json.dumps(LOAN_NEW, ensure_ascii=False),
                                             encoding="utf-8-sig")
    (tmp_path / "list.json").write_text(json.dumps([LOAN_OLD], ensure_ascii=False),
                                        encoding="utf-8")
    jdoc = {"JID": GENERIC["JID"], "JYEAR": "114", "JTITLE": "損害賠償",
            "JFULLX": {"JFULLTYPE": "text", "JFULLCONTENT": GENERIC["JFULL"]}}
    (tmp_path / "jdoc.json").write_text(json.dumps(jdoc, ensure_ascii=False),
                                        encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    got = {r["JID"]: r for r in records_from_paths([tmp_path])}
    assert set(got) == {LOAN_NEW["JID"], LOAN_OLD["JID"], GENERIC["JID"]}
    assert got[GENERIC["JID"]]["JFULL"] == GENERIC["JFULL"]


def test_deficits_on_the_shipped_corpus_match_the_harness(shipped_conn):
    from legal_agent.evaluation.judgment_coverage import TARGET, stock_by_family

    wanted = deficits(shipped_conn, ROOT / "evals" / "real_sessions.json")
    stock = stock_by_family(shipped_conn)
    assert wanted, "the shipped corpus has short families (RESULTS §10)"
    for family, short in wanted.items():
        assert short == TARGET - len(stock.get(family, []))


def test_api_candidates_add_public_order_rulings_to_civil():
    assert _api_candidate("TSTV,114,訴,1,20250101,1")
    assert _api_candidate("TSTM,114,北秩,1,20250101,1")      # 社維法 ruling
    assert not _api_candidate("TSTM,114,訴,1,20250101,1")    # other criminal
    assert not _api_candidate("TSTV,114,司促,1,20250101,1")


def test_no_test_record_reached_the_shipped_corpus():
    shipped = json.loads((ROOT / "legal_agent" / "corpus" / "judgments_v1.json")
                         .read_text(encoding="utf-8"))
    assert not any(r["jid"].startswith("TST") for r in shipped)
