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
