"""The Space's model backend (dialogue/hf_llm.py) and how app.py falls back.

The generation test needs torch and fakes the weights; CI has no torch and
skips it. The real weights are exercised by the measurement in
evals/RESULTS.md §12, not here.

Run:  python -m pytest tests/test_hf_llm.py -q
"""
from __future__ import annotations

import subprocess
import sys

import pytest


def _config_under(env: dict) -> str:
    code = (
        "from legal_agent import config;"
        "print(config.LLM_PROVIDER, config.EMBED_BACKEND)"
    )
    clean = {k: v for k, v in __import__("os").environ.items()
             if k not in {"SPACES_ZERO_GPU", "LEGAL_AGENT_PROVIDER", "LEGAL_AGENT_EMBED"}}
    out = subprocess.run([sys.executable, "-c", code], env={**clean, **env},
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_a_zerogpu_host_picks_the_space_backends_and_nothing_else_changes():
    assert _config_under({}) == "ollama ollama"
    assert _config_under({"SPACES_ZERO_GPU": "true"}) == "hf st"
    # an explicit choice still wins on the Space
    assert _config_under({"SPACES_ZERO_GPU": "true", "LEGAL_AGENT_PROVIDER": "manual"}) == "manual st"


def test_space_quota_error_renders_the_no_model_page(monkeypatch):
    import app

    def quota(_prompt):
        raise RuntimeError("ZeroGPU quota exceeded")

    monkeypatch.setattr(app, "_SPACE_LLM", quota)
    text = app._space_llm("prompt")
    assert "「法律明文」" in text and "「分析研判」" in text   # three-section contract kept
    assert "ZeroGPU quota exceeded" in text
    assert "第" not in text.split("「分析研判」")[1]          # no citation invented on failure


def test_a_gpu_worker_error_reaches_the_page_with_its_message(monkeypatch):
    # ZeroGPU forwards only the class name of a worker exception unless it is a
    # gr.Error; the deployed page read 「模型這次沒有執行('RuntimeError')」.
    import app
    from legal_agent.dialogue import hf_llm

    def broken(*a):
        raise RuntimeError("No CUDA GPUs are available")

    monkeypatch.setattr(hf_llm, "_generate_unguarded", broken)
    monkeypatch.setattr(app, "_SPACE_LLM", lambda p: hf_llm._generate(p, "m", 0.0, 1))
    text = app._space_llm("prompt")
    assert "(RuntimeError: No CUDA GPUs are available)" in text     # no repr quotes


def test_analysis_llm_prefers_ollama_then_the_space_model_then_the_stub(monkeypatch):
    import app

    monkeypatch.setattr(app, "ollama_available", lambda: False)
    monkeypatch.setattr(app, "_SPACE_LLM", None)
    assert app._analysis_llm() is app._stub_llm
    monkeypatch.setattr(app, "_SPACE_LLM", lambda p: "x")
    assert app._analysis_llm() is app._space_llm


def test_generate_is_one_user_turn_greedy_at_zero_and_returns_only_new_tokens(monkeypatch):
    torch = pytest.importorskip("torch")
    from legal_agent.dialogue import hf_llm

    seen = {}

    class Enc(dict):
        def to(self, device):
            return self

    class Tok:
        pad_token_id = None
        eos_token_id = 0

        def apply_chat_template(self, messages, **kw):
            seen["messages"] = messages
            return Enc(input_ids=torch.tensor([[5, 6, 7]]))

        def decode(self, ids, skip_special_tokens):
            return "|".join(str(int(i)) for i in ids)

    class Model:
        device = "cpu"

        def generate(self, **kw):
            seen["kw"] = kw
            return torch.tensor([[5, 6, 7, 8, 9]])

    monkeypatch.setitem(hf_llm._LOADED, "fake", (Tok(), Model()))
    monkeypatch.setattr(hf_llm, "preload", lambda model_id=None: None)
    out = hf_llm.hf_llm("fake", temperature=0.0)("問題")
    assert out == "8|9"
    assert seen["messages"] == [{"role": "user", "content": "問題"}]
    assert seen["kw"]["do_sample"] is False
    assert seen["kw"]["max_new_tokens"] == hf_llm.MAX_NEW_TOKENS
