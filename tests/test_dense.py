"""Offline tests for the dense/hybrid retrieval module — the pure-function
parts only (RRF fusion). Embedding calls need a live Ollama and are exercised
by the measurement scripts, not by CI.

Run:  python -m pytest tests/test_dense.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.retrieval.dense import rrf_fuse  # noqa: E402

A = ("甲法", "第1條", "2020-01-01")
B = ("乙法", "第2條", "2020-01-01")
C = ("丙法", "第3條", "2020-01-01")


def test_rrf_rewards_agreement():
    # B appears at #2 in BOTH rankings; A and C appear only once (at #1).
    # 2/(60+2) > 1/(60+1): showing up in both lists beats one solo #1.
    fused = rrf_fuse([[A, B], [C, B]])
    assert fused[0] == B


def test_rrf_handles_disjoint_rankings():
    # keys missing from one ranking simply score nothing from it
    fused = rrf_fuse([[A], [B]])
    assert set(fused) == {A, B}


def test_rrf_is_deterministic_on_ties():
    # identical contributions -> stable tie-break by key, run to run
    assert rrf_fuse([[A], [B]]) == rrf_fuse([[A], [B]])


# ── hybrid wiring in the retriever (dense layer faked, no Ollama) ────────────
def _hybrid_conn(tmp_path):
    from legal_agent.data.database import connect, init_db
    from legal_agent.data.seed import seed_source_hierarchy

    db = tmp_path / "h.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    conn.executemany(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("甲法", "第1條", "維護居住安寧之規定。", "2020-01-01", None, "法律", "http://x/1"),
            ("乙法", "第2條", "延長工作時間之工資加給標準。", "2020-01-01", None, "法律", "http://x/2"),
        ],
    )
    conn.commit()
    return conn


def test_fusion_promotes_dense_only_candidate(tmp_path, monkeypatch):
    # query hits 甲法 lexically (安寧) but NOT 乙法 (the vocabulary-gap shape);
    # a faked dense ranking surfaces 乙法 — it must enter the results with its
    # honest lexical score of 0.0, and 甲法 must keep its real BM25 score.
    from legal_agent import config as cfg
    from legal_agent.retrieval import dense, retriever

    conn = _hybrid_conn(tmp_path)
    monkeypatch.setattr(cfg, "DENSE_RETRIEVAL", "auto")
    key_a = ("甲法", "第1條", "2020-01-01")
    key_b = ("乙法", "第2條", "2020-01-01")
    monkeypatch.setattr(dense, "load_index", lambda stem=None: ([key_a, key_b], object()))
    monkeypatch.setattr(dense, "dense_rank", lambda q, keys, m, model=None: [key_b, key_a])

    results = retriever.retrieve_scored("加班費爭議影響安寧", conn=conn)
    by_id = {s.statute_id: sc for s, sc in results}
    assert set(by_id) == {"甲法", "乙法"}
    assert by_id["乙法"] == 0.0          # dense-only: lexically unmatched

    # BM25 score untouched by fusion: identical to the pure-BM25 run
    monkeypatch.setattr(cfg, "DENSE_RETRIEVAL", "off")
    pure = {s.statute_id: sc for s, sc in
            retriever.retrieve_scored("加班費爭議影響安寧", conn=conn)}
    assert by_id["甲法"] == pure["甲法"]
    conn.close()


def test_fusion_falls_back_to_bm25_when_index_missing(tmp_path, monkeypatch):
    from legal_agent import config as cfg
    from legal_agent.retrieval import dense, retriever

    conn = _hybrid_conn(tmp_path)
    monkeypatch.setattr(cfg, "DENSE_RETRIEVAL", "auto")
    def boom(stem=None):
        raise FileNotFoundError("no index")
    monkeypatch.setattr(dense, "load_index", boom)

    results = retriever.retrieve_scored("維護安寧", conn=conn)
    assert [s.statute_id for s, _ in results] == ["甲法"]   # pure BM25 behaviour
    conn.close()
