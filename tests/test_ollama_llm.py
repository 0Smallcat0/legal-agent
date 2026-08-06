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


def test_think_key_is_absent_unless_asked_for(monkeypatch):
    """A server or model that has never heard of `think` must see the old
    payload byte for byte."""
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp({"response": "ok"})

    monkeypatch.setattr(ol.urllib.request, "urlopen", fake_urlopen)
    ol.ollama_llm()("x")
    assert "think" not in captured["body"]

    ol.ollama_llm(think=False)("x")
    assert captured["body"]["think"] is False


def test_an_answer_lost_inside_the_think_phase_is_retried(monkeypatch):
    """qwen3:4b returned 0 chars of answer and 2 564 of thinking at the 2 048
    cap, and the pipeline rendered a fully-verified page with nothing on it.
    The retry is keyed on that signature, not on a list of model names."""
    calls = []

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(body)
        if "think" not in body:
            return _FakeResp({"response": "", "thinking": "嗯,讓我想想……",
                              "done_reason": "length"})
        return _FakeResp({"response": "法律明文……"})

    monkeypatch.setattr(ol.urllib.request, "urlopen", fake_urlopen)
    assert ol.ollama_llm(num_predict=2048)("x") == "法律明文……"
    assert len(calls) == 2
    assert calls[1]["think"] is False
    assert calls[1]["options"]["num_predict"] == 4096   # doubled: 2 048 truncated


def test_an_empty_answer_without_thinking_is_not_retried(monkeypatch):
    """An ordinary model returning nothing is a real failure, and stage3 already
    reports it loudly. Retrying it would only hide it behind a second wait."""
    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(json.loads(req.data.decode("utf-8")))
        return _FakeResp({"response": ""})

    monkeypatch.setattr(ol.urllib.request, "urlopen", fake_urlopen)
    assert ol.ollama_llm()("x") == ""
    assert len(calls) == 1


def test_a_server_that_rejects_think_keeps_the_first_answer(monkeypatch):
    """Older Ollama 400s on the key. The empty answer travels on unchanged
    rather than the call raising."""
    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data.decode("utf-8"))
        if "think" in body:
            raise ol.urllib.error.URLError("does not support thinking")
        return _FakeResp({"response": "", "thinking": "……"})

    monkeypatch.setattr(ol.urllib.request, "urlopen", fake_urlopen)
    assert ol.ollama_llm()("x") == ""


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
