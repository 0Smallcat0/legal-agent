"""Retrieval — pull relevant statutes FROM the corpus (spec §2.2, Mechanism 1).

"Retrieval-first, no bare answers": this is the ONLY source later layers (the
citation verifier, the reasoning model) may cite. It reads verbatim rows from the
`statutes` table, ranks them lexically, and returns the top matches with content +
source_url intact for traceability. It never fabricates and never falls back to
un-retrieved text.

Method (pure, local — no LLM, no network, no embeddings, no GPU):
  1. POINT-IN-TIME filter (mandatory, BEFORE ranking): candidates = the slice in
     force at `as_of_date` (canonical predicate in data/schema.sql). A superseded
     version is never a candidate.
  2. Tokenize each candidate's `content` with jieba (word tokens + CJK character
     bigrams, robust to jieba's Traditional-Chinese mis-segmentation), build a
     BM25 index over just those candidates, tokenize the query the same way.
  3. Return the top-K verbatim Statute records that share at least one token with
     the query — LEXICAL OVERLAP decides match/no-match, BM25 only ORDERS them;
     [] if nothing overlaps.

`retrieve()` returns the Statutes; `retrieve_scored()` returns (Statute, BM25
score) pairs (same order) — the score is the relevance signal Stage 3's
Mechanism-3 honesty tier grades against.

Fires exactly ONCE per conversation, on the complete fact set (spec §3.3).
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import date

import jieba
from rank_bm25 import BM25Okapi

from legal_agent.config import DB_PATH
from legal_agent.data.database import connect
from legal_agent.data.models import Statute

jieba.setLogLevel(logging.WARNING)  # silence the one-time dict-build chatter

DEFAULT_K = 5

_COLUMNS = "statute_id, article_no, content, effective_from, effective_to, hierarchy_level, source_url"
_MEANINGFUL = re.compile(r"[0-9A-Za-z一-鿿]")
_CJK_RUN = re.compile(r"[一-鿿]+")


def _cjk_bigrams(text: str) -> list[str]:
    """Adjacent CJK character bigrams within each run (bounded by punctuation).

    Traditional-Chinese robustness: jieba's Simplified-oriented dict mis-segments
    some Traditional strings (e.g. '飼養貓咪' -> '飼養貓','咪' while '貓咪' alone
    stays '貓咪'); bigrams match regardless of how jieba split the words.
    """
    bigrams: list[str] = []
    for run in _CJK_RUN.findall(text):
        bigrams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return bigrams


def _tokenize(text: str) -> list[str]:
    """jieba word tokens (punctuation dropped) + CJK character bigrams."""
    words = [tok for tok in jieba.lcut(text) if _MEANINGFUL.search(tok)]
    return words + _cjk_bigrams(text)


def _row_to_statute(row: sqlite3.Row) -> Statute:
    return Statute(
        statute_id=row["statute_id"],
        article_no=row["article_no"],
        content=row["content"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        hierarchy_level=row["hierarchy_level"],
        source_url=row["source_url"],
    )


def _load_in_force(conn: sqlite3.Connection, as_of_date: str | None) -> list[Statute]:
    """Candidate set = the statute slices in force at `as_of_date`.

    Mirrors the canonical time-slice predicate in data/schema.sql:
        effective_from <= :as_of AND (effective_to IS NULL OR :as_of < effective_to)
    With no date, "in force" means the current slice (effective_to IS NULL).
    """
    if as_of_date is None:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM statutes WHERE effective_to IS NULL"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM statutes "
            "WHERE effective_from <= :as_of "
            "AND (effective_to IS NULL OR :as_of < effective_to)",
            {"as_of": as_of_date},
        ).fetchall()
    return [_row_to_statute(r) for r in rows]


def _retrieve_scored(
    query: str,
    as_of_date: str | None,
    k: int,
    conn: sqlite3.Connection | None,
) -> list[tuple[Statute, float]]:
    """Shared core for retrieve() and retrieve_scored(): point-in-time filter ->
    BM25 -> lexical-overlap inclusion -> BM25 ordering -> top-k (Statute, score)."""
    if as_of_date is not None:
        try:
            date.fromisoformat(as_of_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"as_of_date must be ISO 'YYYY-MM-DD', got {as_of_date!r}"
            ) from exc
    if k <= 0:
        return []

    own_conn = connect(DB_PATH) if conn is None else None
    active = conn if own_conn is None else own_conn
    try:
        candidates = _load_in_force(active, as_of_date)
    finally:
        if own_conn is not None:
            own_conn.close()

    if not candidates:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
    query_vocab = set(query_tokens)

    doc_tokens = [_tokenize(c.content) for c in candidates]
    # Match / no-match is decided by LEXICAL OVERLAP, not the BM25 score sign (on a
    # tiny corpus BM25 IDF can be 0/negative and wrongly drop a real match). BM25
    # only ORDERS the qualifying matches.
    matches = [i for i, toks in enumerate(doc_tokens) if query_vocab.intersection(toks)]
    if not matches:
        return []

    scores = BM25Okapi(doc_tokens).get_scores(query_tokens)
    matches.sort(key=lambda i: scores[i], reverse=True)
    return [(candidates[i], float(scores[i])) for i in matches][:k]


def retrieve(
    query: str,
    as_of_date: str | None = None,
    k: int = DEFAULT_K,
    conn: sqlite3.Connection | None = None,
) -> list[Statute]:
    """Return up to `k` verbatim Statute records most relevant to `query`.

    Args:
        query: free-text query (the structured fact set, at dialogue Stage 3).
        as_of_date: ISO 'YYYY-MM-DD'. Selects the version in force at that date;
            None means the currently-in-force slice. Raises ValueError if given
            but not a valid ISO date.
        k: max results (default 5).
        conn: optional open connection (tests point this at a fixture DB);
            defaults to the real corpus at config.DB_PATH.

    Returns:
        Statute records that lexically overlap the query (share >=1 token),
        ordered by BM25 score, or [] if the point-in-time candidate set is empty
        or nothing overlaps.
    """
    return [statute for statute, _score in _retrieve_scored(query, as_of_date, k, conn)]


def retrieve_scored(
    query: str,
    as_of_date: str | None = None,
    k: int = DEFAULT_K,
    conn: sqlite3.Connection | None = None,
) -> list[tuple[Statute, float]]:
    """Same as retrieve() but returns (Statute, BM25 score) pairs, ranked. The
    score is the relevance signal for Stage 3's Mechanism-3 honesty tier."""
    return _retrieve_scored(query, as_of_date, k, conn)
