"""Optional 4th verification axis — semantic consistency via an injected LLM.

The three structural axes (exists / content-match / in-force) are pure code and
stay the project's core claim. This axis targets the error class they provably
cannot reach (evals/RESULTS.md "known unplanted gap"): SUBJECT SWAPS and
deleted preconditions — 「土地所有人得禁止之」 cited as 「承租人得禁止之」 has
the right article, right amounts, right dates, wrong law.

Design constraints, in order:
  1. OFF by default. `verify_answer(..., semantic_llm=None)` never calls this
     module; behaviour without a model is bit-for-bit the pure-code verifier.
  2. Conservative on every failure path. LLM unreachable, garbage output,
     missing fields -> (True, "") = NOT flagged. A checker that cries wolf on
     its own infrastructure errors gets turned off by its user.
  3. Injected, never constructed. `semantic_llm: Callable[[str], str]` follows
     the same seam as the reasoning model (config.LLM_PROVIDER) — tests inject
     fakes, the CLI wires a local Ollama, no key and no network by default.
  4. Judged by the same harness it joins: mutation.py grades this axis with
     seeded subject swaps (`--semantic`), so its catch rate is MEASURED per
     model, not assumed.
"""
from __future__ import annotations

import json
import re
from typing import Callable

# The claim sentence and the verbatim article both go in; the model answers a
# single yes/no. The reply is parsed, never shown verbatim to the user.
_PROMPT_TEMPLATE = (
    "你是法條引用檢查器。只依提供的逐字條文判斷,不得依記憶補充。\n"
    "逐字條文:\n{verbatim}\n\n"
    "答案中的主張:\n{claim}\n\n"
    "問題:此主張是否與條文「明確牴觸」?判斷標準:\n"
    "- 只有當主張把權利或義務歸給與條文明顯不同的主體(例如條文規範甲,主張卻說乙),"
    "或明確改寫條文的要件時,才算牴觸(consistent: false)。\n"
    "- 主張省略主體、未提及要件、或只是籠統摘要條文,一律視為一致(consistent: true)。\n"
    "- 金額與日期已由其他檢查器處理,不必考慮。\n"
    "只回傳 JSON,格式:{{\"consistent\": true 或 false, \"reason\": \"一句話\"}}"
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def semantic_consistent(
    claim_scope: str,
    verbatim: str,
    llm: Callable[[str], str],
) -> tuple[bool, str]:
    """Ask the injected model whether the claim matches the verbatim article.

    Returns (consistent, reason). EVERY failure path returns (True, "") —
    only an explicit, well-formed "consistent": false flags anything.
    """
    prompt = _PROMPT_TEMPLATE.format(verbatim=verbatim, claim=claim_scope)
    try:
        raw = llm(prompt)
    except Exception:
        return True, ""                      # infrastructure error ≠ bad citation

    match = _JSON_RE.search(raw or "")
    if not match:
        return True, ""
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return True, ""

    if parsed.get("consistent") is False:    # strict: only literal false flags
        reason = str(parsed.get("reason") or "主張與條文語意不符")
        return False, f"語意檢查:{reason}"
    return True, ""
