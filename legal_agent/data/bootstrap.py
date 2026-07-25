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
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals

# Source of truth for the shipped corpus. The old hand-typed noise seed is
# superseded by the official-XML proposal — loading both would create duplicate
# current slices for the same article.
PROPOSALS = ("moj_bulk_v1_proposal.json", "noise_routing_proposal.json")


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
        size = corpus_size(conn)
        if size:
            return size
        for name in PROPOSALS:
            proposal = config.CORPUS_DIR / name
            if proposal.exists():
                load_proposals(proposal, conn)
        return corpus_size(conn)
    finally:
        conn.close()
