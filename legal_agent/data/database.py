"""SQLite connection, schema, and the single write path into `statutes`.

Responsibility: open connections to the local SQLite database, create the three
tables defined in schema.sql (spec §1.4), and own the one INSERT that every
ingest route goes through. It does NOT fetch or generate legal data — deciding
WHAT to persist belongs to the ingest modules; this one only persists it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from legal_agent.data.models import Statute

# schema.sql lives next to this module.
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with the defaults this project relies on.

    - ``PRAGMA foreign_keys = ON`` so the statutes -> source_hierarchy integrity
      check is actually enforced (SQLite leaves it OFF by default).
    - ``row_factory = sqlite3.Row`` so callers read columns by name.
    """
    # The default DB now lives in a per-user data directory that does not exist
    # on a fresh install, and sqlite3 does not create it — it raises
    # 「unable to open database file」, which reads like a permission problem.
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path) -> None:
    """Create the schema by executing schema.sql. Idempotent.

    Safe to run repeatedly — schema.sql uses ``CREATE TABLE IF NOT EXISTS``.
    Creates no rows; data/seed.py seeds source_hierarchy.
    """
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


def insert_statute(conn: sqlite3.Connection, statute: Statute) -> None:
    """Insert one statute time-slice. Raises sqlite3.IntegrityError on a
    duplicate (statute_id, article_no, effective_from) or an unknown level."""
    conn.execute(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            statute.statute_id,
            statute.article_no,
            statute.content,
            statute.effective_from,
            statute.effective_to,
            statute.hierarchy_level,
            statute.source_url,
        ),
    )
    conn.commit()
