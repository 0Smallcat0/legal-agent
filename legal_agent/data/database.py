"""SQLite connection + schema initialization for the data layer.

Responsibility: open connections to the local SQLite database and create the
three tables defined in schema.sql (spec §1.4). This is the ONLY 'real' code in
the data layer — it wires up the schema so the file can be validated and, later,
populated. It does NOT import, fetch, or generate any legal data; that is a
separate, later build step (spec §5, steps after this one).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# schema.sql lives next to this module.
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with the defaults this project relies on.

    - ``PRAGMA foreign_keys = ON`` so the statutes -> source_hierarchy integrity
      check is actually enforced (SQLite leaves it OFF by default).
    - ``row_factory = sqlite3.Row`` so callers read columns by name.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | Path) -> None:
    """Create the schema by executing schema.sql. Idempotent.

    Safe to run repeatedly — schema.sql uses ``CREATE TABLE IF NOT EXISTS``.
    Creates NO rows: seeding source_hierarchy with the four authority levels
    (spec §1.4) is the first task of the data-population step, not this one.
    """
    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


# Shipped since step 1 (kept here as the layer's map):
#   - seed_source_hierarchy() lives in data/seed.py (5 levels incl. 行政實務見解).
#   - point-in-time slice queries live in retrieval/retriever.py (_load_in_force).
#   - the statute importer lives in data/moj_xml.py (official bulk XML ->
#     human-reviewed proposal JSON -> data/source_ingest.py).
# TODO (still open):
#   - the judgment importer (opendata.judicial.gov.tw JSON -> rows).
