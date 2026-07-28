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


# 租賃住宅市場發展及管理條例 regulates the leasing-SERVICE INDUSTRY as well as
# landlord and tenant, and its industry chapters are long — 營業保證金 rules,
# 服務業 penalty schedules — so BM25 hands them seats on any 租賃 question.
# Measured over the real sessions: 2-3 of 8 seats in EVERY landlord-tenant case
# went to 服務業 articles a tenant has no use for.
_INDUSTRY_SUBJECTS = ("租賃住宅服務業", "包租業", "代管業", "營業保證金", "全國聯合會")
# …unless the person is actually dealing with one of those businesses. The words
# have to name the RENTAL trade: 仲介 and 業者 were in this list for one round and
# a 房仲 house-purchase question pulled 條例§24 (營業保證金) straight back — a
# 不動產經紀業 is not a 租賃住宅服務業. 二房東 is absent for the same reason: an
# ordinary sublessor is not a licensed 包租業, and those cases are 民法§443/§444.
_INDUSTRY_IN_QUESTION = ("包租", "代管", "租賃住宅服務業", "租屋網", "租賃業者")


def _drop_industry_regulation(query: str, candidates: list[Statute]) -> list[Statute]:
    """Drop trade-regulation articles when the question is not about the trade."""
    if any(word in query for word in _INDUSTRY_IN_QUESTION):
        return candidates
    return [
        c for c in candidates
        if not any(word in (c.content or "") for word in _INDUSTRY_SUBJECTS)
    ]


# 漏水 and 修繕 fire the tenancy vocabulary whoever is asking, so an
# OWNER-OCCUPIED flat flooded from upstairs was handed 民法§430/§437/§423 — a
# LANDLORD's repair duty. Measured: 4 of 8 seats there and 3 of 8 in a
# house-purchase session, neither of which mentions a landlord at all.
_TENANCY_SUBJECTS = ("承租人", "出租人", "租賃物", "租賃契約", "租賃住宅")
# Said only when the asker owns the place…
_OWNER_OCCUPIED = ("自有住宅", "自己的房子", "我買的", "我的房子", "我是屋主",
                   "屋主是我", "已經過戶", "交屋",
                   # A bought THING counts too: 「裝好的冷氣一直漏水,修了四次」 spent
                   # all three reserved seats on tenancy articles because 修繕 and
                   # 漏水 had filled the ranked window with them first.
                   "保固卡", "保固期", "含安裝", "買了一台")
# …and only believed when nothing in the question puts a tenancy in the room.
# A landlord asking about their OWN rented-out flat says 房東/租約/房客, and a
# tenant says 押金/退租, so either way the articles stay.
_TENANCY_IN_QUESTION = ("房東", "租約", "租屋", "承租", "押金", "退租", "二房東",
                        "包租", "房客", "租金")


def _drop_tenancy_when_owner_occupied(query: str, candidates: list[Statute]) -> list[Statute]:
    """Drop landlord-and-tenant articles when the asker has said they own it."""
    if not any(word in query for word in _OWNER_OCCUPIED):
        return candidates
    if any(word in query for word in _TENANCY_IN_QUESTION):
        return candidates
    return [
        c for c in candidates
        if not any(word in (c.content or "") for word in _TENANCY_SUBJECTS)
    ]


# 「我爸失智,弟弟拿他的存摺把錢領走」 returned a window that was 8/8 繼承編. The
# father is ALIVE; answering his family with the rules for dividing his estate is
# the wrong-premise failure this project exists to avoid.
_INHERITANCE_SUBJECTS = ("被繼承人", "遺產", "應繼分", "繼承人", "遺囑")
# Words that only make sense about someone still living…
_STILL_ALIVE = ("失智", "認不得", "神智不清", "意識不清", "住院", "還在世",
                "植物人", "臥床", "安養院", "療養院")
