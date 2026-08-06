"""Legal Agent — citations verified by code, and the verifier graded by seeded defects.

Three calls, each usable on its own. The database builds itself from the corpus
shipped inside this package on first use, so nothing here needs a git clone, an
API key, a model, or a network:

    >>> import legal_agent
    >>> for r in legal_agent.verify("依民法第184條,故意不法侵害他人權利者負賠償責任。"):
    ...     print(r.flagged, r.reason)

    >>> for statute in legal_agent.retrieve("退租後房東不退押金"):
    ...     print(statute.statute_id, statute.article_no)

`verify` is the piece worth lifting: it extracts every statute citation from
generated text and checks three axes against the corpus — does the article
exist, does the claim match the verbatim text, was it in force on the date. It
is pure Python. No model is consulted, so it cannot be talked out of a verdict.

The submodules stay importable for everything this shortcut does not cover
(`legal_agent.evaluation.mutation` grades the verifier itself;
`legal_agent.dialogue` runs the four-stage consultation; `legal_agent.data`
harvests and ingests). Package layout mirrors SPEC.md:

    data/               §1   time-sliced statute corpus + judgment harvester
    retrieval/          §2.2 hybrid retrieval, point-in-time filtered
    anti_hallucination/ §2   the five-gate defense
    dialogue/           §3   four-stage clinic flow
    evaluation/         §4   golden set, mutation test, calibration, recall
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

__version__ = "0.1.0"

__all__ = [
    "Statute",
    "VerificationResult",
    "__version__",
    "corpus_path",
    "ensure_corpus",
    "open_corpus",
    "retrieve",
    "retrieve_scored",
    "verify",
]


def __getattr__(name: str):
    # Lazy: `jieba` alone costs about a second, and a caller who only wants
    # `verify` should not pay for the retriever's tokeniser.
    if name == "Statute":
        from legal_agent.data.models import Statute

        return Statute
    if name == "VerificationResult":
        from legal_agent.anti_hallucination.verifier import VerificationResult

        return VerificationResult
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def corpus_path() -> Path:
    """Where the database lives. Override with ``LEGAL_AGENT_DB``."""
    from legal_agent import config

    return Path(config.DB_PATH)


def ensure_corpus(db_path: str | Path | None = None) -> int:
    """Build the corpus if it is not there yet; return the article count.

    Idempotent and fast once built. `verify` and `retrieve` call it for you, so
    you only need it directly to control *when* the first (few-second) build
    happens — at startup rather than inside a request.
    """
    from legal_agent.data.bootstrap import ensure_corpus as _ensure

    return _ensure(str(db_path) if db_path else None)


def open_corpus(db_path: str | Path | None = None) -> sqlite3.Connection:
    """A connection to a ready corpus, for callers making many calls.

    Pass it back in as ``conn=`` to avoid reopening per call. The caller closes it.
    """
    from legal_agent.data.database import connect

    path = Path(db_path) if db_path else corpus_path()
    ensure_corpus(path)
    return connect(path)


def verify(
    answer: str,
    as_of: str | None = None,
    conn: sqlite3.Connection | None = None,
    db_path: str | Path | None = None,
) -> list:
    """Check every statute citation in `answer` against the corpus.

    Returns one result per citation, each carrying `exists`, `content_match`,
    `in_force`, `flagged`, `reason`, and the verbatim source text when the
    article was found — so a caller can show the reader what the law actually
    says next to what was claimed.

    `as_of` (``"YYYY-MM-DD"``) checks the version in force on that date rather
    than today's, which is how an anachronistic citation gets caught.
    """
    from legal_agent.anti_hallucination.verifier import verify_answer

    own = None if conn is not None else open_corpus(db_path)
    active = conn if conn is not None else own
    try:
        return verify_answer(answer, [], as_of_date=as_of, conn=active, corpus_conn=active)
    finally:
        if own is not None:
            own.close()


def retrieve_scored(
    query: str,
    as_of: str | None = None,
    k: int | None = None,
    conn: sqlite3.Connection | None = None,
    db_path: str | Path | None = None,
) -> list[tuple]:
    """Ranked ``(Statute, score)`` pairs for `query`, filtered by date FIRST.

    The point-in-time filter runs before ranking, so a repealed version cannot
    be retrieved and then explained away. `as_of=None` means "in force now".
    `k=None` means the tuned window, `retriever.DEFAULT_K` — this was a
    hardcoded 8, which quietly became a SECOND default the day the tuned one
    moved to 12, handing callers of the public API a narrower window than every
    published number was measured with.
    """
    from legal_agent.retrieval.retriever import DEFAULT_K
    from legal_agent.retrieval.retriever import retrieve_scored as _retrieve

    own = None if conn is not None else open_corpus(db_path)
    active = conn if conn is not None else own
    try:
        return _retrieve(query, as_of_date=as_of, k=k or DEFAULT_K, conn=active)
    finally:
        if own is not None:
            own.close()


def retrieve(
    query: str,
    as_of: str | None = None,
    k: int | None = None,
    conn: sqlite3.Connection | None = None,
    db_path: str | Path | None = None,
) -> list:
    """The statutes `retrieve_scored` ranks, without the scores."""
    return [
        statute for statute, _score
        in retrieve_scored(query, as_of=as_of, k=k, conn=conn, db_path=db_path)
    ]
