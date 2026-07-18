"""Dense retrieval via local Ollama embeddings — the hybrid half that closes
BM25's vocabulary gap.

Measured motivation (2026-07-18 live simulation): the query 「雇主不給加班費」
cannot lexically reach 勞基法§24, whose text says 「延長工作時間之工資」 —
zero token overlap, BM25 rank >20. Embedding cosine between those two phrases
is 0.70: the semantic bridge BM25 cannot build.

Model choice is MEASURED, not assumed (4-query everyday-law benchmark,
target-article rank): nomic-embed-text failed outright on Traditional-Chinese
legal text (加班費→408, 網購→925, 遺產→1524 — with its task prefixes) and was
rejected; **bge-m3** took the same exam and won (網購 消保§19 → rank 1,
遺產 民法§1138 → rank 1, 押金 → 2, 加班費 None→37). See evals/RESULTS.md.

Same philosophy as every model in this project:
  * OPTIONAL — no Ollama, no index -> callers fall back to pure BM25.
  * Zero new Python dependencies — urllib (stdlib) + numpy (already shipped
    transitively with rank_bm25).
  * Fusion is RRF (reciprocal rank fusion): rank-based, no score-scale tuning,
    no learned weights — deterministic and explainable.

The corpus index (current slices only) is cached beside the DB:
    db/dense_bgem3.npy        float32 [N, 1024] L2-normalized
    db/dense_bgem3.keys.json  [[statute_id, article_no, effective_from], ...]
Rebuilt automatically when the corpus's current-slice key set changes.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np

from legal_agent import config

EMBED_MODEL = "bge-m3"
_DEFAULT_STEM = Path(config.DB_PATH).parent / "dense_bgem3"
_BATCH = 64


def embed_texts(
    texts: list[str],
    model: str = EMBED_MODEL,
    host: str | None = None,
    timeout: float = 120.0,
) -> np.ndarray:
    """Embed a list of texts via Ollama /api/embed. Returns L2-normalized
    float32 [len(texts), dim]. Raises on any transport/shape error — the
    CALLER decides whether that means fall back to BM25."""
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
    changed. Returns (keys, matrix). Raises when Ollama is unreachable AND no
    valid cache exists — callers fall back to BM25."""
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
