"""Tests for the statute-entry CLI: seeding, insertion, flag detection, and the
interactive add loop (driven by a scripted input()).

Run:  python -m pytest tests/test_cli.py -q
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent import cli  # noqa: E402
from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.models import Statute  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    connection = connect(db)
    yield connection
    connection.close()


def test_seed_is_idempotent_and_exact(conn):
    first = seed_source_hierarchy(conn)
    second = seed_source_hierarchy(conn)  # re-run must not duplicate
    assert first == 5
    assert second == 5
    ranks = {r["level"]: r["rank"] for r in conn.execute("SELECT level, rank FROM source_hierarchy")}
    assert ranks == {"憲法": 1, "法律": 2, "命令": 3, "函釋": 4, "行政實務見解": 5}


def test_insert_then_duplicate_pk_raises(conn):
    seed_source_hierarchy(conn)
    statute = Statute("民法", "第793條", "（測試,非真實條文）", "2021-01-20", None, "法律", None)
    cli.insert_statute(conn, statute)
    assert conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        cli.insert_statute(conn, statute)  # same (statute_id, article_no, effective_from)


def test_insert_unknown_level_fails_fk(conn):
    seed_source_hierarchy(conn)
    bad = Statute("民法", "第1條", "x", "2021-01-20", None, "不存在的位階", None)
    with pytest.raises(sqlite3.IntegrityError):
        cli.insert_statute(conn, bad)


def test_row_flags_detects_all_problems():
    valid = {"法律"}
    clean = {
        "content": "有內容",
        "effective_from": "2021-01-20",
        "effective_to": None,
        "hierarchy_level": "法律",
    }
    assert cli._row_flags(clean, valid) == []

    dirty = {
        "content": "   ",
        "effective_from": "2021-13-40",   # not a real date
        "effective_to": "2000-01-01",     # valid ISO, but from is invalid here
        "hierarchy_level": "仙級",         # not in seed set
    }
    flags = cli._row_flags(dirty, valid)
    assert "內容為空" in flags
    assert "生效日非合法日期" in flags
    assert "位階不在種子集合" in flags


def test_row_flags_effective_to_before_from():
    valid = {"法律"}
    row = {
        "content": "x",
        "effective_from": "2021-01-20",
        "effective_to": "2020-01-01",
        "hierarchy_level": "法律",
    }
    assert "失效日早於生效日" in cli._row_flags(row, valid)


def _script(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(it))


def test_cmd_add_happy_path(conn, monkeypatch, capsys):
    seed_source_hierarchy(conn)
    _script(
        monkeypatch,
        [
            "民法",                 # statute_id
            "第793條",              # article_no
            "（測試,非真實條文）",   # content line
            "END",                  # end multiline content
            "民國110年01月20日",     # effective_from (ROC -> auto ISO)
            "",                     # effective_to: skip (currently in force)
            "2",                    # pick level -> 法律
            "",                     # source_url: skip
            "y",                    # confirm write
            "n",                    # add another? no
        ],
    )
    cli.cmd_add(conn)
    row = conn.execute("SELECT * FROM statutes").fetchone()
    assert row is not None
    assert row["statute_id"] == "民法"
    assert row["article_no"] == "第793條"
    assert row["effective_from"] == "2021-01-20"   # auto-converted
    assert row["effective_to"] is None
    assert row["hierarchy_level"] == "法律"


def test_cmd_add_decline_discards(conn, monkeypatch, capsys):
    seed_source_hierarchy(conn)
    _script(
        monkeypatch,
        [
            "民法", "第800條", "內容", "END",
            "1100120",   # effective_from
            "",          # effective_to skip
            "2",         # level 法律
            "",          # url skip
            "n",         # confirm? NO -> discard
            "n",         # add another? no
        ],
    )
    cli.cmd_add(conn)
    assert conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
