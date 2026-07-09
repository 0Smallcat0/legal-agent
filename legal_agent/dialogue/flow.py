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


@dataclass
class SessionState:
    stage: Stage = Stage.TRIAGE
    problem_type: str | None = None
    collected_facts: dict[str, str] = field(default_factory=dict)
    pending_questions: list[str] = field(default_factory=list)  # field keys asked last turn
    user_text: str | None = None   # the opening complaint (fed to Mechanism 5)


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
            batch = intake.next_questions(state)
            state.pending_questions = [f.key for f in batch]
            return "好的,聽起來是住宅噪音問題。\n" + _render_batch(batch), state
        if result.kind == "other":
            state.problem_type = result.problem_type
            return result.message, state
        return result.question, state

    if state.stage is Stage.INTAKE:
        intake.record_answers(state, user_message)
        batch = intake.next_questions(state)
        if batch:
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
    ladder = solution.build_solution_ladder(state.collected_facts, retrieved=s3.retrieved)
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
