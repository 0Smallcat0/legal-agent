"""Seed source_hierarchy with Taiwan's authority levels (spec §1.4).

This MUST run before any statute / 法源 is inserted: statutes.hierarchy_level
carries a foreign key to source_hierarchy(level). The seeder is idempotent — safe
to run repeatedly (existing rows are left untouched).

Convention (spec §1.4): LOWER rank = HIGHER authority.
The description column is an optional one-line gloss (not legal text).
"""
from __future__ import annotations

import sqlite3

# (level, rank, description). rank: lower = more authoritative.
SOURCE_HIERARCHY_LEVELS: list[tuple[str, int, str]] = [
    ("憲法", 1, "國家最高法規範"),
    ("法律", 2, "立法院三讀通過、總統公布(法 / 律 / 條例 / 通則)"),
    ("命令", 3, "行政機關依法律授權訂定(規程 / 規則 / 細則 / 辦法 / 標準 / 準則等)"),
    ("函釋", 4, "行政機關對法令的解釋性函令"),
    ("行政實務見解", 5, "主管機關公開之處理原則/受理分工;效力低於函釋,非法律明文"),
]


def seed_source_hierarchy(conn: sqlite3.Connection) -> int:
    """Insert the authority levels if absent; return the row count afterwards.

    Idempotent via ``ON CONFLICT(level) DO NOTHING`` — re-running never
    duplicates or overwrites. Commits on the given connection.
    """
    conn.executemany(
        "INSERT INTO source_hierarchy(level, rank, description) VALUES (?, ?, ?) "
        "ON CONFLICT(level) DO NOTHING",
        SOURCE_HIERARCHY_LEVELS,
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM source_hierarchy").fetchone()[0]
