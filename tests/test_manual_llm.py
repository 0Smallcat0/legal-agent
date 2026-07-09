"""Tests for the zero-cost manual (human-in-the-loop) runtime backend.

Deterministic: scripted input + captured output, no network, no API key.

Run:  python -m pytest tests/test_manual_llm.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent import config, run  # noqa: E402
from legal_agent.dialogue import stage3  # noqa: E402
from legal_agent.dialogue.manual_llm import END_SENTINEL, manual_llm  # noqa: E402


def _scripted(lines):
    it = iter(lines)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return fake_input


def test_manual_llm_roundtrips_pasted_answer():
    outputs = []
    llm = manual_llm(
        input_fn=_scripted(["法律明文:社維法第72條。", "分析研判:先報警。", END_SENTINEL]),
        output_fn=outputs.append,
    )
    answer = llm("PROMPT-BODY-機密")
    assert answer == "法律明文:社維法第72條。\n分析研判:先報警。"
    # the assembled prompt was shown to the human so they can copy it
    assert any("PROMPT-BODY-機密" in o for o in outputs)


def test_manual_llm_stops_at_sentinel_and_ignores_trailing():
    llm = manual_llm(
        input_fn=_scripted(["answer line", END_SENTINEL, "SHOULD-NOT-READ"]),
        output_fn=lambda _: None,
    )
    assert llm("p") == "answer line"


def test_manual_llm_empty_answer_on_immediate_eof():
    def eof_input(prompt=""):
        raise EOFError

    assert manual_llm(input_fn=eof_input, output_fn=lambda _: None)("p") == ""


def test_build_runtime_llm_manual_needs_no_key(monkeypatch):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "manual")
    # manual mode must NOT construct a real Anthropic client
    monkeypatch.setattr(
        stage3, "default_anthropic_llm",
        MagicMock(side_effect=AssertionError("manual must not build a client")),
    )
    llm = run.build_runtime_llm()
    assert callable(llm)


def test_build_runtime_llm_unknown_provider_exits(monkeypatch, capsys):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")   # not wired up yet
    with pytest.raises(SystemExit) as exc:
        run.build_runtime_llm()
    assert exc.value.code == 2
    assert "LLM_PROVIDER" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
