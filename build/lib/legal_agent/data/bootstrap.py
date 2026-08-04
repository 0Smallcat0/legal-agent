"""One call that makes a fresh clone runnable: schema + corpus, idempotent.

This lived inside `app.py`, so the terminal entry point and the README needed
four separate commands to reach the state the web demo reached by itself. Cheap
to call from anywhere: when the corpus is already loaded it returns immediately
without touching the proposal files.
"""
from __future__ import annotations

import sqlite3

from legal_agent import config
from legal_agent.data.database import connect, init_db
from legal_agent.data.judgment_ingest import load_judgments
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals

# Source of truth for the shipped corpus. The old hand-typed noise seed is
# superseded by the official-XML proposal — loading both would create duplicate
# current slices for the same article.
PROPOSALS = ("moj_bulk_v1_proposal.json", "noise_routing_proposal.json")

# Reference judgments, redacted to the two slices a page renders (see
# data/judgment_ingest.py). Shipped because the harvester cannot practically
# rebuild them: the 司法院 API serves 00:00-06:00 and returns one day at a time.
JUDGMENTS = "judgments_v1.json"


def corpus_size(conn: sqlite3.Connection) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]
    except sqlite3.OperationalError:      # table not created yet
        return 0


def ensure_corpus(db_path=None) -> int:
    """Build the schema and load the corpus if it is not there yet.

    Returns the article count. Idempotent and fast on an already-loaded DB.
    """
    path = db_path or config.DB_PATH
    init_db(path)
    conn = connect(path)
    try:
        seed_source_hierarchy(conn)
        if not corpus_size(conn):
            for name in PROPOSALS:
                proposal = config.CORPUS_DIR / name
                if proposal.exists():
                    load_proposals(proposal, conn)
        # Checked separately, not behind the statute early-return: a DB built
        # before judgments shipped has a full corpus and an empty judgments
        # table, and would otherwise never pick them up.
        _ensure_judgments(conn)
        return corpus_size(conn)
    finally:
        conn.close()


def judgment_count(conn: sqlite3.Connection) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
    except sqlite3.OperationalError:      # table not created yet
        return 0


def _ensure_judgments(conn: sqlite3.Connection) -> int:
    """Load the shipped reference judgments once. Returns the row count.

    Harvested judgments (from `data/judicial_api.py`) live in the same table, so
    a populated table is left alone: the shipped file is a floor, never an
    overwrite.
    """
    existing = judgment_count(conn)
    if existing:
        return existing
    shipped = config.CORPUS_DIR / JUDGMENTS
    if shipped.exists():
        load_judgments(shipped, conn)
    return judgment_count(conn)