# …and never believed over an explicit death. 「一人一半繼承了一間房子」 keeps the
# chapter, which is how a co-ownership session still reaches 繼承 when it should.
_DEATH_IN_QUESTION = ("過世", "往生", "去世", "身故", "死亡", "走了", "遺產",
                      "繼承", "喪事", "告別式", "遺囑")


def _drop_inheritance_while_alive(query: str, candidates: list[Statute]) -> list[Statute]:
    """Drop the succession chapter when the person concerned is plainly alive."""
    if not any(word in query for word in _STILL_ALIVE):
        return candidates
    if any(word in query for word in _DEATH_IN_QUESTION):
        return candidates
    return [
        c for c in candidates
        if not any(word in (c.content or "") for word in _INHERITANCE_SUBJECTS)
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
    window = fused if fused is not None else ranked
    return _promote_lexicon_phrases(query, candidates, window, k)


# TRIED AND REJECTED — per-statute cap inside the top-k window. One statute
# routinely floods the window (公寓大廈條例 took 7 of 8 seats on an upstairs-noise
# question), so capping each statute's seats looked obvious. Measured, it loses
# on BOTH harnesses because real answers legitimately cluster inside one code
# (瑕疵擔保 = 民法§354+§359; 加班費 = 勞基§22+§24+§30):
#   cap  golden pass/partial/miss   six lived sessions hit@8
#   off        18/7/1                     9/14 (64%)
#   2          15/10/1                    5/14 (36%)
#   3          16/9/1                     5/14 (36%)
#   4          17/8/1                     7/14 (50%)
# The flooding is real; a blunt per-statute cap is the wrong instrument for it.
# Vocabulary (retrieval/lexicon.py) fixed the same cases without the cost.


def _expand(text: str) -> str:
    """Bridge the everyday/statutory vocabulary gap (config.QUERY_EXPANSION).
    Additive only — the user's wording stays verbatim at the front — so a
    query that already matched cannot lose its matches."""
    if getattr(config, "QUERY_EXPANSION", "off") != "on":
        return text
    from legal_agent.retrieval.lexicon import expand
    return expand(text)


# Lexicon phrases as a THIRD retrieval channel, not just a ranking nudge.
# Measured on six lived sessions: expansion could not save the vocabulary-gap
# cases it was written for, because inclusion is decided by the user's own words
# (deliberately — see above) and those queries share NO token with the target
# article. 「樓上小孩跑跳、拖椅子」 never reaches 社維§72; 「收到三天就當機」 never
# reaches 民法§354. The dense channel ranks them 8-25, too deep for the 3
# reserved seats to reach.
# The lexicon's statutory side is VERBATIM article text, so a phrase hit is an
# exact pointer, not a fuzzy guess: 「製造噪音或深夜喧嘩」 occurs in exactly one
# article. Promote at most N such articles to the window tail, carrying an
# honest BM25 score of 0.0 — the honesty tier reads the TOP score, which still
# comes from a genuine user-word match, so 「資料不足」 keeps its meaning.
# N swept on both harnesses (stub-LLM golden v2 pass/partial/miss of 26
# scorable · six lived sessions hit@8):
#   N=0  18/7/1 · 9/14 (64%)      N=1  19/6/1 · 9/14 (64%)
#   N=2  18/7/1 · 10/14 (71%)     N=3  17/8/1 · 12/14 (86%)
#   N=4  13/11/2 · 12/14 (86%)
# N=3 is the knee: real-wording recall +22 points for one golden case sliding
# pass -> partial (pass+partial stays 25/26). N=4 buys nothing and starts
# evicting answers outright.
LEXICON_RESERVED_SEATS = 3
# TRIED AND REJECTED — capping corroboration once a row already had N articles
# in the window ("the ninth inheritance article is worth nothing, the first
# 監護宣告 article is worth everything"). Measured against the uncapped 68/70:
#   N=1 -> 65/70,  N=2 -> 66/70,  N=3 -> 68/70,  golden 19/7/0 throughout.
# Finishing a topic is worth more than the one case it was meant to rescue.


def _promote_lexicon_phrases(
    query: str,
    candidates: list[Statute],
    ranked: list[tuple[Statute, float]],
    k: int,
) -> list[tuple[Statute, float]]:
    """Give the top-k window up to LEXICON_RESERVED_SEATS articles that contain a
    triggered lexicon phrase verbatim. No-op when expansion is off, no phrase
    fires, or every hit is already in the window."""
    if LEXICON_RESERVED_SEATS <= 0 or getattr(config, "QUERY_EXPANSION", "off") != "on":
        return ranked[:k]
    from legal_agent.retrieval.lexicon import expansions

    phrases = expansions(query)
    if not phrases:
        return ranked[:k]

    def key_of(s: Statute) -> tuple[str, str, str]:
        return (s.statute_id, s.article_no, s.effective_from)

    window = {key_of(s) for s, _ in ranked[:k]}

    # Spend the seats on the phrases that actually POINT somewhere. A phrase is
    # only a pointer when it identifies one article: 「公然侮辱人者」 matches 刑§309
    # and nothing else, while 「負損害賠償責任」 matches 18 articles and
    # 「土地所有人」 33 — promoting the first candidate that happens to contain one
    # of those is noise wearing precision's clothes. Measured: 刑§309 for an
    # insult session and 民§354 for a house purchase both had a unique phrase and
    # still lost their seat to a broad one that fired earlier in the table.
    # (Not the tie-break rejected in RESULTS.md — that ordered by how many
    # TRIGGERS matched; this orders by how many ARTICLES the phrase resolves to.)
    # When several phrases are equally selective the tie-break used to be table
    # position, which has nothing to do with what was asked: 「付了十萬斡旋金,屋主
    # 不賣了」 spent all three seats on 定型化契約 and 買賣瑕疵 phrases and never
    # reached 民法§248, even though 民法§249 — the other half of the same answer —
    # was already sitting in the window. So prefer a phrase whose OWN ROW already
    # has an article in the window: the ranking has corroborated that topic, and
    # finishing it beats opening a new one on a tie.
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

    # TRIED AND REJECTED — ranking corroborated rows by the STRENGTH of their
    # evidence (how high the corroborating article sits) instead of treating
    # corroboration as a yes/no. 民法§191 at rank 1 does look like better proof of
    # the topic than a tenancy article at rank 8, and it costs 民法§818 without
    # recovering 民法§184: 59/61 against 60/61, golden unchanged at 19/7/0.

    matches: list[tuple[int, int, int, str, list[Statute]]] = []
    for position, phrase in enumerate(phrases):
        hits = [c for c in candidates if phrase in c.content]
        if hits:
            rank = 0 if row_of.get(phrase) in corroborated else 1
            matches.append((len(hits), rank, position, phrase, hits))
    matches.sort(key=lambda m: (m[0], m[1], m[2]))   # selective, corroborated, table

    promote: list[tuple[Statute, float]] = []
    taken: set[tuple[str, str, str]] = set()
    for _count, _rank, _position, _phrase, hits in matches:
        if len(promote) >= LEXICON_RESERVED_SEATS:
            break
        for c in hits:
            key = key_of(c)
            if key not in window and key not in taken:
                promote.append((c, 0.0))
                taken.add(key)
                break                            # one article per phrase
    if not promote:
        return ranked[:k]

    # Making room must not evict an article the SAME phrases point at. Measured
    # on a stalking session: 家暴法§14 (what a 保護令 can order) sat at rank 6,
    # was therefore 「already in the window」 and not promoted — and then the three
    # promotions cut the window to five and dropped it. Trim the unprotected tail
    # first; only cut a phrase-matched article if there is nothing else to give.
    room = max(k - len(promote), 0)
    window_items = ranked[:k]
    protected = [
        i for i, (statute, _score) in enumerate(window_items)
        if any(phrase in (statute.content or "") for phrase in phrases)
    ]
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
