"""Hugging Face transformers backend (config.LLM_PROVIDER = "hf").

For the public Space, which has no Ollama. On a ZeroGPU host a real GPU exists
only inside a `@spaces.GPU` function, so generation runs there, and the weights
are placed on `cuda` once at startup, as that host requires. Anywhere else the
decorator is absent and the same code runs on whatever device torch finds —
which is how it is measured locally (evals/RESULTS.md §12).

torch and transformers are imported in this module and nowhere else, so the
library, the tests and the Ollama path never need them (`pip install .[space]`).
Like every backend this is a plain str->str `llm`: the citation check, the
honesty tier and the action ladder still run over its output, in code.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from legal_agent import config

try:            # must be imported before torch on a ZeroGPU host
    import spaces
except ImportError:
    spaces = None

# The same cap as the Ollama path (ollama_llm.num_predict), so the measured
# model and the deployed one stop at the same length.
MAX_NEW_TOKENS = 2048
# ZeroGPU admits a call against this, not against the time it ends up using: a
# visitor whose remaining daily quota is below it is refused outright
# (unauthenticated 2 min/day, free account 5), and a call that runs past it is
# aborted. Measured on the Space: 593 tokens in 15.6 s from a 2,703-token
# prompt, 38 tok/s (RESULTS.md §12). 60 s covers the 2,048-token cap (~54 s)
# and the longest answer measured, 1,574 tokens (~41 s) — and gives an
# unauthenticated visitor two answers a day where 90 s gave one.
GPU_SECONDS = 60

_LOADED: dict[str, tuple] = {}


def preload(model_id: str | None = None, **from_pretrained) -> tuple:
    """Load tokenizer + weights once per process. On ZeroGPU this must run at
    import time of the app, outside any request; elsewhere it is just a cache.
    `from_pretrained` is passed through (a local measurement on an 8 GB card
    loads the same weights 4-bit)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_id = model_id or config.HF_MODEL
    if model_id in _LOADED:
        return _LOADED[model_id]
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if from_pretrained:
        model = AutoModelForCausalLM.from_pretrained(model_id, **from_pretrained)
    elif torch.cuda.is_available():     # True under ZeroGPU's startup emulation too
        model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16)
        model.to("cuda")
    else:
        model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float32)
    model.eval()
    _LOADED[model_id] = (tokenizer, model)
    return _LOADED[model_id]


def _visible(exc: Exception) -> Exception:
    """ZeroGPU hands the caller only the CLASS NAME of an exception raised in
    its GPU worker (the page read 「模型這次沒有執行('RuntimeError')」, 2026-10-21);
    the message reaches only the owner's container log. A `gr.Error` is the one
    kind it passes through whole, so the reason gets wrapped in one."""
    try:
        import gradio as gr
    except ImportError:
        return exc
    return gr.Error(f"{type(exc).__name__}: {exc}"[:300])


def _generate(prompt: str, model_id: str, temperature: float, max_new_tokens: int) -> str:
    try:
        return _generate_unguarded(prompt, model_id, temperature, max_new_tokens)
    except Exception as exc:
        raise _visible(exc) from exc


def _generate_unguarded(prompt: str, model_id: str, temperature: float, max_new_tokens: int) -> str:
    import torch

    tokenizer, model = _LOADED[model_id]
    # One user turn, the template's default system message — what Ollama's
    # /api/generate does with the same prompt string.
    enc = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        add_generation_prompt=True, return_dict=True, return_tensors="pt",
    ).to(model.device)
    sampling = (
        {"do_sample": True, "temperature": temperature}
        if temperature > 0
        # Greedy, and silence the checkpoint's own sampling defaults.
        else {"do_sample": False, "temperature": None, "top_p": None, "top_k": None}
    )
    start = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(
            **enc, max_new_tokens=max_new_tokens,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            **sampling,
        )
    new = out[0, enc["input_ids"].shape[1]:]
    # The container log is where GPU_SECONDS gets checked against the real speed.
    print(f"hf_llm: {len(new)} tokens in {time.perf_counter() - start:.1f}s "
          f"(prompt {enc['input_ids'].shape[1]})", flush=True)
    return tokenizer.decode(new, skip_special_tokens=True)


if spaces is not None:
    _generate = spaces.GPU(duration=GPU_SECONDS)(_generate)


def hf_llm(
    model_id: str | None = None,
    temperature: float = 0.2,
    max_new_tokens: int = MAX_NEW_TOKENS,
) -> Callable[[str], str]:
    """Build a str->str `llm` backed by in-process transformers weights.
    temperature: 0.2 like ollama_llm; graders pass 0.0 (greedy)."""
    model_id = model_id or config.HF_MODEL
    preload(model_id)

    def llm(prompt: str) -> str:
        return _generate(prompt, model_id, temperature, max_new_tokens)

    return llm
