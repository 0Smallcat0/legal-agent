"""Which corpus did this process actually read?

Two agents have computed two different answers to the same question on this
repo, each having opened a different database, and neither run carried a signal
naming which one. Both mistakes were made by throwaway scripts that hardcoded a
path — so the fingerprint has to be a one-liner, and the floor check has to
abort rather than warn.
"""
from __future__ import annotations

import json

import pytest

from legal_agent.data.bootstrap import (
    JUDGMENTS,
    PROPOSALS,
    CorpusFloorError,
    corpus_fingerprint,
    ensure_corpus,
    shipped_floor,
)
from legal_agent.data.database import connect, init_db
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals


@pytest.fixture(scope="module")
def full_db(tmp_path_factory):
    """A complete corpus, built the way a fresh install builds one."""
    path = tmp_path_factory.mktemp("fingerprint") / "full.db"
    ensure_corpus(str(path))
    return path


def test_the_floor_is_counted_from_the_shipped_files_not_typed_in():
    """A hardcoded floor stops tracking the corpus the day a proposal is added,
    which is precisely the drift the floor exists to catch."""
    from legal_agent import config

    rows = 0
    union = set()
    for name in PROPOSALS:
        entries = json.loads((config.CORPUS_DIR / name).read_text(encoding="utf-8"))
        rows += len(entries)
        union |= {(e["statute_id"], e.get("article_no") or "") for e in entries}
    judgments = len(
        json.loads((config.CORPUS_DIR / JUDGMENTS).read_text(encoding="utf-8"))
    )

    floor = shipped_floor()
    assert (floor.statutes, floor.articles, floor.judgments) == (
        rows, len(union), judgments,
    )


def test_the_fingerprint_names_the_database_it_actually_read(full_db):
    fingerprint = corpus_fingerprint(full_db)

    assert fingerprint.db_path == full_db
    assert str(full_db) in fingerprint.render()


def test_a_complete_corpus_meets_the_floor_and_does_not_abort(full_db):
    fingerprint = corpus_fingerprint(full_db)

    assert fingerprint.shortfall == ()
    assert fingerprint.require_floor() is fingerprint
    assert fingerprint.statutes == shipped_floor().statutes
    assert fingerprint.articles == shipped_floor().articles
    assert fingerprint.judgments == shipped_floor().judgments


def test_a_partial_corpus_aborts_the_run_and_says_how_much_is_missing(tmp_path):
    """The failure this guards is not a crash — it is a confident wrong number.
    Same family as `realworld.check_labels`: an article the corpus cannot hold
    scores a miss no matter how good retrieval is."""
    from legal_agent import config

    path = tmp_path / "partial.db"
    init_db(path)
    conn = connect(path)
    try:
        seed_source_hierarchy(conn)
        load_proposals(config.CORPUS_DIR / "noise_routing_proposal.json", conn)
    finally:
        conn.close()

    fingerprint = corpus_fingerprint(path)
    assert fingerprint.shortfall, "a two-article corpus must not pass as complete"
    assert "低於出貨地板" in fingerprint.render()

    with pytest.raises(CorpusFloorError) as excinfo:
        fingerprint.require_floor()
    message = str(excinfo.value)
    assert str(path) in message                       # which corpus
    assert str(shipped_floor().statutes) in message   # and how far short


def test_one_harvested_judgment_does_not_keep_the_shipped_ones_out(tmp_path):
    """A partial nightly harvest used to make `_ensure_judgments` return early,
    so the 386 shipped judgments never loaded and every harness aborted."""
    path = tmp_path / "harvested.db"
    init_db(path)
    conn = connect(path)
    try:
        conn.execute(
            "INSERT INTO judgments (jid, court, year, case_type, cited_articles, full_text) "
            "VALUES ('HARVESTED,1', 'X', 115, '測試', '[]', '')"
        )
        conn.commit()
    finally:
        conn.close()

    ensure_corpus(str(path))
    fingerprint = corpus_fingerprint(path)
    fingerprint.require_floor()                      # must not raise
    assert fingerprint.judgments == shipped_floor().judgments + 1


def test_a_database_that_does_not_exist_says_so_instead_of_reporting_zeros(tmp_path):
    fingerprint = corpus_fingerprint(tmp_path / "never-built.db")

    assert fingerprint.exists is False
    assert "不存在" in fingerprint.render()
    with pytest.raises(CorpusFloorError):
        fingerprint.require_floor()


