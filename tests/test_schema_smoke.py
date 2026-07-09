"""Smoke test for the data-layer schema — the ONE executable check in the
scaffold. It verifies that schema.sql is valid SQLite AND that the critical
design decision actually holds in practice:

  * the three §1.4 tables are created;
  * the same (statute_id, article_no) can hold MULTIPLE time slices, but a
    duplicate slice (same primary key) is rejected — i.e. statutes really are
    time-sliced, not keyed on article number alone;
  * statutes.hierarchy_level is foreign-key-checked against source_hierarchy.

Run:  python -m pytest tests/ -q      (or)      python tests/test_schema_smoke.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402


def test_three_tables_exist(tmp_path):
    db = tmp_path / "smoke.db"
    init_db(db)
    conn = connect(db)
    try:
        names = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"statutes", "judgments", "source_hierarchy"} <= names


def test_statute_is_time_sliced(tmp_path):
    """Two versions of the SAME article coexist; a duplicate time slice fails."""
    db = tmp_path / "smoke.db"
    init_db(db)
    conn = connect(db)
    try:
        conn.execute("INSERT INTO source_hierarchy(level, rank) VALUES ('法律', 2)")
        # Two time slices of 民法第793條 — both must insert.
        conn.execute(
            "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
            "effective_to, hierarchy_level) "
            "VALUES ('民法', '第793條', 'v1', '1929-05-23', '2021-01-20', '法律')"
        )
        conn.execute(
            "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
            "effective_to, hierarchy_level) "
            "VALUES ('民法', '第793條', 'v2', '2021-01-20', NULL, '法律')"
        )
        conn.commit()

        n = conn.execute(
            "SELECT COUNT(*) FROM statutes WHERE statute_id='民法' AND article_no='第793條'"
        ).fetchone()[0]
        assert n == 2, "the same article must be able to hold multiple time slices"

        # A duplicate time slice (identical primary key) must be rejected.
        try:
            conn.execute(
                "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
                "effective_to, hierarchy_level) "
                "VALUES ('民法', '第793條', 'dup', '2021-01-20', NULL, '法律')"
            )
            conn.commit()
            raise AssertionError("duplicate time slice should have failed the primary key")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


def test_hierarchy_fk_enforced(tmp_path):
    """statutes.hierarchy_level must reference a known source_hierarchy level."""
    db = tmp_path / "smoke.db"
    init_db(db)
    conn = connect(db)
    try:
        try:
            conn.execute(
                "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
                "hierarchy_level) "
                "VALUES ('民法', '第1條', 'x', '1929-05-23', '不存在的層級')"
            )
            conn.commit()
            raise AssertionError("unknown hierarchy_level should fail the foreign key")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


if __name__ == "__main__":
    import tempfile

    for check in (test_three_tables_exist, test_statute_is_time_sliced, test_hierarchy_fk_enforced):
        check(Path(tempfile.mkdtemp()))
    print("OK: schema smoke tests passed")
