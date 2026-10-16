"""Retrieval — pull relevant statutes FROM the corpus (spec §2.2, Mechanism 1).

The ONLY source later layers (verifier, reasoning model) may cite: verbatim
`statutes` rows with content + source_url intact. Never fabricates.

Method (local, no LLM, no GPU):
  1. POINT-IN-TIME filter BEFORE ranking: candidates = the slice in force at
     `as_of_date` (canonical predicate in data/schema.sql). A superseded
     version is never a candidate.
  2. Topic filters drop candidates the question plainly rules out.
  3. Tokenize with jieba + CJK bigrams; BM25 over just those candidates.
     LEXICAL OVERLAP with the user's own words decides match/no-match; BM25
     (on the lexicon-expanded query) only ORDERS the matches. [] if none.
  4. Optional dense fusion (bge-m3 via Ollama, RRF; see `_dense_fuse`) and
     lexicon reserved seats reshape the top-k window. Promoted items carry
     BM25 score 0.0, so the top score still comes from a real lexical match.

`retrieve_scored()` returns (Statute, BM25 score) pairs — the score is what
the Mechanism-3 honesty tier grades. Fires once per conversation (spec §3.3).
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

# Golden v2, 2 561-article corpus: k=5 -> 92% pass+partial, k=8 -> 96%, k=12 no
# further gain; everyday problems span several statutes. The honesty tier reads
# the TOP score, not the window size.
# Bound into retrieve()/retrieve_scored() signatures at definition time:
# reassigning this at runtime is a no-op — edit the source (AGENTS.md trap 4).
DEFAULT_K = 8

_COLUMNS = "statute_id, article_no, content, effective_from, effective_to, hierarchy_level, source_url"
_MEANINGFUL = re.compile(r"[0-9A-Za-z一-鿿]")
_CJK_RUN = re.compile(r"[一-鿿]+")


def _cjk_bigrams(text: str) -> list[str]:
    """Adjacent CJK character bigrams within each run (bounded by punctuation).

    jieba mis-segments some Traditional strings ('飼養貓咪' -> '飼養貓','咪');
    bigrams match regardless of how jieba split the words.
    """
    bigrams: list[str] = []
    for run in _CJK_RUN.findall(text):
        bigrams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return bigrams


def _tokenize(text: str) -> list[str]:
    """jieba word tokens (punctuation dropped) + CJK character bigrams.

    Single-character CJK word tokens are dropped: function words (的/與/之…)
    otherwise overlap almost every article. Bigrams still carry their signal.
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


# 租賃住宅市場發展及管理條例's long leasing-INDUSTRY chapters (營業保證金,
# 服務業 penalties) otherwise take 2-3 of 8 seats in every landlord-tenant case.
_INDUSTRY_SUBJECTS = ("租賃住宅服務業", "包租業", "代管業", "營業保證金", "全國聯合會")
# …unless the person deals with that trade. These must name the RENTAL trade:
# 仲介/業者 would let a 房仲 purchase question pull 條例§24 back, and 二房東 is an
# ordinary sublessor (民法§443/§444), not a licensed 包租業.
_INDUSTRY_IN_QUESTION = ("包租", "代管", "租賃住宅服務業", "租屋網", "租賃業者")


def _drop_industry_regulation(query: str, candidates: list[Statute]) -> list[Statute]:
    """Drop trade-regulation articles when the question is not about the trade."""
    if any(word in query for word in _INDUSTRY_IN_QUESTION):
        return candidates
    return [
        c for c in candidates
        if not any(word in (c.content or "") for word in _INDUSTRY_SUBJECTS)
    ]


# 漏水/修繕 fire tenancy vocabulary whoever asks, handing an OWNER-OCCUPIED flat
# a landlord's repair duty (民法§430/§437/§423): 4 of 8 seats there, 3 of 8 in
# a house-purchase session.
_TENANCY_SUBJECTS = ("承租人", "出租人", "租賃物", "租賃契約", "租賃住宅", "租賃")
# Said only when the asker owns the place (or a bought THING, e.g. a leaking
# air-conditioner under warranty)…
_OWNER_OCCUPIED = ("自有住宅", "自己的房子", "我買的", "我的房子", "我是屋主",
                   "屋主是我", "已經過戶", "交屋",
                   "保固卡", "保固期", "含安裝", "買了一台")
# …and only believed when nothing puts a tenancy in the room (a landlord says
# 房東/租約/房客, a tenant 押金/退租).
_TENANCY_IN_QUESTION = ("房東", "租約", "租屋", "承租", "押金", "退租", "二房東",
                        "包租", "房客", "租金")


def _drop_tenancy_when_owner_occupied(query: str, candidates: list[Statute]) -> list[Statute]:
    """Drop landlord-and-tenant articles when the asker has said they own it."""
    if not any(word in query for word in _OWNER_OCCUPIED):
        return candidates
    if any(word in query for word in _TENANCY_IN_QUESTION):
        return candidates
    # First line only (see _drop_inheritance_while_alive): a whole-text match
    # removed 公寓大廈條例§3/§27, which merely mention tenants. 「租賃」 is a
    # subject word so §421/§450/§462, whose first lines lack 承租人/出租人, go.
    return [
        c for c in candidates
        if not any(
            word in (c.content or "").split("\n", 1)[0] for word in _TENANCY_SUBJECTS
        )
    ]


