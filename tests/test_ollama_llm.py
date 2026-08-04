"""Tests for the local Ollama backend. No real network: urlopen is monkeypatched.

Run:  python -m pytest tests/test_ollama_llm.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent import config, run  # noqa: E402
from legal_agent.dialogue import ollama_llm as ol  # noqa: E402


class _FakeResp:
    def __init__(self, payload, status=200):
        self._b = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_llm_posts_generate_and_returns_response(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp({"response": "測試回答"})

    monkeypatch.setattr(ol.urllib.request, "urlopen", fake_urlopen)
    llm = ol.ollama_llm(model="qwen2.5:7b", host="http://localhost:11434")
    assert llm("你好") == "測試回答"
    assert captured["url"].endswith("/api/generate")
    assert captured["body"]["model"] == "qwen2.5:7b"
    assert captured["body"]["stream"] is False
    assert captured["body"]["prompt"] == "你好"


def test_ollama_llm_includes_format_when_set(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp({"response": "{}"})

    monkeypatch.setattr(ol.urllib.request, "urlopen", fake_urlopen)
    ol.ollama_llm(fmt="json")("x")
    assert captured["body"]["format"] == "json"


def test_ollama_available_true_then_false(monkeypatch):
    monkeypatch.setattr(ol.urllib.request, "urlopen", lambda *a, **k: _FakeResp({"models": []}))
    assert ol.ollama_available("http://localhost:11434") is True

    def boom(*a, **k):
        raise ol.urllib.error.URLError("connection refused")

    monkeypatch.setattr(ol.urllib.request, "urlopen", boom)
    assert ol.ollama_available("http://localhost:11434") is False


def test_build_runtime_llm_ollama_dispatch(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr("legal_agent.dialogue.ollama_llm.ollama_available", lambda *a, **k: True)
    llm = run.build_runtime_llm()
    assert callable(llm)


def test_build_runtime_llm_ollama_down_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr("legal_agent.dialogue.ollama_llm.ollama_available", lambda *a, **k: False)
    with pytest.raises(SystemExit) as exc:
        run.build_runtime_llm()
    assert exc.value.code == 2
    assert "Ollama" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
