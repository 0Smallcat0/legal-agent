"""Tests for the 司法院裁判書 importer — open-data JSON → judgments rows,
with cited_articles extracted by the verifier's own citation grammar.
Deterministic, no network; fixture is synthetic 測試-marked text.

Run:  python -m pytest tests/test_judicial_json.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.judicial_json import (  # noqa: E402
    load_judgments,
    parse_file,
)

FIXTURE = ROOT / "tests" / "fixtures" / "judicial_sample.json"
KNOWN = {"民法", "社會秩序維護法", "噪音管制法"}


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "j.db"
    init_db(db)
    connection = connect(db)
    yield connection
    connection.close()


def test_parse_maps_api_fields_to_schema():
    rows, warnings = parse_file(FIXTURE, KNOWN)
    assert len(rows) == 2                      # the JID-less record is dropped
    first = rows[0]
    assert first["jid"] == "TPEV,113,測簡,1,20240315,1"
    assert first["court"] == "TPEV"            # first comma-segment of the JID
    assert first["year"] == 113                # ROC year as integer
    assert first["case_type"] == "損害賠償(測試)"
    # honesty split: the NLP-task fields are NULL, never faked
    assert first["issues"] is None and first["holding"] is None
    assert any("缺 JID" in w for w in warnings)


def test_cited_articles_use_verifier_grammar_incl_suffix_normalization():
    rows, _ = parse_file(FIXTURE, KNOWN)
    cited = json.loads(rows[0]["cited_articles"])
    assert {"statute_id": "民法", "article_no": "第793條"} in cited
    assert {"statute_id": "社會秩序維護法", "article_no": "第72條"} in cited
    # 「第9條之1」 normalized to the corpus form — same rule as the verifier
    assert {"statute_id": "噪音管制法", "article_no": "第9-1條"} in cited
    assert len(cited) == 3                     # 民法793 cited twice → deduped
    # a judgment with no citations gets an empty JSON array, not NULL
    assert json.loads(rows[1]["cited_articles"]) == []


def test_load_is_idempotent_and_queryable_via_json1(conn):
    rows, _ = parse_file(FIXTURE, KNOWN)
    assert load_judgments(rows, conn) == (2, 0)
    assert load_judgments(rows, conn) == (0, 2)   # duplicate jid → skipped

    # the schema's documented JSON1 query shape actually works on the data
    hits = conn.execute(
        "SELECT j.jid FROM judgments j, json_each(j.cited_articles) c "
        "WHERE json_extract(c.value, '$.statute_id') = ? "
        "AND json_extract(c.value, '$.article_no') = ?",
        ("民法", "第793條"),
    ).fetchall()
    assert [h[0] for h in hits] == ["TPEV,113,測簡,1,20240315,1"]