# A question about a living parent with dementia must not get the estate-
# division chapter (once a window of 8/8 繼承編): a wrong-premise answer.
_INHERITANCE_SUBJECTS = ("被繼承人", "遺產", "應繼分", "繼承人", "繼承權", "遺囑")
# Words that only make sense about someone still living…
_STILL_ALIVE = ("失智", "認不得", "神智不清", "意識不清", "住院", "還在世",
                "植物人", "臥床", "安養院", "療養院")
# …and never believed over an explicit death or inheritance.
_DEATH_IN_QUESTION = ("過世", "往生", "去世", "身故", "死亡", "走了", "遺產",
                      "繼承", "喪事", "告別式", "遺囑")


def _drop_inheritance_while_alive(query: str, candidates: list[Statute]) -> list[Statute]:
    """Drop the succession chapter when the person concerned is plainly alive."""
    if not any(word in query for word in _STILL_ALIVE):
        return candidates
    if any(word in query for word in _DEATH_IN_QUESTION):
        return candidates
    # FIRST line only — the sentence that sets the subject. A real succession
    # article names it there (§1138); 民法§15-2 merely lists 拋棄繼承權 among
    # acts needing consent, and a whole-text match removed it from the pool.
    return [
        c for c in candidates
        if not any(
            word in (c.content or "").split("\n", 1)[0] for word in _INHERITANCE_SUBJECTS
        )
    ]


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

    candidates = _drop_industry_regulation(query, candidates)
    candidates = _drop_tenancy_when_owner_occupied(query, candidates)
    candidates = _drop_inheritance_while_alive(query, candidates)
    if not candidates:
        return []

    # The USER'S OWN WORDS decide match / no-match; expansion only helps RANK.
    # Expanded terms in the inclusion set match shared boilerplate and turn
    # out-of-scope questions into confident answers.
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []
    query_vocab = set(query_tokens)

    doc_tokens = [_tokenize(c.content) for c in candidates]
    # Overlap, not BM25 score sign: IDF can be 0/negative on a tiny corpus.
    matches = [i for i, toks in enumerate(doc_tokens) if query_vocab.intersection(toks)]
    if not matches:
        return []

    scores = BM25Okapi(doc_tokens).get_scores(_tokenize(_expand(query)))
    matches.sort(key=lambda i: scores[i], reverse=True)
    ranked = [(candidates[i], float(scores[i])) for i in matches]

    fused = _dense_fuse(_expand(dense_query or query), candidates, ranked, k=k)
    window = fused if fused is not None else ranked
    return _promote_lexicon_phrases(query, candidates, window, k)


# No per-statute cap on the window: measured and rejected (RESULTS.md §9).


def _expand(text: str) -> str:
    """Bridge the everyday/statutory vocabulary gap (config.QUERY_EXPANSION).
    Additive only — the user's wording stays verbatim at the front — so a
    query that already matched cannot lose its matches."""
    if config.QUERY_EXPANSION != "on":
        return text
    from legal_agent.retrieval.lexicon import expand
    return expand(text)


# Lexicon phrases as a THIRD channel. Inclusion uses the user's own words, so a
# vocabulary-gap query sharing NO token with its target (「樓上小孩跑跳」 vs
# 社維§72) is never a match, and dense ranks such targets too deep. The
# lexicon's statutory side is VERBATIM article text, so a phrase hit is an exact
# pointer. Up to N such articles join the window tail with BM25 score 0.0 —
# the honesty tier's TOP score still comes from a real user-word match.
# N=3 is the measured knee (sweep in evals/HISTORY.md).
LEXICON_RESERVED_SEATS = 3
# Corroboration is NOT capped per row: measured and rejected (RESULTS.md §9).


