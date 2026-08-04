"""Offline tests for the 裁判書API harvester's pure parts: the JDoc adapter,
the substantive-civil filter, and the .env reader. No network.

Run:  python -m pytest tests/test_judicial_api.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.judicial_api import (  # noqa: E402
    _load_env,
    is_substantive_civil,
    jdoc_to_record,
)
from legal_agent.data.judicial_json import parse_judgment  # noqa: E402


def test_jdoc_to_record_flattens_nested_fulltext():
    jdoc = {
        "JID": "ILDV,115,重訴,7,20260707,1",
        "JYEAR": "115",
        "JCASE": "重訴",
        "JNO": "7",
        "JDATE": "20260707",
        "JTITLE": "塗銷所有權移轉登記等",
        "JFULLX": {"JFULLTYPE": "file", "JFULLCONTENT": "臺灣宜蘭地方法院民事判決…依民法第184條…", "JFULLPDF": "http://x"},
    }
    record = jdoc_to_record(jdoc)
    assert record["JID"] == "ILDV,115,重訴,7,20260707,1"
    assert record["JFULL"].startswith("臺灣宜蘭地方法院")

    # the record feeds straight into the existing importer
    row, warnings = parse_judgment(record, known_ids={"民法"})
    assert warnings == []
    assert row["jid"] == "ILDV,115,重訴,7,20260707,1"
    assert row["court"] == "ILDV"
    assert row["year"] == 115
    assert row["case_type"] == "塗銷所有權移轉登記等"
    assert '"民法"' in row["cited_articles"] and "第184條" in row["cited_articles"]


def test_jdoc_to_record_survives_missing_fullx():
    row = jdoc_to_record({"JID": "X,1,訴,1,20260101,1", "JYEAR": "1", "JTITLE": "t"})
    assert row["JFULL"] == ""


def test_substantive_civil_filter():
    assert is_substantive_civil("ILDV,115,重訴,7,20260707,1")       # 民事實質
    assert is_substantive_civil("ILEV,114,宜簡,406,20260617,2")     # 簡易判決
    assert not is_substantive_civil("ILDV,115,司促,2524,20260611,1")  # 司-prefixed
    assert not is_substantive_civil("ILDV,115,促,12,20260611,1")      # bare order
    assert not is_substantive_civil("CHDM,100,訴,1552,20130517,2")    # 刑事 M
    assert not is_substantive_civil("badjid")                         # malformed


@pytest.fixture
def conn(tmp_path):
    from legal_agent.data.database import connect, init_db

    db = tmp_path / "h.db"
    init_db(db)
    c = connect(db)
    yield c
    c.close()


def _row(jid="AAA,114,訴,1,20260101,1", case_type="損害賠償", full_text="舊版全文"):
    return {
        "jid": jid, "court": "AAA", "year": 114, "case_type": case_type,
        "issues": None, "cited_articles": "[]", "holding": None,
        "full_text": full_text,
    }


def test_relisted_jid_overwrites_previous_content(conn):
    """Spec 肆一: a re-listed jid means the judgment was AMENDED — the newer
    content must replace the older, not be discarded as a duplicate."""
    from legal_agent.data.judicial_json import load_judgments

    load_judgments([_row()], conn)
    assert load_judgments([_row(case_type="損害賠償(更正)", full_text="更正後全文")],
                          conn, replace=True) == (1, 0)
    row = conn.execute(
        "SELECT case_type, full_text FROM judgments WHERE jid = ?",
        ("AAA,114,訴,1,20260101,1",),
    ).fetchone()
    assert row["case_type"] == "損害賠償(更正)"
    assert row["full_text"] == "更正後全文"
    assert conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0] == 1

    # without replace, the old row stands (cheap-retry semantics)
    assert load_judgments([_row(case_type="又一版")], conn) == (0, 1)


def test_removed_judgment_is_deleted_locally(conn):
    """Spec 肆二: 查無資料 means the court unpublished it — the local copy
    must go, or the removal protects nobody."""
    from legal_agent.data.judicial_json import delete_judgment, load_judgments

    load_judgments([_row()], conn)
    assert delete_judgment("AAA,114,訴,1,20260101,1", conn) is True
    assert conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0] == 0
    assert delete_judgment("NOPE,1,訴,1,20260101,1", conn) is False


def test_load_env_reads_key_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nJUDICIAL_USER=abc\nJUDICIAL_PASSWORD = p w \n", encoding="utf-8")
    values = _load_env(env)
    assert values["JUDICIAL_USER"] == "abc"
    assert values["JUDICIAL_PASSWORD"] == "p w"
    assert _load_env(tmp_path / "missing.env") == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
