"""Local Ollama runtime backend — FREE, offline (config.LLM_PROVIDER = "ollama").

Talks to the Ollama HTTP API (default http://localhost:11434) using only the
Python standard library (urllib) — no extra dependency. Model + host come from
config. Because the whole system prompt is baked into the single prompt string,
this is a plain str->str `llm` like every other backend, and the five
anti-hallucination gates still run over its output.
"""
from __future__ import annotations

import contextlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable

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
    think: bool | None = None,
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
    case, and a truncated answer still passes through the verifier honestly.
    think: pass False to switch a reasoning model's <think> phase off. Left None
    the key is not sent at all, so servers and models that do not know it behave
    exactly as before. See the retry below for why None is not the same as False.
    """
    model = model or config.OLLAMA_MODEL
    think = config.OLLAMA_THINK if think is None else think
    base = (host or config.OLLAMA_HOST).rstrip("/")
    url = f"{base}/api/generate"

    def _call(prompt: str, think_flag: bool | None, cap: int) -> dict:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": cap},
        }
        if think_flag is not None:
            payload["think"] = think_flag
        if fmt is not None:
            payload["format"] = fmt
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def llm(prompt: str) -> str:
        try:
            data = _call(prompt, think, num_predict)
        except urllib.error.URLError as exc:      # server died mid-session
            raise RuntimeError(f"呼叫 Ollama 失敗({url}):{exc}") from exc
        answer = data.get("response", "")

        # A reasoning model can spend the ENTIRE generation budget inside its
        # <think> phase and return an empty answer. Measured 2026-08-06 on
        # qwen3:4b: response 0 chars, thinking 2 564 chars, done_reason
        # 「length」 — the pipeline then had a well-retrieved, fully-verified
        # page with nothing written on it. Diagnosed from the response rather
        # than from a list of model names, because the next thinking model will
        # not be on that list: an empty answer WITH thinking text is the
        # signature, and the retry disables thinking and doubles the cap
        # (2 048 was still short: think=False alone came back truncated at
        # done_reason 「length」; 4 096 finished at 「stop」).
        if not answer.strip() and (data.get("thinking") or "").strip() and think is None:
            # Suppressed: an older server or a model that rejects `think` leaves
            # the empty answer alone, which stage3 already reports loudly.
            with contextlib.suppress(urllib.error.URLError, OSError):
                answer = _call(prompt, False, num_predict * 2).get("response", "")
        return answer

    return llm
