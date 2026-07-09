"""Manual, zero-cost runtime backend (spec §0.4 — an alternative to the paid API).

No API key and no local model. `run_stage3` hands the fully-assembled prompt to
the callable this builds; the callable PRINTS that prompt for you to copy into any
chat you already have (e.g. your Claude subscription), then reads the answer you
paste back from stdin. The whole system prompt is baked into the single prompt
string (stage3.build_model_input), so the model on the other side needs no setup,
and the five anti-hallucination gates still run verbatim over whatever you paste.

Select the backend in config.LLM_PROVIDER.
"""
from __future__ import annotations

from typing import Callable

# A lone line equal to this ends the pasted answer. Distinct enough to never
# appear as a line inside a real (Chinese) legal answer.
END_SENTINEL = "END"

_RULE = "═" * 60


def manual_llm(
    input_fn: Callable[..., str] = input,
    output_fn: Callable[[str], None] = print,
) -> Callable[[str], str]:
    """Build a str->str `llm` that round-trips through a human copy/paste.

    input_fn / output_fn are injected so this is fully testable with scripted
    input and captured output (defaults are the real stdin/stdout).
    """

    def llm(prompt: str) -> str:
        output_fn("\n" + _RULE)
        output_fn("↓ 複製以下整段 prompt,貼進你的 Claude 對話(或任何聊天)取得回答:")
        output_fn(_RULE)
        output_fn(prompt)
        output_fn(_RULE)
        output_fn(f"↑ 把模型的回答貼回這裡;貼完後,單獨一行輸入 {END_SENTINEL} 送出。")

        lines: list[str] = []
        while True:
            try:
                line = input_fn()
            except EOFError:      # Ctrl-Z (Win) / Ctrl-D (Unix) also ends input
                break
            if line is None:
                break
            if line.strip() == END_SENTINEL:
                break
            lines.append(line)
        return "\n".join(lines).strip()

    return llm
