"""One call that makes a fresh install runnable: schema + corpus, idempotent.

Cheap to call from anywhere: when the corpus is complete it returns without
reading the proposal files. Also home of `corpus_fingerprint()` — which
database this process reads, and whether it carries everything the package
shipped.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from legal_agent import config
from legal_agent.data.database import connect, init_db
from legal_agent.data.judgment_ingest import load_judgments
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals

# Source of truth for the shipped corpus. (The old hand-typed noise seed is not
# loaded: with the official-XML proposal it would duplicate current slices.)
PROPOSALS = (
    "moj_bulk_v1_proposal.json",
    # Gap batch: statutes triage routes to (強制汽車責任保險法, 勞保條例, 就服法,
    # 性平法) that the bulk batch lacked.
    "moj_gap_v1_proposal.json",
    "noise_routing_proposal.json",
)

# Reference judgments, redacted to the two slices a page renders (see
# data/judgment_ingest.py). Shipped because the harvester cannot practically
# rebuild them: the 司法院 API serves 00:00-06:00 and returns one day at a time.
JUDGMENTS = "judgments_v1.json"


def corpus_size(conn: sqlite3.Connection) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]
    except sqlite3.OperationalError:      # table not created yet
        return 0


def _statutes_are_short(conn: sqlite3.Connection) -> bool:
    """Does the table hold fewer articles than the shipped proposals carry?

    One aggregate per statute (~0.2ms), not ~2,900 keys. Sound because articles
    are only ever added, so a count below the shipped one means one is absent.
    Checking only for an EMPTY table would leave a database that predates a
    proposal file (e.g. 2,562 rows without the 361-article gap batch) stale
    forever.
    """
    try:
        have = dict(
            conn.execute(
                "SELECT statute_id, COUNT(DISTINCT article_no) FROM statutes "
                "GROUP BY statute_id"
            )
        )
    except sqlite3.OperationalError:      # table not created yet
        return True
    return any(
        have.get(sid, 0) < wanted for sid, wanted in _shipped_articles_by_statute().items()
    )


def ensure_corpus(db_path=None) -> int:
    """Build the schema and load any part of the shipped corpus that is missing.

    Returns the article count. Idempotent and fast on an already-loaded DB:
    the completeness check is one aggregate query, and the proposal files are
    only read when something is actually short. Re-loading cannot duplicate a
    time slice — `statutes`' primary key is (statute_id, article_no,
    effective_from), so an article already present raises IntegrityError and
    `load_proposals` skips it.
    """
    path = db_path or config.DB_PATH
    init_db(path)
    conn = connect(path)
    try:
        seed_source_hierarchy(conn)
        if _statutes_are_short(conn):
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
    """Make sure every shipped reference judgment is present. Returns the row count.

    Harvested judgments (from `data/judicial_api.py`) live in the same table.
    The shipped file is a floor, never an overwrite: rows already present are
    ignored. Loaded whenever any shipped jid is missing, so a partial harvest
    cannot keep the shipped judgments out; a complete table is only read.
    """
    shipped = config.CORPUS_DIR / JUDGMENTS
    jids = shipped_judgment_ids()
    if jids and _present_count(conn, jids) < len(jids):
        load_judgments(shipped, conn)
    return judgment_count(conn)


@lru_cache(maxsize=1)
def shipped_judgment_ids() -> tuple[str, ...]:
    """The jids the package ships (parsed once per process)."""
    shipped = config.CORPUS_DIR / JUDGMENTS
    if not shipped.exists():
        return ()
    return tuple(r["jid"] for r in json.loads(shipped.read_text(encoding="utf-8")))


def _present_count(conn: sqlite3.Connection, jids: tuple[str, ...]) -> int:
    """How many of `jids` the table holds — a read, so a loaded DB is not written."""
    try:
        marks = ",".join("?" * len(jids))
        return conn.execute(
            f"SELECT COUNT(*) FROM judgments WHERE jid IN ({marks})", jids
        ).fetchone()[0]
    except sqlite3.OperationalError:      # judgments table not created yet
        return 0


# ── which corpus am I reading, and is all of it there? ───────────────────────
# Scripts that hardcode a DB path can silently read a different database than
# the harnesses; checking must be cheaper than hardcoding: one call, one line.


@dataclass(frozen=True)
class CorpusFloor:
    """What the files inside the installed package carry.

    Counted from the files, never typed in: a hardcoded number stops tracking
    the corpus the moment a proposal is added, which is the very drift this
    floor exists to catch.
    """

    statutes: int          # rows the proposal files carry, summed
    articles: int          # distinct (statute_id, article_no) among them
    judgments: int         # rows the shipped judgment file carries


class CorpusFloorError(RuntimeError):
    """The database carries less than the package shipped.

    Same failure family as `evaluation.realworld.BadLabelError`: a label the
    corpus can never match and an article the corpus does not hold both produce
    a confident wrong number rather than an error. Both abort the run.
    """


@lru_cache(maxsize=1)
def _shipped_article_keys() -> tuple[frozenset[tuple[str, str]], int]:
    """(distinct (statute_id, article_no) across PROPOSALS, total row count)."""
    keys: set[tuple[str, str]] = set()
    rows = 0
    for name in PROPOSALS:
        proposal = config.CORPUS_DIR / name
        if not proposal.exists():
            continue
        entries = json.loads(proposal.read_text(encoding="utf-8"))
        rows += len(entries)
        keys.update(
            (entry["statute_id"], entry.get("article_no") or "") for entry in entries
        )
    return frozenset(keys), rows


@lru_cache(maxsize=1)
def _shipped_articles_by_statute() -> dict[str, int]:
    """How many distinct articles each statute should have. Used by
    `ensure_corpus` to decide whether the corpus is complete without reading
    the proposal files on every call."""
    counts: dict[str, int] = {}
    for statute_id, _article_no in _shipped_article_keys()[0]:
        counts[statute_id] = counts.get(statute_id, 0) + 1
    return counts


@lru_cache(maxsize=1)
def shipped_floor() -> CorpusFloor:
    """The corpus the installed package can build on its own.

    Cheap after the first call (the files never change at runtime): about 8ms
    of JSON on a cold cache, nothing afterwards.
    """
    keys, rows = _shipped_article_keys()
    shipped = config.CORPUS_DIR / JUDGMENTS
    judgments = (
        len(json.loads(shipped.read_text(encoding="utf-8"))) if shipped.exists() else 0
    )
    return CorpusFloor(statutes=rows, articles=len(keys), judgments=judgments)


@dataclass(frozen=True)
class CorpusFingerprint:
    """Which database this process reads, and what is in it."""

    db_path: Path
    exists: bool
    statutes: int          # rows in the statutes table (time slices, not articles)
    articles: int          # distinct (statute_id, article_no)
    judgments: int
    floor: CorpusFloor

    @property
    def shortfall(self) -> tuple[str, ...]:
        """Counts below the shipped floor, worded for a person. Empty when none.

        Above the floor is LEGAL and not reported here: an overnight harvest
        accumulates judgments, and a machine that has been running the
        harvester holds more than the package ships.
        """
        gaps = []
        if not self.exists:
            return (f"資料庫不存在:{self.db_path}",)
        for label, have, want in (
            ("statutes 列", self.statutes, self.floor.statutes),
            ("distinct 條號", self.articles, self.floor.articles),
            ("judgments 列", self.judgments, self.floor.judgments),
        ):
            if have < want:
                gaps.append(f"{label} {have}/{want}(缺 {want - have})")
        return tuple(gaps)

    def render(self) -> str:
        """The one line a harness prints before it prints any number."""
        if not self.exists:
            return f"語料指紋:{self.db_path} —— 不存在"
        over = "" if self.judgments <= self.floor.judgments else "↑"
        state = "低於出貨地板" if self.shortfall else "達出貨地板"
        return (
            f"語料指紋:{self.db_path}"
            f"｜statutes {self.statutes} 列 / {self.articles} 條號"
            f"｜judgments {self.judgments}{over}"
            f"｜地板 {self.floor.statutes}/{self.floor.articles}/{self.floor.judgments}"
            f"｜{state}"
        )

    def require_floor(self) -> CorpusFingerprint:
        """Abort unless the database carries at least what the package ships."""
        if self.shortfall:
            raise CorpusFloorError(
                f"這個語料低於出貨地板,任何數字都會是自信的假數字:{self.db_path}"
                f" —— " + "、".join(self.shortfall)
                + "。先跑 `python -c \"import legal_agent; legal_agent.ensure_corpus()\"`。"
            )
        return self


def corpus_fingerprint(
    db_path=None, conn: sqlite3.Connection | None = None
) -> CorpusFingerprint:
    """Which corpus is this process reading. Read-only: never builds, never raises.

    Building is `ensure_corpus`'s job and raising is `require_floor`'s, so this
    stays safe to call from a throwaway script that only wants to know whether
    it is looking at the same database the harnesses are.
    """
    path = Path(db_path or config.DB_PATH)
    floor = shipped_floor()
    if conn is None and not path.exists():
        return CorpusFingerprint(path, False, 0, 0, 0, floor)
    own = connect(path) if conn is None else None
    active = conn if own is None else own
    try:
        statutes = corpus_size(active)
        try:
            articles = active.execute(
                "SELECT COUNT(*) FROM (SELECT DISTINCT statute_id, article_no "
                "FROM statutes)"
            ).fetchone()[0]
        except sqlite3.OperationalError:      # table not created yet
            articles = 0
        return CorpusFingerprint(
            path, True, statutes, articles, judgment_count(active), floor
        )
    finally:
        if own is not None:
            own.close()
