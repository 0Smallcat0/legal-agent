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
    "【絕對不要做的兩件事】(1)不要把使用者剛講的話原封不動複述一遍;"
    "(2)不要反問使用者法律問題(例如「你覺得這樣合法嗎」「你認為誰有錯」)——"
    "那正是這個系統稍後要回答的事,問回去等於沒問。每一輪都要問到「還沒問到的欄位」"
    "裡的新資訊。\n"
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
    asked: str | None = None   # checklist key this turn asked about, when code did the asking


def _format_history(history: list[dict]) -> str:
    rows = []
    for m in history:
        who = "使用者" if m.get("role") == "user" else "助理"
        rows.append(f"{who}:{m.get('content', '')}")
    return "\n".join(rows)


def build_intake_prompt(history: list[dict], facts: dict, problem_type: str = "noise") -> str:
    known = json.dumps(facts, ensure_ascii=False) if facts else "{}"
    # Computed code-side: a small local model tracks 「what is still missing」 far
    # better when it is handed the list than when it has to diff two JSONs.
    missing = _missing_fields(facts, problem_type)
    missing_block = (
        "\n".join(f"- {f.key}: {f.question}" for f in missing)
        if missing else "(全部欄位都問到了 — 請把 ready 設為 true)"
    )
    return (
        build_system_prompt(problem_type)
        + "\n\n===== 目前已知的事實(JSON) =====\n" + known
        + "\n\n===== 還沒問到的欄位(這一輪只問這裡面的) =====\n" + missing_block
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


def _missing_fields(facts: dict, problem_type: str):
    """Checklist fields not yet filled, in checklist order."""
    checklist = _CHECKLISTS.get(problem_type, GENERIC_CHECKLIST)
    return [f for batch in checklist for f in batch if f.key not in (facts or {})]


def _asks_something(reply: str) -> bool:
    return any(mark in (reply or "") for mark in ("?", "？"))


# Questions that hand the legal judgement BACK to the user. Measured on the web
# demo's first model-driven turn: 「你覺得房東扣你的押金是公平的嗎?」 — it has a
# question mark and is not a repeat, so the earlier guard let it through, and the
# visitor is asked the exact thing they came to find out.
_OPINION_SEEKING = ("你覺得", "你認為", "合理嗎", "公平嗎", "對不對", "違法嗎",
                    "合法嗎", "有沒有錯", "該不該")


def _asks_for_a_verdict(reply: str) -> bool:
    return any(phrase in (reply or "") for phrase in _OPINION_SEEKING)


def _char_overlap(a: str, b: str) -> float:
    sa, sb = set(a or ""), set(b or "")
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _re_asks_a_filled_field(reply: str, facts: dict, problem_type: str) -> bool:
    """True when the reply asks about a field that is ALREADY answered.

    Measured on the web demo: the visitor wrote 「公寓大廈有管委會」, the field was
    filled, and the model's next question was 「…公寓大廈有管委會嗎?」. The reply
    asks something (so the question-mark guard passes) and is not a repeat of an
    earlier assistant line (so that guard passes too) — but it is a question the
    user has answered, which is the same insult by another route.
    """
    from legal_agent.dialogue.intake import FIELD_HINTS

    open_keys = [k for k in field_keys(problem_type) if k not in facts]
    filled_keys = [k for k in field_keys(problem_type) if k in facts]

    def mentions(key: str) -> bool:
        return any(word in reply for word in FIELD_HINTS.get(key, ()))

    return any(mentions(k) for k in filled_keys) and not any(mentions(k) for k in open_keys)


def _stalled(reply: str, history: list[dict]) -> bool:
    """True when this reply makes no progress: it asks nothing, or it is a
    near-copy of something the assistant already said.

    Measured on six lived sessions with the local 8B model: it restated the
    user's own facts back and asked 「你覺得這樣合法嗎?」 — the question the tool
    exists to answer — then repeated that same sentence for four turns straight.
    The model drives the intake, but code guarantees it moves.
    """
    if not _asks_something(reply) or _asks_for_a_verdict(reply):
        return True
    for message in history:
        if message.get("role") != "assistant":
            continue
        previous = message.get("content", "")
        if reply.strip() == previous.strip() or _char_overlap(reply, previous) > 0.85:
            return True
    return False


def _last_user_message(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") == "user":
            return (message.get("content") or "").strip()
    return ""


def run_smart_intake_turn(history: list[dict], facts: dict, llm,
                          problem_type: str = "noise",
                          pending_key: str | None = None) -> IntakeTurn:
    """One intake turn: ask the model for its natural reply + fact extraction.
    NO retrieval here (spec §3.3) — this only calls the injected `llm`.

    Two code-side guarantees around a small local model:
      * `pending_key` — the field the PREVIOUS turn asked about directly. If the
        model failed to extract it, the user's own words are filed there
        verbatim, exactly as the rule-based intake does. Answers do not vanish
        because the extractor had a bad turn.
      * a reply that makes no progress is replaced by the next missing question.
    """
    turn = parse_intake_response(
        llm(build_intake_prompt(history, facts, problem_type)), facts, problem_type,
    )
    answer = _last_user_message(history)
    if pending_key and pending_key not in turn.facts and answer:
        turn.facts[pending_key] = answer
    # Deterministic assist UNDER the model: if the user's words unambiguously
    # answer a still-open field, file them there even when the extractor missed
    # it. Measured on the web demo — the visitor wrote 「公寓大廈有管委會」 and the
    # next model question was 「有管委會的公寓大廈,還是透天/無管委會?」.
    if answer:
        from legal_agent.dialogue.intake import route_answer

        open_keys = {k for k in field_keys(problem_type) if k not in turn.facts}
        routed = route_answer(answer, open_keys)
        if routed is not None:
            turn.facts[routed] = answer
    if turn.ready:
        return turn
    missing = _missing_fields(turn.facts, problem_type)
    stalled = (
        _stalled(turn.reply, history)
        or _re_asks_a_filled_field(turn.reply, turn.facts, problem_type)
    )
    if missing and stalled:
        return IntakeTurn(reply=missing[0].question, facts=turn.facts,
                          ready=False, asked=missing[0].key)
    return turn
