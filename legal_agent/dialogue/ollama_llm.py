"""Local Ollama runtime backend — FREE, offline (config.LLM_PROVIDER = "ollama").

Talks to the Ollama HTTP API (default http://localhost:11434) using only the
Python standard library (urllib) — no extra dependency. Model + host come from
config. Because the whole system prompt is baked into the single prompt string,
this is a plain str->str `llm` like every other backend, and the five
anti-hallucination gates still run over its output.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from legal_agent import config


def ollama_available(host: str | None = None, timeout: float = 3.0) -> bool:
    """True if an Ollama server answers at `host` (used to fail fast with a helpful
    message before a conversation starts)."""
    base = (host or config.OLLAMA_HOST).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as resp:
            return getattr(resp, "status", 200) == 200
    except (urllib.error.URLError, OSError):
        return False


def ollama_llm(
    model: str | None = None,
    host: str | None = None,
    timeout: float = 180.0,
    fmt: str | dict | None = None,
    temperature: float = 0.2,
    num_predict: int = 2048,
) -> Callable[[str], str]:
    """Build a str->str `llm` backed by a local Ollama model.

    fmt: when set ("json" or a JSON schema), Ollama constrains the output to valid
    JSON — used by the intake so a small local model reliably returns the
    structured {reply, facts, ready} object instead of drifting into free prose.
    temperature: sampling temperature (default 0.2, the prior hard-coded value);
    graders/checkers pass 0.0 so repeated runs measure the model, not the dice.
    num_predict: generation cap. Without it a small model can ramble unboundedly
    on a long retrieval prompt — measured 2026-07-21: one golden case decoded
    7 472 tokens at 42 t/s and rode straight into the 180 s client timeout. A
    well-formed answer here is < 1 500 tokens; 2 048 caps the tail, ~50 s worst
    case, and a truncated answer still passes through the verifier honestly."""
    model = model or config.OLLAMA_MODEL
    base = (host or config.OLLAMA_HOST).rstrip("/")
    url = f"{base}/api/generate"

    def llm(prompt: str) -> str:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        if fmt is not None:
            payload["format"] = fmt
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:      # server died mid-session
            raise RuntimeError(f"呼叫 Ollama 失敗({url}):{exc}") from exc
        return data.get("response", "")

    return llm
