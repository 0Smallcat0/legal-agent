"""Shared test configuration.

Dense retrieval is forced OFF for every test by default: CI has no Ollama and
no built index, and local runs must not silently depend on either (or slow
every retrieval call with an embedding round-trip). Tests that exercise the
hybrid path re-enable it explicitly and fake the dense layer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent import config  # noqa: E402


@pytest.fixture(autouse=True)
def _dense_off(monkeypatch):
    monkeypatch.setattr(config, "DENSE_RETRIEVAL", "off")


NOISE_FIXTURE = Path(__file__).with_name("fixtures") / "noise_corpus.json"


def load_noise_fixture(conn) -> tuple[int, int]:
    """The nine hand-verified 住宅噪音 articles, for an isolated test corpus.

    These used to live in `legal_agent/data/noise_seed.py` — 177 lines of
    production code whose only remaining caller was the test suite, the shipped
    corpus having been built from the official bulk XML since v2. The rows are
    the same, character for character; they are data now rather than code, and
    they load through `source_ingest`, so every fixture exercises the real
    ingest path instead of a parallel one maintained for tests.
    """
    from legal_agent.data.source_ingest import load_proposals

    return load_proposals(NOISE_FIXTURE, conn)
