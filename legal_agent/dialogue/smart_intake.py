"""LLM-driven intake — the 'intelligent' upgrade to Stages 1-2 (spec §3).

The rule-based triage/intake ask scripted questions and file answers positionally,
which feels robotic and mis-files free-form replies (e.g. it stored "醫院宿舍,
覺得很煩" as building_type). This module lets the runtime model DRIVE the intake:
it reads the conversation so far, replies naturally, asks its own follow-ups, and
extracts the structured facts the Stage-3 pipeline needs.

It NEVER retrieves or cites law — that stays in Stage 3 — so the single-retrieval
invariant (spec §3.3) is preserved. It collects exactly the same fields as the
rule-based checklist (intake.NOISE_CHECKLIST) so advance_to_stage3 is unchanged.

Pairs with a free/cheap provider (ollama) or the paid API — NOT manual mode, where
a per-turn paste would be unbearable (manual keeps the rule-based intake).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from legal_agent.dialogue.intake import GENERIC_CHECKLIST, NOISE_CHECKLIST

# problem_type -> checklist. The generic flow (spec §3.4) collects a thinner,
# domain-neutral fact set; both paths reuse the SAME checklists the rule-based
# intake asks from, so either intake hands Stage 3 an identical fact shape.
_CHECKLISTS = {"noise": NOISE_CHECKLIST, "generic": GENERIC_CHECKLIST}


def field_keys(problem_type: str = "noise") -> list[str]:
    checklist = _CHECKLISTS.get(problem_type, GENERIC_CHECKLIST)
    return [f.key for batch in checklist for f in batch]


def _field_spec(problem_type: str) -> str:
    checklist = _CHECKLISTS.get(problem_type, GENERIC_CHECKLIST)
    return "\n".join(
        f"- {f.key}: {f.question}  (為什麼問:{f.rationale})"
        for batch in checklist
        for f in batch
    )


# Shared prompt sections. The noise wording is IDENTICAL to the original
# noise-only prompt; generic only swaps the role line, the field spec, and the
# finish rule (four fields instead of six).
_PROMPT_RULES = (
    "【現在不要做的事】不要給法律意見、不要引用或猜任何法條、不要下結論——那是稍後"
    "檢索法條後才做的步驟。\n"
    "【要蒐集的事實(英文 key: 問題重點)】\n{field_spec}\n"
    "【怎麼問】一次最多問 1–2 題;先用一句話回應使用者剛說的,再自然地追問。要聽得懂"
    "模糊或不在選項內的回答(例如「醫院宿舍」是團體宿舍,既非一般公寓大廈也非透天,"
    "就照實記錄並在需要時追問有沒有管理單位;「很煩」是情緒不是事實,要追問實際影響)。"
    "使用者已經回答過的內容,務必記進 facts,絕對不要重複問同一個問題;"
    "「目前已知的事實」JSON 裡已有的欄位,不要再問,只問還缺的。\n"
    "【何時結束】當{n_fields}個欄位都大致問到、或使用者表示沒有更多資訊時,把 ready 設為 true。\n"
    "【輸出格式(務必嚴格遵守)】只輸出一個 JSON,放在 ```json 與 ``` 之間,前後不要有"
    "其他文字:\n"
    '```json\n{{"reply": "你要對使用者說的話(含追問)", '
    '"facts": {{{facts_example}}}, "ready": false}}\n```\n'
    "facts 只放你已經有把握的欄位(用上面的英文 key);還不知道的欄位就先不要放進去。"
)

_ROLE_LINES = {
    "noise": (
        "你是台灣「住宅噪音」法律諮詢的問診助理。你現在唯一的任務是【問診】——用自然、"
        "口語、有同理心的方式跟使用者對話,把處理噪音糾紛所需的關鍵事實問清楚。\n"
    ),
    "generic": (
        "你是台灣民生法律諮詢(租屋、勞資、消費、車禍、家事、鄰里等)的問診助理。你現在"
        "唯一的任務是【問診】——用自然、口語、有同理心的方式跟使用者對話,把處理這個"
        "法律問題所需的關鍵事實問清楚。\n"
    ),
}
_FACTS_EXAMPLES = {
    "noise": '"noise_type": "…", "timing": "…"',
    "generic": '"problem": "…", "goal": "…"',
}
_N_FIELDS_ZH = {4: "四", 6: "六"}


def build_system_prompt(problem_type: str = "noise") -> str:
    ptype = problem_type if problem_type in _CHECKLISTS else "generic"
    n = len(field_keys(ptype))
    return _ROLE_LINES[ptype] + _PROMPT_RULES.format(
        field_spec=_field_spec(ptype),
        n_fields=_N_FIELDS_ZH.get(n, str(n)),
        facts_example=_FACTS_EXAMPLES[ptype],
    )


# Backward-compatible name: the noise prompt, byte-identical to the original.
INTAKE_SYSTEM_PROMPT = build_system_prompt("noise")


@dataclass
class IntakeTurn:
    reply: str
    facts: dict       # cumulative known facts (english keys only)
    ready: bool


def _format_history(history: list[dict]) -> str:
    rows = []
    for m in history:
        who = "使用者" if m.get("role") == "user" else "助理"
        rows.append(f"{who}:{m.get('content', '')}")
    return "\n".join(rows)


def build_intake_prompt(history: list[dict], facts: dict, problem_type: str = "noise") -> str:
    known = json.dumps(facts, ensure_ascii=False) if facts else "{}"
    return (
        build_system_prompt(problem_type)
        + "\n\n===== 目前已知的事實(JSON) =====\n" + known
        + "\n\n===== 對話紀錄 =====\n" + _format_history(history)
        + "\n\n請根據以上,輸出下一步的 JSON(記得只輸出 ```json 區塊)。"
    )


_FENCED_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_ANY_BRACE = re.compile(r"\{.*\}", re.DOTALL)


def parse_intake_response(text: str, prev_facts: dict,
                          problem_type: str = "noise") -> IntakeTurn:
    """Lenient parse of the model's JSON. If no JSON is found (a small local model
    may mis-format), degrade to 'treat the text as the reply, keep asking' rather
    than crash. Only the active checklist's field keys are merged;
    previously-known facts persist."""
    raw = None
    m = _FENCED_JSON.search(text or "")
    if m:
        raw = m.group(1)
    else:
        m2 = _ANY_BRACE.search(text or "")
        raw = m2.group(0) if m2 else None

    obj = None
    if raw:
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            obj = None

    if not isinstance(obj, dict):
        return IntakeTurn(
            reply=(text or "").strip() or "可以再多說一點嗎?",
            facts=dict(prev_facts),
            ready=False,
        )

    allowed = set(field_keys(problem_type))
    facts = dict(prev_facts)
    new = obj.get("facts")
    if isinstance(new, dict):
        for k, v in new.items():
            if k in allowed and isinstance(v, str) and v.strip():
                facts[k] = v.strip()

    reply = obj.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        reply = "了解,我再確認幾個細節。"
    return IntakeTurn(reply=reply.strip(), facts=facts, ready=bool(obj.get("ready", False)))


def run_smart_intake_turn(history: list[dict], facts: dict, llm,
                          problem_type: str = "noise") -> IntakeTurn:
    """One intake turn: ask the model for its natural reply + fact extraction.
    NO retrieval here (spec §3.3) — this only calls the injected `llm`."""
    return parse_intake_response(
        llm(build_intake_prompt(history, facts, problem_type)), facts, problem_type,
    )
