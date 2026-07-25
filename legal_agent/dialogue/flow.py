"""Dialogue orchestrator — Stages 1-2 + the Stage 3 -> 4 pipeline bridge (spec §3).

    TRIAGE -> INTAKE -> READY_FOR_STAGE3   (Stages 1-2: rule-based, NEVER retrieve)
    advance_to_stage3(): retrieve ONCE -> LLM answer + gates (Stage 3) ->
                         solution ladder (Stage 4) -> combined PipelineResult

HARD INVARIANT (spec §3.3): retrieval is NOT imported or called in Stages 1-2.
This module imports only triage + intake at module load; stage3/solution (which
pull in the retrieval layer) are imported LAZILY inside advance_to_stage3.
handle_turn (Stages 1-2) never touches them.

Rule-based v1, no LLM in Stages 1-2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from legal_agent.dialogue import intake, triage


class Stage(str, Enum):
    TRIAGE = "TRIAGE"
    INTAKE = "INTAKE"
    READY_FOR_STAGE3 = "READY_FOR_STAGE3"


# The user must be able to end the questioning. Measured on the web demo, which
# has no such escape: four turns in, the visitor had answered everything they
# knew, the checklist still had gaps, and the result column was still blank.
DONE_WORDS = {"沒有了", "沒了", "就這樣", "夠了", "可以了", "沒有其他", "沒別的了",
              "不知道", "不清楚", "沒印象"}
DONE_PHRASES = ("請幫我分析", "請分析", "開始分析", "幫我看", "可以分析", "直接分析")
# Hard cap on intake turns — a checklist that cannot be completed must not trap
# the user inside it forever.
MAX_INTAKE_TURNS = 6


def wants_analysis(message: str) -> bool:
    """True when the user is asking to stop answering and get the diagnosis."""
    text = (message or "").strip()
    return text in DONE_WORDS or any(phrase in text for phrase in DONE_PHRASES)


@dataclass
class SessionState:
    stage: Stage = Stage.TRIAGE
    problem_type: str | None = None
    collected_facts: dict[str, str] = field(default_factory=dict)
    pending_questions: list[str] = field(default_factory=list)  # field keys asked last turn
    user_text: str | None = None   # the opening complaint (fed to Mechanism 5)
    asked_discriminating: bool = False  # the one ambiguous-case question was used
    intake_turns: int = 0          # answers taken so far (cap: MAX_INTAKE_TURNS)


@dataclass
class PipelineResult:
    """Combined Stage 3 + Stage 4 output surfaced to the caller."""
    answer: str                    # Stage 3 answer (may be 資料不足 / marginal-prefixed)
    honesty_tier: str              # Mechanism 3: normal | marginal | insufficient
    law_section: str | None        # Mechanism 4: 法律明文 (rank<=3)
    practice_section: str | None   # Mechanism 4: 實務見解 (rank 4-5)
    analysis_section: str | None   # Mechanism 4: 分析研判
    sections_ok: bool
    practice_disclaimer_ok: bool   # 實務見解 carries the 非法律明文 disclaimer
    verifications: list            # Mechanism 2: per-citation VerificationResult
    flagged_count: int
    premise_flag: bool             # Mechanism 5
    solution_text: str             # Stage 4: rendered escalation ladder
    solution_ladder: "SolutionLadder"
    stage3: "Stage3Result"         # full Stage 3 result, for deeper access


def _render_batch(batch: list[intake.IntakeField]) -> str:
    lines = ["請幫我確認幾個問題(可逐項分行回答):"]
    for i, f in enumerate(batch, 1):
        lines.append(f"{i}. {f.question}")
    # Say the exit exists. A visitor who has run out of facts should not have to
    # guess that 「請幫我分析」 works.
    lines.append("(不知道或問夠了,直接說「請幫我分析」即可)")
    return "\n".join(lines)


def _render_ready(state: SessionState) -> str:
    facts = "\n".join(f"  - {k}: {v}" for k, v in state.collected_facts.items())
    return (
        "資訊已收集完成(READY_FOR_STAGE3)。\n"
        "接下來進行分類與法條檢索(Stage 3)+ 解法階梯(Stage 4);請呼叫 advance_to_stage3()。\n"
        f"整理到的事實:\n{facts}"
    )


def handle_turn(state: SessionState, user_message: str) -> tuple[str, SessionState]:
    """Advance one turn (Stages 1-2 only). Returns (reply, state). Never retrieves."""
    if state.user_text is None:
        state.user_text = user_message   # remember the opening complaint (Mechanism 5)

    if state.stage is Stage.TRIAGE:
        result = triage.classify(user_message)
        if result.kind == "noise":
            state.problem_type = "noise"
            state.stage = Stage.INTAKE
            # The opening complaint already describes the noise — the generic
            # flow seeds `problem` with it, the noise flow did not, so a visitor
            # who wrote 「樓上小孩跑跳、拖椅子」 was asked 「噪音主要是什麼?」 four
            # turns running. Their own words are the best answer to that field.
            state.collected_facts.setdefault("noise_type", user_message)
            batch = intake.next_questions(state)
            state.pending_questions = [f.key for f in batch]
            return "好的,聽起來是住宅噪音問題。\n" + _render_batch(batch), state
        if result.kind == "other" or state.asked_discriminating:
            # Generic fallback (spec §3.4): non-noise problems get the shallow
            # intake instead of a dead end — the corpus covers far more than
            # noise now. Keep the finer other:* label when triage produced one.
            state.problem_type = result.problem_type or "generic"
            state.stage = Stage.INTAKE
            if state.collected_facts.get("problem") is None:
                # seed with the ORIGINAL complaint plus this turn's clarifying
                # reply (when they differ) — nothing the user typed is dropped
                parts = [p.strip() for p in (state.user_text, user_message) if p and p.strip()]
                state.collected_facts["problem"] = " / ".join(dict.fromkeys(parts))
            batch = intake.next_questions(state)
            state.pending_questions = [f.key for f in batch]
            # Triage's own note is shown when it has one — for a personal-safety
            # complaint it carries the 110 / 113 pointer, which matters more than
            # anything the pipeline will say two turns later.
            preface = f"{result.message}\n" if result.message else ""
            return preface + "好的,先幫我補齊幾個關鍵事實。\n" + _render_batch(batch), state
        state.asked_discriminating = True
        return result.question, state

    if state.stage is Stage.INTAKE:
        intake.record_answers(state, user_message)
        state.intake_turns += 1
        batch = intake.next_questions(state)
        # The user decides when the questioning ends — either by saying so, or by
        # hitting the turn cap. Whatever facts exist go to Stage 3; the honesty
        # tier already grades a thin retrieval honestly, which is a better answer
        # than an unfinishable questionnaire.
        stop = wants_analysis(user_message) or state.intake_turns >= MAX_INTAKE_TURNS
        if batch and not stop:
            state.pending_questions = [f.key for f in batch]
            return _render_batch(batch), state
        state.pending_questions = []
        state.stage = Stage.READY_FOR_STAGE3
        return _render_ready(state), state

    return "已在 READY_FOR_STAGE3;請呼叫 advance_to_stage3() 進入 Stage 3+4。", state


def advance_to_stage3(state: SessionState, llm=None, as_of_date=None, conn=None) -> PipelineResult:
    """Run the Stage 3 -> Stage 4 pipeline. Requires READY_FOR_STAGE3.

    Stage 3 retrieves EXACTLY ONCE and fires the gates; Stage 4 builds the
    escalation ladder from the same facts. stage3/solution are imported LAZILY so
    importing flow (Stages 1-2) never pulls in the retrieval layer (spec §3.3).
    """
    if state.stage is not Stage.READY_FOR_STAGE3:
        raise ValueError(f"Stage 3 requires READY_FOR_STAGE3, got {state.stage}")

    from legal_agent.dialogue import solution, stage3  # lazy: keep retrieval out of Stages 1-2

    s3 = stage3.run_stage3(
        state.collected_facts, llm=llm, as_of_date=as_of_date, conn=conn,
        user_text=state.user_text,
    )
    if state.problem_type == "noise":
        ladder = solution.build_solution_ladder(state.collected_facts, retrieved=s3.retrieved)
    else:
        ladder = solution.build_generic_ladder(state.collected_facts, retrieved=s3.retrieved)
    return PipelineResult(
        answer=s3.answer,
        honesty_tier=s3.honesty_tier,
        law_section=s3.law_section,
        practice_section=s3.practice_section,
        analysis_section=s3.analysis_section,
        sections_ok=s3.sections_ok,
        practice_disclaimer_ok=s3.practice_disclaimer_ok,
        verifications=s3.verifications,
        flagged_count=s3.flagged_count,
        premise_flag=s3.premise_flag,
        solution_text=ladder.render(),
        solution_ladder=ladder,
        stage3=s3,
    )
