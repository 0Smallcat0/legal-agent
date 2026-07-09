"""Tests for the Layer-2 法源 ingest infra: the 5th source_hierarchy level and
the proposal loader. Deterministic, no network.

Run:  python -m pytest tests/test_source_ingest.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.data.source_ingest import load_proposals  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "proposals_fixture.json"


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    connection = connect(db)
    seed_source_hierarchy(connection)
    yield connection
    connection.close()


# ── Part 1: the 5th authority level ──────────────────────────────────────────
def test_source_hierarchy_has_five_ordered_levels(conn):
    rows = conn.execute("SELECT level, rank FROM source_hierarchy ORDER BY rank").fetchall()
    assert [(r["level"], r["rank"]) for r in rows] == [
        ("憲法", 1), ("法律", 2), ("命令", 3), ("函釋", 4), ("行政實務見解", 5),
    ]


def test_seed_still_idempotent_with_five_levels(conn):
    assert seed_source_hierarchy(conn) == 5   # re-run adds nothing


# ── Part 2: the proposal loader ──────────────────────────────────────────────
def test_load_proposals_ingests_and_is_idempotent(conn):
    inserted, skipped = load_proposals(FIXTURE, conn)
    assert (inserted, skipped) == (2, 0)

    # persisted into the statutes (法源) table, distinguished by hierarchy_level
    levels = {r["hierarchy_level"] for r in conn.execute("SELECT hierarchy_level FROM statutes")}
    assert {"命令", "行政實務見解"} <= levels

    # a 文號-as-id row keeps an empty article_no (NOT NULL, but "" is allowed)
    row = conn.execute("SELECT * FROM statutes WHERE hierarchy_level = '行政實務見解'").fetchone()
    assert row["article_no"] == ""

    # idempotent re-run: same rows are skipped, nothing duplicated
    inserted2, skipped2 = load_proposals(FIXTURE, conn)
    assert (inserted2, skipped2) == (0, 2)
    assert conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0] == 2


def test_unknown_hierarchy_level_is_rejected(conn, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps([{
            "statute_id": "測試",
            "article_no": "第1條",
            "content": "x",
            "effective_from": "2020-01-01",
            "effective_to": None,
            "hierarchy_level": "不存在的位階",
            "source_url": None,
        }]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_proposals(bad, conn)
    # fail-fast: nothing was inserted
    assert conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0] == 0


def test_source_ingest_main_loads_and_is_idempotent(tmp_path, monkeypatch, capsys):
    from legal_agent import config
    from legal_agent.data import source_ingest

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ingest.db")
    assert source_ingest.main([str(FIXTURE)]) == 0
    assert "inserted 2 / skipped 0" in capsys.readouterr().out
    source_ingest.main([str(FIXTURE)])                          # idempotent re-run
    assert "inserted 0 / skipped 2" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
