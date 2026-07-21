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

from legal_agent import config
from legal_agent.config import DB_PATH
from legal_agent.data.database import connect
from legal_agent.data.models import Statute

jieba.setLogLevel(logging.WARNING)  # silence the one-time dict-build chatter

# MEASURED against golden v2 on the 2 561-article corpus (query expansion on):
# k=5 -> 92% pass+partial, k=8 -> 96%, k=12 -> no further gain. Everyday
# problems legitimately span several statutes (社維 + 公寓大廈 + 民法侵權), so
# a 5-slot window truncates correct answers. Honesty tier is unaffected (it
# reads the TOP score, not the window size).
DEFAULT_K = 8

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
    """jieba word tokens (punctuation dropped) + CJK character bigrams.

    Single-character CJK word tokens are dropped: function words (的/與/及/之…)
    otherwise create spurious lexical overlap with almost every article — the
    golden set's out-of-scope cases caught exactly this. Content signal from
    single characters is still carried by the bigrams.
    """
    words = [
        tok for tok in jieba.lcut(text)
        if _MEANINGFUL.search(tok) and not (len(tok) == 1 and _CJK_RUN.fullmatch(tok))
    ]
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
    dense_query: str | None = None,
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

    # The USER'S OWN WORDS decide match / no-match; expansion only helps RANK.
    # Letting expanded statutory terms into the inclusion set would manufacture
    # matches out of shared boilerplate — measured: 「同一順序之繼承人」 (added
    # for an inheritance question) collided with 民法§195's 「不得讓與或繼承」
    # and turned an out-of-scope question into a confident answer.
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

    scores = BM25Okapi(doc_tokens).get_scores(_tokenize(_expand(query)))
    matches.sort(key=lambda i: scores[i], reverse=True)
    ranked = [(candidates[i], float(scores[i])) for i in matches]

    fused = _dense_fuse(_expand(dense_query or query), candidates, ranked, k=k)
    return (fused if fused is not None else ranked)[:k]


def _expand(text: str) -> str:
    """Bridge the everyday/statutory vocabulary gap (config.QUERY_EXPANSION).
    Additive only — the user's wording stays verbatim at the front — so a
    query that already matched cannot lose its matches."""
    if getattr(config, "QUERY_EXPANSION", "off") != "on":
        return text
    from legal_agent.retrieval.lexicon import expand
    return expand(text)


# Dense reserved seats: RRF's dual-presence bonus systematically buries a
# dense-only item — measured on golden v2, 民法§184 at dense rank 2 (and
# 噪管§6 at 4, §793 at 5, §1141 at 3) still missed the top-8 because dozens of
# lexically-matched articles each collect BOTH reciprocal ranks. The dense
# channel's top few therefore get guaranteed seats at the TAIL of the top-k
# window. BM25 scores stay untouched (promoted dense-only items carry 0.0, so
# the honesty floor — the TOP score — cannot move).
# N swept on the stub-LLM golden harness (pass/partial/miss of 26 scorable):
#   N=0 16/9/1 · N=2 17/8/1 · N=3 18/7/1 · N=4 17/7/2 · N=5 17/8/1
# N=3 wins; at N>=4 the displaced fused tail costs mg-02 its expected §16.
DENSE_RESERVED_SEATS = 3


def _dense_fuse(
    query: str,
    candidates: list[Statute],
    bm25_ranked: list[tuple[Statute, float]],
    k: int | None = None,
) -> list[tuple[Statute, float]] | None:
    """Hybrid re-ranking (config.DENSE_RETRIEVAL="auto"): RRF-fuse the BM25
    ranking with the cached bge-m3 dense ranking (retrieval/dense.py), then
    guarantee the dense top-DENSE_RESERVED_SEATS survive into the top-k window.

    Contract: BM25 scores are UNTOUCHED — the honesty floor keeps its meaning;
    a dense-only candidate (the vocabulary-gap case) carries its honest lexical
    score of 0.0. Returns None — pure BM25, behaviour unchanged — when the
    feature is off, the index is unbuilt, or Ollama is unreachable."""
    if getattr(config, "DENSE_RETRIEVAL", "off") == "off":
        return None
    try:
        from legal_agent.retrieval import dense
        index_keys, matrix = dense.load_index()
        dense_keys = dense.dense_rank(query, index_keys, matrix)
    except Exception:
        return None

    def key_of(s: Statute) -> tuple[str, str, str]:
        return (s.statute_id, s.article_no, s.effective_from)

    bm25_by_key = {key_of(s): (s, sc) for s, sc in bm25_ranked}
    candidate_by_key = {key_of(c): c for c in candidates}
    fused_keys = dense.rrf_fuse([list(bm25_by_key), dense_keys[:50]])

    out: list[tuple[Statute, float]] = []
    for fkey in fused_keys:
        if fkey in bm25_by_key:
            out.append(bm25_by_key[fkey])
        elif fkey in candidate_by_key:          # dense-only: lexically unmatched
            out.append((candidate_by_key[fkey], 0.0))

    if k is None or k <= 0:
        return out

    # Reserved seats: promote dense top-N missing from the window to its tail
    # (dense order preserved; the window's weakest fused tail is displaced).
    window_keys = {key_of(s) for s, _ in out[:k]}
    promote: list[tuple[Statute, float]] = []
    for dkey in dense_keys[:DENSE_RESERVED_SEATS]:
        if dkey in window_keys:
            continue
        if dkey in bm25_by_key:
            promote.append(bm25_by_key[dkey])
        elif dkey in candidate_by_key:          # point-in-time filter still rules
            promote.append((candidate_by_key[dkey], 0.0))
    if not promote:
        return out
    promoted_keys = {key_of(s) for s, _ in promote}
    keep = [e for e in out[:k] if key_of(e[0]) not in promoted_keys][: max(k - len(promote), 0)]
    kept_keys = {key_of(e[0]) for e in keep}
    tail = [e for e in out
            if key_of(e[0]) not in kept_keys and key_of(e[0]) not in promoted_keys]
    return keep + promote + tail


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
    dense_query: str | None = None,
) -> list[tuple[Statute, float]]:
    """Same as retrieve() but returns (Statute, BM25 score) pairs, ranked. The
    score is the relevance signal for Stage 3's Mechanism-3 honesty tier.

    dense_query: optional FOCUSED text for the dense half of the hybrid (the
    semantic core — problem/goal), while `query` (the full fact set) still
    drives BM25's exact-term matching. Measured: the overtime target 勞基§24
    ranks 34 on the full fact string but 5 on problem+goal alone — process
    facts (「持續一年」「問過人資被拒」) are semantic noise. None = use `query`."""
    return _retrieve_scored(query, as_of_date, k, conn, dense_query=dense_query)
