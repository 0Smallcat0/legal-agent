"""Stage 2 — Structured intake (spec §3.2). Pre-designed 住宅噪音 checklist.

NO retrieval, NO LLM — this is the checklist the model-free path walks, and the
field set the model-driven intake (dialogue/smart_intake.py) extracts into. Each
field records a legally-relevant fact plus its rationale (why it matters).
Answers are filed by WHAT THEY SAY when a line unambiguously matches one open
field (route_answer), positionally otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntakeField:
    key: str
    question: str
    rationale: str   # the legal purpose this fact serves


# Batches of 2-3, presented and recorded in this order.
NOISE_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "noise_type",
            "噪音主要是什麼?(腳步/拖家具、深夜喧嘩爭吵、寵物吠叫、音響卡拉OK、裝修施工、冷氣/機械設備)",
            "分辨 社維法§72 / 噪音法§6(近鄰) vs 噪音法§9(特定場所)",
        ),
        IntakeField(
            "timing",
            "大多什麼時段?持續性還是偶發?",
            "深夜喧嘩(§72)、非持續(§6→警察)",
        ),
    ],
    [
        IntakeField(
            "building_type",
            "有管委會的公寓大廈,還是透天/無管委會?",
            "是否走 公寓大廈條例§16/§47",
        ),
        IntakeField(
            "impact",
            "對你的影響?(睡眠/健康/精神困擾,大概多嚴重)",
            "民法§195 情節重大",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有錄音/錄影或其他紀錄?",
            "各路徑的舉證",
        ),
        IntakeField(
            "actions_taken",
            "報過警嗎?反映過管委會/里長?對方知情、溝通過嗎?",
            "決定下一步升級",
        ),
    ],
]

ALL_FIELD_KEYS: list[str] = [f.key for batch in NOISE_CHECKLIST for f in batch]

# Generic fallback checklist (spec §3.4: non-noise problems get a shallower
# flow instead of a dead end). Two batches, four facts — enough for one good
# retrieval query, honest about being thinner than a scenario checklist.
GENERIC_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "problem",
            "發生了什麼事?對方是誰(例:房東、雇主、賣家、鄰居)?",
            "鎖定法律關係與爭點",
        ),
        IntakeField(
            "goal",
            # 停止 leads: the generic flow also carries personal-safety cases, and
            # offering 「拿回款項」 first to someone being stalked is tone-deaf.
            "你希望達成什麼結果?(例:要求對方停止、拿回款項、請求賠償)",
            "決定救濟方向",
        ),
    ],
    [
        IntakeField(
            "timeline",
            "事情何時發生?持續多久了?",
            "確認時效與事實時點",
        ),
        IntakeField(
            "actions_taken",
            "已經採取過哪些行動(例:溝通、存證、申訴)?",
            "決定下一步升級",
        ),
    ],
]


def _checklist(session_state) -> list[list[IntakeField]]:
    """noise keeps its hand-designed checklist; everything else gets the
    generic fallback (problem_type is duck-typed off the session state)."""
    if getattr(session_state, "problem_type", None) == "noise":
        return NOISE_CHECKLIST
    return GENERIC_CHECKLIST


def next_questions(session_state) -> list[IntakeField]:
    """Return the next batch of still-unanswered fields (2-3), or [] when the
    whole checklist is complete. Reads session_state.collected_facts (duck-typed
    to avoid a circular import with flow)."""
    for batch in _checklist(session_state):
        unanswered = [f for f in batch if f.key not in session_state.collected_facts]
        if unanswered:
            return unanswered
    return []


# Words that identify WHICH field an answer is about. Positional filing alone
# mis-files constantly in the model-free web demo: a visitor who answered
# 「公寓大廈有管委會」 had it stored as the previous question's answer and was then
# asked 「有管委會的公寓大廈,還是透天/無管委會?」 — the thing they had just said.
# Conservative by construction: a line is re-routed only when it matches exactly
# ONE still-unanswered field, otherwise the positional rule stands.
FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "building_type": ("公寓", "大廈", "透天", "管委會", "套房", "華廈", "宿舍", "社區"),
    "evidence": ("錄音", "錄影", "照片", "截圖", "分貝", "檢測", "沒有證據", "沒錄"),
    "actions_taken": ("報警", "報過警", "里長", "申訴", "檢舉", "調解", "溝通過",
                      "按門鈴", "反映"),
    "impact": ("睡不好", "失眠", "精神", "健康", "上班", "壓力", "受不了", "耳鳴"),
    "timing": ("半夜", "深夜", "凌晨", "白天", "晚上", "每天", "偶爾", "持續"),
    "goal": ("我想", "希望", "拿回", "要求", "請求", "賠償", "停止", "解約"),
    "timeline": ("多久", "個月", "半年", "一年", "已經"),
}


def route_answer(line: str, unanswered: set[str]) -> str | None:
    """The one unanswered field this line unambiguously answers, else None."""
    hits = [
        key for key in unanswered
        if any(word in line for word in FIELD_HINTS.get(key, ()))
    ]
    return hits[0] if len(hits) == 1 else None


def record_answers(session_state, message: str) -> None:
    """Store the user's reply against the fields asked last turn
    (session_state.pending_questions), one answer per non-empty line, positionally
    — except where a line unambiguously answers a DIFFERENT still-open field, in
    which case it is filed there instead. A missing line leaves its field
    unanswered (it is simply re-asked next turn)."""
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip()]
    facts = session_state.collected_facts
    open_keys = {
        f.key for batch in _checklist(session_state) for f in batch if f.key not in facts
    }

    positional: list[str] = []
    for line in lines:
        target = route_answer(line, open_keys)
        if target is not None:
            facts[target] = line
            open_keys.discard(target)
        else:
            positional.append(line)

    # The leftover lines pair with the still-open asked fields IN ORDER — each
    # list needs its own cursor, or a routed line silently eats a positional slot.
    cursor = 0
    for key in session_state.pending_questions:
        if key in facts:            # already filled by routing this turn
            continue
        if cursor >= len(positional):
            break
        facts[key] = positional[cursor]
        cursor += 1