def test_more_judgments_than_shipped_is_legal_because_the_harvester_accumulates(
    full_db, tmp_path
):
    """Below the floor aborts; above it is a machine that has been harvesting
    overnight, and aborting on that would make the check useless in real use."""
    import shutil

    grown = tmp_path / "grown.db"
    shutil.copy(full_db, grown)
    conn = connect(grown)
    try:
        row = conn.execute("SELECT * FROM judgments LIMIT 1").fetchone()
        columns = list(row.keys())
        values = [row[c] for c in columns]
        values[columns.index("jid")] = "TESTV,999,test,1"
        conn.execute(
            f"INSERT INTO judgments({','.join(columns)}) "
            f"VALUES ({','.join('?' * len(columns))})",
            values,
        )
        conn.commit()
    finally:
        conn.close()

    fingerprint = corpus_fingerprint(grown)
    assert fingerprint.judgments == shipped_floor().judgments + 1
    assert fingerprint.shortfall == ()
    assert "↑" in fingerprint.render()


def test_the_public_shortcut_reaches_the_same_answer(full_db):
    """`legal_agent.corpus_fingerprint()` is the whole point: it has to be
    cheaper to call than it is to hardcode a path."""
    import legal_agent

    assert legal_agent.corpus_fingerprint(full_db).statutes == shipped_floor().statutes
    assert "corpus_fingerprint" in legal_agent.__all__


def test_the_harness_helper_prints_the_line_and_returns_the_fingerprint(
    full_db, capsys
):
    from legal_agent.evaluation import print_corpus_fingerprint

    fingerprint = print_corpus_fingerprint(full_db)
    printed = capsys.readouterr().out

    assert "語料指紋" in printed
    assert str(full_db) in printed
    assert fingerprint.statutes == shipped_floor().statutes


# ── the other half: is all of it still there after a package upgrade? ────────
# `ensure_corpus` used to load the proposals only when the corpus was
# completely empty, so a database built before a proposal shipped stayed on the
# old corpus forever with no signal. The orphaned DB in the repo tree carries
# 2,562 rows — bulk + noise, with the 361-article gap batch missing — which is
# this failure mode having actually happened, to a file nobody was using.


def _copy(db, tmp_path, name):
    import shutil

    target = tmp_path / name
    shutil.copy(db, target)
    return target


def test_a_corpus_that_predates_a_proposal_is_repaired_on_the_next_call(
    full_db, tmp_path
):
    stale = _copy(full_db, tmp_path, "stale.db")
    conn = connect(stale)
    try:
        conn.execute("DELETE FROM statutes WHERE statute_id = ?", ("強制汽車責任保險法",))
        conn.commit()
    finally:
        conn.close()
    assert corpus_fingerprint(stale).shortfall, "the fixture must actually be short"

    ensure_corpus(str(stale))

    assert corpus_fingerprint(stale).shortfall == ()


def test_repair_restores_the_rows_exactly_and_adds_no_duplicate_time_slices(
    full_db, tmp_path
):
    """One article legitimately holds two slices, so 'restored' is a row count,
    not an article count: a second load of the same file must be skipped by the
    (statute_id, article_no, effective_from) primary key, not appended."""
    stale = _copy(full_db, tmp_path, "dup.db")
    conn = connect(stale)
    try:
        conn.execute("DELETE FROM statutes WHERE statute_id = ?", ("勞動基準法",))
        conn.commit()
    finally:
        conn.close()

    ensure_corpus(str(stale))

    fingerprint = corpus_fingerprint(stale)
    assert fingerprint.statutes == shipped_floor().statutes
    assert fingerprint.articles == shipped_floor().articles


def test_a_complete_corpus_never_opens_a_proposal_file(full_db, monkeypatch):
    """The check has to stay cheap: `ensure_corpus` runs on every
    `open_corpus`, which is every public `verify` and `retrieve` call."""
    import legal_agent.data.bootstrap as bootstrap

    def _explode(*_args, **_kwargs):
        raise AssertionError("a complete corpus must not re-read the proposals")

    monkeypatch.setattr(bootstrap, "load_proposals", _explode)
    assert ensure_corpus(str(full_db)) == shipped_floor().statutes


def test_the_dense_docstring_does_not_name_a_path_the_module_never_computes():
    """`dense.py` documented 「db/dense_bgem3.npy」 while computing
    `Path(config.DB_PATH).parent / "dense_bgem3"`. A repo-relative `db/` does
    exist and does hold files by those names — orphans, already mistaken for
    the live index twice. The docstring was teaching the trap."""
    from legal_agent.retrieval import dense

    assert "db/dense_bgem3" not in (dense.__doc__ or "")
    assert "config.DB_PATH" in (dense.__doc__ or "")