def _promote_lexicon_phrases(
    query: str,
    candidates: list[Statute],
    ranked: list[tuple[Statute, float]],
    k: int,
) -> list[tuple[Statute, float]]:
    """Give the top-k window up to LEXICON_RESERVED_SEATS articles that contain a
    triggered lexicon phrase verbatim. No-op when expansion is off, no phrase
    fires, or every hit is already in the window."""
    if LEXICON_RESERVED_SEATS <= 0 or config.QUERY_EXPANSION != "on":
        return ranked[:k]
    from legal_agent.retrieval.lexicon import expansions

    phrases = expansions(query)
    if not phrases:
        return ranked[:k]

    def key_of(s: Statute) -> tuple[str, str, str]:
        return (s.statute_id, s.article_no, s.effective_from)

    window = {key_of(s) for s, _ in ranked[:k]}

    # Order phrases by selectivity: a phrase is a pointer only when it resolves
    # to few articles (「公然侮辱人者」 -> 刑§309 alone; 「負損害賠償責任」 hits 18,
    # 「土地所有人」 33). This counts ARTICLES per phrase, not the trigger-count
    # tie-break rejected in RESULTS.md. Among equally selective phrases, prefer
    # one whose OWN ROW already has an article in the window (the ranking has
    # corroborated that topic; e.g. 民法§248 beside §249), then table position.
    from legal_agent.retrieval.lexicon import LEXICON

    row_of = {}
    for index, (_triggers, statutory) in enumerate(LEXICON):
        for term in statutory:
            row_of.setdefault(term, index)
    corroborated = {
        row_of[phrase]
        for phrase in phrases
        if phrase in row_of
        and any(phrase in (s.content or "") for s, _ in ranked[:k])
    }

    # Corroboration is yes/no; weighting it by rank was rejected (RESULTS.md §9).
    matches: list[tuple[int, int, int, str, list[Statute]]] = []
    for position, phrase in enumerate(phrases):
        hits = [c for c in candidates if phrase in c.content]
        if hits:
            rank = 0 if row_of.get(phrase) in corroborated else 1
            matches.append((len(hits), rank, position, phrase, hits))
    matches.sort(key=lambda m: (m[0], m[1], m[2]))   # selective, corroborated, table

    # …but the FIRST seat goes to a topic the window does not already carry: an
    # uncorroborated row is a whole answer the window is missing.
    first_new = next((i for i, m in enumerate(matches) if m[1] != 0), None)
    if first_new is not None and first_new > 0:
        matches.insert(0, matches.pop(first_new))

    promote: list[tuple[Statute, float]] = []
    promoted_rows: list[int | None] = []      # which row won each seat, in order
    taken: set[tuple[str, str, str]] = set()
    for _count, _rank, _position, _phrase, hits in matches:
        if len(promote) >= LEXICON_RESERVED_SEATS:
            break
        for c in hits:
            key = key_of(c)
            if key not in window and key not in taken:
                promote.append((c, 0.0))
                promoted_rows.append(row_of.get(_phrase))
                taken.add(key)
                break                            # one article per phrase
    if not promote:
        return ranked[:k]

    # Making room must not evict an article the SAME phrases point at (it was
    # not promoted because it was already in the window). Trim the unprotected
    # tail first; cut a phrase-matched article only if nothing else is left.
    window_items = ranked[:k]
    protected = [
        i for i, (statute, _score) in enumerate(window_items)
        if any(phrase in (statute.content or "") for phrase in phrases)
    ]
    # Promote at most as many as there are unprotected places — a fully
    # phrase-matched window has nothing to gain from swapping — but at least one
    # when the first promotion opens a topic the window does not carry.
    unprotected = max(len(window_items) - len(protected), 0)
    floor = 1 if promoted_rows and promoted_rows[0] not in corroborated else 0
    promote = promote[: max(unprotected, floor)]
    if not promote:
        return window_items[:k]
    room = max(k - len(promote), 0)
    keep_idx = list(range(len(window_items)))
    for i in reversed(range(len(window_items))):
        if len(keep_idx) <= room:
            break
        if i in protected:
            continue
        keep_idx.remove(i)
    while len(keep_idx) > room:          # only phrase-matched items left to cut
        keep_idx.pop()
    keep = [window_items[i] for i in sorted(keep_idx)]
    return (keep + promote)[:k]


# RRF's dual-presence bonus buries dense-only items (lexically matched articles
# collect BOTH reciprocal ranks), so the dense top-N get guaranteed seats at the
# window TAIL with BM25 score 0.0. N=3 is the measured best (sweep in
# evals/HISTORY.md).
DENSE_RESERVED_SEATS = 3


# Queries whose dense half failed and silently fell back to BM25 (AGENTS.md
# trap 2). Harnesses print it as `dense_fallbacks`; a run must show 0 before
# its number is compared with a published one.
_DENSE_FALLBACKS = 0


def dense_fallback_count() -> int:
    """Queries since the last reset whose dense half failed and fell back."""
    return _DENSE_FALLBACKS


def reset_dense_fallbacks() -> None:
    global _DENSE_FALLBACKS
    _DENSE_FALLBACKS = 0


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
    if config.DENSE_RETRIEVAL == "off":
        return None
    try:
        from legal_agent.retrieval import dense
        index_keys, matrix = dense.load_index()
        dense_keys = dense.dense_rank(query, index_keys, matrix)
    except Exception:
        # Right for the product, wrong for a measurement: Ollama can unload
        # bge-m3 mid-run, so this fires per query with no error. The counter
        # makes the silence visible (see dense_fallback_count).
        global _DENSE_FALLBACKS
        _DENSE_FALLBACKS += 1
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
        k: max results (default DEFAULT_K).
        conn: optional open connection (tests point this at a fixture DB);
            defaults to the real corpus at config.DB_PATH.

    Returns:
        The ranked window (lexical matches plus any dense/lexicon reserved-seat
        promotions), or [] if no in-force candidate overlaps the query.
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

    dense_query: optional FOCUSED text (problem/goal) for the dense half, while
    `query` (the full fact set) drives BM25. Process facts are semantic noise:
    勞基§24 ranks 34 on the full facts, 5 on problem+goal. None = use `query`."""
    return _retrieve_scored(query, as_of_date, k, conn, dense_query=dense_query)
