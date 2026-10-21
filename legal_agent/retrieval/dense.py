"""Dense retrieval via local Ollama embeddings — the hybrid half that closes
BM25's vocabulary gap.

「雇主不給加班費」 shares no token with 勞基法§24 (「延長工作時間之工資」); their
embedding cosine is 0.70. Model: bge-m3 (nomic-embed-text was measured and
rejected on Traditional-Chinese legal text; ranks in evals/HISTORY.md).

  * OPTIONAL — no Ollama or no index -> callers fall back to pure BM25. That
    fallback is SILENT (AGENTS.md trap 2); retriever.dense_fallback_count()
    counts it.
  * No new dependencies — urllib + numpy (via rank_bm25). The Space, which has
    no Ollama, embeds with sentence-transformers instead
    (LEGAL_AGENT_EMBED=st, `pip install .[space]`).
  * Fusion is RRF: rank-based, no tuned weights, deterministic.

The index (current slices only) is cached beside the DATABASE, under
`Path(config.DB_PATH).parent` (`LEGAL_AGENT_HOME`), NOT the repo:
    <config.DB_PATH>/../dense_bgem3.npy        float32 [N, 1024] L2-normalized
    <config.DB_PATH>/../dense_bgem3.keys.json  [[statute_id, article_no, effective_from], ...]
A repo-relative `db/` holding files by these names is an orphan no code reads;
`legal_agent.corpus_fingerprint()` prints the real path.
"""
from __future__ import annotations

import json
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

from legal_agent import config

EMBED_MODEL = "bge-m3"
# The same model's published weights, for config.EMBED_BACKEND = "st" (the
# Space, which has no Ollama). Its own index file: the two are measured
# separately in evals/RESULTS.md §10, so they are never mixed in one ranking.
ST_EMBED_MODEL = "BAAI/bge-m3"
_DEFAULT_STEM = Path(config.DB_PATH).parent / (
    "dense_bgem3_st" if config.EMBED_BACKEND == "st" else "dense_bgem3"
)
_BATCH = 64


@lru_cache(maxsize=1)
def _st_model():
    # A separate process, CPU: a model forward in the Space's main process
    # breaks every @spaces.GPU call after it (st_worker.py says why).
    from legal_agent.retrieval.st_worker import STProcess

    return STProcess()


def embed_texts(
    texts: list[str],
    model: str = EMBED_MODEL,
    host: str | None = None,
    timeout: float = 120.0,
) -> np.ndarray:
    """Embed a list of texts via Ollama /api/embed, or sentence-transformers
    when config.EMBED_BACKEND is "st". Returns L2-normalized
    float32 [len(texts), dim]. Raises on any transport/shape error — the
    CALLER decides whether that means fall back to BM25."""
    if config.EMBED_BACKEND == "st":
        out = _st_model().encode(texts, batch_size=_BATCH, normalize_embeddings=True)
        return np.asarray(out, dtype=np.float32)
    base = (host or config.OLLAMA_HOST).rstrip("/")
    rows: list[list[float]] = []
    for start in range(0, len(texts), _BATCH):
        body = json.dumps(
            {"model": model, "input": texts[start:start + _BATCH]}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/embed", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows.extend(data["embeddings"])
    matrix = np.asarray(rows, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _current_slices(conn) -> tuple[list[tuple[str, str, str]], list[str]]:
    rows = conn.execute(
        "SELECT statute_id, article_no, effective_from, content FROM statutes "
        "WHERE effective_to IS NULL ORDER BY statute_id, article_no, effective_from"
    ).fetchall()
    keys = [(r[0], r[1], r[2]) for r in rows]
    texts = [f"{r[0]}{r[1]}:{r[3]}" for r in rows]   # bge-m3: no task prefixes
    return keys, texts


def ensure_index(
    conn,
    stem: Path | str = _DEFAULT_STEM,
    model: str = EMBED_MODEL,
) -> tuple[list[tuple[str, str, str]], np.ndarray]:
    """Load the cached corpus index, rebuilding iff the current-slice key set
    changed. Returns (keys, matrix). Raises when Ollama is unreachable and no
    valid cache exists."""
    stem = Path(stem)
    npy, keys_json = stem.with_suffix(".npy"), stem.with_suffix(".keys.json")
    keys, texts = _current_slices(conn)

    if npy.exists() and keys_json.exists():
        cached_keys = [tuple(k) for k in json.loads(keys_json.read_text(encoding="utf-8"))]
        if cached_keys == keys:
            return keys, np.load(npy)

    matrix = embed_texts(texts, model=model)
    npy.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy, matrix)
    keys_json.write_text(json.dumps(keys, ensure_ascii=False), encoding="utf-8")
    return keys, matrix


def load_index(
    stem: Path | str = _DEFAULT_STEM,
) -> tuple[list[tuple[str, str, str]], np.ndarray]:
    """Load the cached index WITHOUT touching the DB or Ollama — the runtime
    path. Raises FileNotFoundError when no index has been built yet (callers
    fall back to BM25); rebuild explicitly with:
        python -m legal_agent.retrieval.dense
    A stale index degrades smoothly: keys that no longer exist simply never
    match a live candidate, and new articles just miss the dense boost."""
    stem = Path(stem)
    npy, keys_json = stem.with_suffix(".npy"), stem.with_suffix(".keys.json")
    if not (npy.exists() and keys_json.exists()):
        raise FileNotFoundError(f"dense index not built: {stem}")
    keys = [tuple(k) for k in json.loads(keys_json.read_text(encoding="utf-8"))]
    return keys, np.load(npy)


def dense_rank(
    query: str,
    keys: list[tuple[str, str, str]],
    matrix: np.ndarray,
    model: str = EMBED_MODEL,
) -> list[tuple[str, str, str]]:
    """All corpus keys ranked by cosine similarity to the query, best first."""
    q = embed_texts([query], model=model)[0]
    sims = matrix @ q
    return [keys[i] for i in np.argsort(-sims)]


def rrf_fuse(
    rankings: list[list[tuple[str, str, str]]],
    k: int = 60,
) -> list[tuple[str, str, str]]:
    """Reciprocal-rank fusion: score(key) = Σ 1/(k + rank_i). Keys missing from
    a ranking simply contribute nothing from it. Deterministic tie-break by key."""
    scores: dict[tuple[str, str, str], float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda key: (-scores[key], key))


if __name__ == "__main__":  # python -m legal_agent.retrieval.dense  (build/refresh index)
    from legal_agent.data.bootstrap import ensure_corpus
    from legal_agent.data.database import connect

    ensure_corpus()
    _conn = connect(config.DB_PATH)
    try:
        _keys, _matrix = ensure_index(_conn)
    finally:
        _conn.close()
    _model = ST_EMBED_MODEL if config.EMBED_BACKEND == "st" else EMBED_MODEL
    print(f"dense index ready: {len(_keys)} slices @ {_DEFAULT_STEM}.npy ({_model})")
