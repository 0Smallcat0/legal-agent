"""Offline tests for the dense/hybrid retrieval module — the pure-function
parts only (RRF fusion). Embedding calls need a live Ollama and are exercised
by the measurement scripts, not by CI.

Run:  python -m pytest tests/test_dense.py -q
"""
from __future__ import annotations

import pytest

from legal_agent.retrieval.dense import rrf_fuse

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


# ── the Space's embedding backend (sentence-transformers faked) ──────────────
def test_st_backend_embeds_in_process_and_never_calls_ollama(monkeypatch):
    import numpy as np

    from legal_agent import config as cfg
    from legal_agent.retrieval import dense

    class FakeST:
        def encode(self, texts, batch_size, normalize_embeddings):
            assert normalize_embeddings
            return [[1.0, 0.0]] * len(texts)

    def no_ollama(*a, **k):
        raise AssertionError("st backend must not reach Ollama")

    monkeypatch.setattr(cfg, "EMBED_BACKEND", "st")
    monkeypatch.setattr(dense, "_st_model", lambda: FakeST())
    monkeypatch.setattr(dense.urllib.request, "urlopen", no_ollama)
    out = dense.embed_texts(["甲", "乙"])
    assert out.dtype == np.float32 and out.shape == (2, 2)


# A stand-in worker speaking st_worker's protocol: row i is [len(text_i), i].
_FAKE_WORKER = """
import json, sys
import numpy as np
from legal_agent.retrieval.st_worker import write_matrix
for line in sys.stdin.buffer:
    texts = json.loads(line)["texts"]
    write_matrix(sys.stdout.buffer, np.array([[len(t), i] for i, t in enumerate(texts)]))
"""


def test_st_process_trades_text_for_rows_over_the_pipe_and_reuses_one_worker():
    import sys

    import numpy as np

    from legal_agent.retrieval.st_worker import STProcess

    proc = STProcess([sys.executable, "-c", _FAKE_WORKER])
    first = proc.encode(["噪音", "押金不退"])
    assert first.dtype == np.float32
    assert first.tolist() == [[2.0, 0.0], [4.0, 1.0]]
    worker = proc._proc
    assert proc.encode(["甲"]).tolist() == [[1.0, 0.0]]
    assert proc._proc is worker                 # not restarted per query
    proc._proc.kill()


def test_a_dead_worker_raises_so_retrieval_can_fall_back():
    import sys

    from legal_agent.retrieval.st_worker import STProcess

    proc = STProcess([sys.executable, "-c", "import sys; sys.stdin.readline()"])
    with pytest.raises(RuntimeError, match="exited"):
        proc.encode(["甲"])
