"""sentence-transformers in a process of its own (config.EMBED_BACKEND = "st").

On a ZeroGPU Space the main process sees no GPU, and once torch has run a
model forward there — on CPU, with or without `spaces` loaded — CUDA's device
count is settled as 0 for that process. Every `@spaces.GPU` worker forked from
it then fails at its own start with 「No CUDA GPUs are available」, before any
of this project's code runs (the deployed Space did, 2026-10-21; reproduced
under WSL with the Space's package set, RESULTS.md §10). So the embedding
model lives in a separately started interpreter, and the main process only
trades text for float32 rows with it over a pipe — no torch op ever runs in it.

Protocol: one JSON line {"texts": [...], "batch_size": n} on stdin; the reply
is rows and dim as two little-endian uint32, then rows*dim float32.

    python -m legal_agent.retrieval.st_worker      # started by STProcess
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import threading

import numpy as np

_HEADER = struct.Struct("<II")


def write_matrix(stream, matrix: np.ndarray) -> None:
    matrix = np.ascontiguousarray(matrix, dtype=np.float32)
    stream.write(_HEADER.pack(*matrix.shape))
    stream.write(matrix.tobytes())
    stream.flush()


def read_matrix(stream) -> np.ndarray:
    header = stream.read(_HEADER.size)
    if len(header) < _HEADER.size:
        # The worker died (its traceback is on stderr, i.e. the container log);
        # embed_texts raises, and retrieval falls back to BM25 as without an index.
        raise RuntimeError("embedding process exited")
    rows, dim = _HEADER.unpack(header)
    body = stream.read(rows * dim * 4)
    if len(body) < rows * dim * 4:
        raise RuntimeError("embedding process exited mid-reply")
    return np.frombuffer(body, dtype=np.float32).reshape(rows, dim)


class STProcess:
    """The `.encode` of a SentenceTransformer, answered by the worker process.
    Started on first use; one request at a time (the startup index thread and
    visitors' queries share it)."""

    def __init__(self, cmd: list[str] | None = None):
        self._cmd = cmd or [sys.executable, "-m", "legal_agent.retrieval.st_worker"]
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def encode(self, texts, batch_size: int = 64, normalize_embeddings: bool = True) -> np.ndarray:
        assert normalize_embeddings, "the worker always L2-normalizes"
        line = json.dumps({"texts": list(texts), "batch_size": batch_size}, ensure_ascii=False)
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                self._proc = subprocess.Popen(
                    self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    env={**os.environ, "CUDA_VISIBLE_DEVICES": ""},
                )
            self._proc.stdin.write(line.encode("utf-8") + b"\n")
            self._proc.stdin.flush()
            return read_matrix(self._proc.stdout)


def main() -> None:
    out = sys.stdout.buffer
    sys.stdout = sys.stderr     # library prints go to the log, never into the pipe
    from sentence_transformers import SentenceTransformer

    from legal_agent.retrieval.dense import ST_EMBED_MODEL

    model = SentenceTransformer(ST_EMBED_MODEL, device="cpu")
    for line in sys.stdin.buffer:
        req = json.loads(line)
        vecs = model.encode(req["texts"], batch_size=req["batch_size"], normalize_embeddings=True)
        write_matrix(out, np.asarray(vecs, dtype=np.float32))


if __name__ == "__main__":
    main()
