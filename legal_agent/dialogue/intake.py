"""Stage 2 — Structured intake (spec §3.2). Pre-designed 住宅噪音 checklist.

NO retrieval, NO LLM. Questions are asked 2-3 per turn (batching is UX-only and,
because this stage is BEFORE retrieval, has ZERO accuracy impact — spec §3.2).
Each field records a legally-relevant fact plus its rationale (why it matters).
v1 records answers positionally, one per line; the LLM upgrade will extract facts
from free-form replies.
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


def next_questions(session_state) -> list[IntakeField]:
    """Return the next batch of still-unanswered fields (2-3), or [] when the
    whole checklist is complete. Reads session_state.collected_facts (duck-typed
    to avoid a circular import with flow)."""
    for batch in NOISE_CHECKLIST:
        unanswered = [f for f in batch if f.key not in session_state.collected_facts]
        if unanswered:
            return unanswered
    return []


def record_answers(session_state, message: str) -> None:
    """Store the user's reply against the fields asked last turn
    (session_state.pending_questions), one answer per non-empty line, positionally.
    A missing line leaves its field unanswered (it is simply re-asked next turn)."""
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip()]
    for i, key in enumerate(session_state.pending_questions):
        if i < len(lines):
            session_state.collected_facts[key] = lines[i]
