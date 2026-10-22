"""Dialogue orchestrator — Stages 1-2 + the Stage 3 -> 4 pipeline bridge (spec §3).

    TRIAGE -> INTAKE -> READY_FOR_STAGE3   (Stages 1-2: rule-based, NEVER retrieve)
    advance_to_stage3(): retrieve ONCE -> LLM answer + gates (Stage 3) ->
                         solution ladder (Stage 4) -> combined PipelineResult

HARD INVARIANT (spec §3.3): retrieval is NOT imported or called in Stages 1-2.
This module imports only triage + intake at module load; stage3/solution (which
pull in the retrieval layer) are imported LAZILY inside advance_to_stage3.
Neither handle_turn nor handle_turn_smart touches them.

Two intake styles, same (reply, state) contract: `handle_turn` is rule-based and
needs no model; `handle_turn_smart` lets the model conduct the interview. An LLM
may run here — retrieval still may not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from legal_agent.dialogue import intake, triage

if TYPE_CHECKING:   # annotation only — a runtime import would drag the
    from legal_agent.dialogue.stage3 import Stage3Result  # retrieval layer into Stages 1-2


class Stage(str, Enum):
    TRIAGE = "TRIAGE"
    INTAKE = "INTAKE"
    READY_FOR_STAGE3 = "READY_FOR_STAGE3"


# The user must always be able to end the questioning.
DONE_WORDS = {"沒有了", "沒了", "就這樣", "夠了", "可以了", "沒有其他", "沒別的了",
              "不知道", "不清楚", "沒印象"}
DONE_PHRASES = ("請幫我分析", "請分析", "開始分析", "幫我看", "可以分析", "直接分析")
# Hard cap on intake turns. Retrieval on the opening words alone already reaches
# 19/20 of the wanted articles, so more questions buy paperwork, not accuracy.
MAX_INTAKE_TURNS = 3



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
    pending_key: str | None = None  # field the LAST turn asked directly (smart intake)
    asked_keys: set[str] = field(default_factory=set)  # never ask the same field twice
    # Which side of the complaint the user is on — "complainant" | "respondent" |
    # None. Inferred where the sentence says it, asked once where it does not,
    # and re-read on every later turn so the user can simply say it is the other
    # way round. None is a real value and renders as an UNCONFIRMED assumption.
    stance: str | None = None
    asked_stance: bool = False


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
    stage3: Stage3Result         # full Stage 3 result, for deeper access
    # The two things the reader cannot otherwise see: which seat this answer
    # was written for, and which checklist fields it never got. Printing only
    # the gaps reads as 「you did not answer」; printing the assumption is what
    # lets him see the system sitting in the wrong chair.
    assumptions_text: str = ""
    # False when the model returned nothing. A blank answer must never be shown
    # under a confident tier — see stage3.MODEL_EMPTY_TEXT.
    model_output_ok: bool = True


def _render_batch(batch: list[intake.IntakeField]) -> str:
    """ONE question, phrased as a question (not a numbered form), plus the exit."""
    if not batch:
        return ""
    lines = [batch[0].question]
    lines.append("(不知道就說「不知道」;想直接看結果就說「請幫我分析」)")
    return "\n".join(lines)


def _render_ready(state: SessionState) -> str:
    facts = "\n".join(
        f"  - {intake.FIELD_LABELS.get(k, k)}:{v}" for k, v in state.collected_facts.items()
    )
    return f"資訊已收集完成,接下來檢索相關法條並整理處理步驟。\n整理到的事實:\n{facts}"


def _questions_ahead(state: SessionState) -> str:
    """How many questions are coming, counted, not promised: the deposit visitor
    was told 「再問一件事就好」 and then asked three."""
    fields = [f for batch in intake.checklist_for(state.problem_type) for f in batch]
    left = sum(1 for f in fields
               if f.key not in state.collected_facts and f.key not in state.asked_keys)
    left = min(left, MAX_INTAKE_TURNS)
    return "再問一件事就好——" if left <= 1 else f"最多再問{'兩三'[left - 2]}件事——"


def _seed_key(problem_type: str | None) -> str:
    """The field the opening complaint answers — the first one in that domain's
    checklist. Their own words beat asking 「發生了什麼事?」 right after they said."""
    return intake.checklist_for(problem_type)[0][0].key


def _update_stance(state: SessionState, message: str) -> None:
    """Read the seat off this turn's words; keep the old one when it says nothing.

    Called on EVERY turn on purpose — 「不是,是我被投訴」 three turns in has to be
    able to flip it, and that sentence is the whole correction mechanism.
    """
    stance = triage.classify_stance(message)
    if stance is not None:
        state.stance = stance


def _read_stance_reply(state: SessionState, message: str) -> None:
    """The turn right after the stance question may answer it by position
    (「前者」); any other turn may not."""
    if state.stance is None:
        state.stance = triage.classify_stance_reply(message)


def _enter_noise_intake(state: SessionState, user_message: str) -> tuple[str, SessionState]:
    """Move into the noise checklist, seeding it with the user's own words."""
    state.problem_type = "noise"
    state.stage = Stage.INTAKE
    # The opening complaint already describes the noise; don't ask for it again.
    state.collected_facts.setdefault("noise_type", state.user_text or user_message)
    ahead = _questions_ahead(state)
    batch = intake.next_questions(state)[:1]
    state.pending_questions = [f.key for f in batch]
    state.asked_keys.update(state.pending_questions)
    return (
        triage.stance_line(state.stance, state.problem_type) + "\n"
        + f"了解,住宅噪音的問題。{ahead}\n" + _render_batch(batch)
    ), state


def _enter_generic_intake(state: SessionState, user_message: str,
                          label: str | None, message: str | None) -> tuple[str, SessionState]:
    """Move into the generic checklist (spec §3.4 fallback), seeded with their words."""
    state.stage = Stage.INTAKE
    seed = _seed_key(state.problem_type)
    if state.collected_facts.get(seed) is None:
        # seed with the ORIGINAL complaint plus this turn's clarifying
        # reply (when they differ) — nothing the user typed is dropped
        parts = [p.strip() for p in (state.user_text, user_message) if p and p.strip()]
        state.collected_facts[seed] = " / ".join(dict.fromkeys(parts))
    ahead = _questions_ahead(state)
    batch = intake.next_questions(state)[:1]
    state.pending_questions = [f.key for f in batch]
    state.asked_keys.update(state.pending_questions)
    # A human acknowledgement of what they described, then ONE question.
    # Triage's message is added only when it carries something actionable
    # (the personal-safety route's 110 / 113 pointer).
    opener = f"了解,{label}的問題。" if label else "了解。"
    preface = f"{message}\n" if message else ""
    return (
        preface + triage.stance_line(state.stance, state.problem_type) + "\n"
        + opener + ahead + "\n" + _render_batch(batch)
    ), state


def handle_turn(state: SessionState, user_message: str) -> tuple[str, SessionState]:
    """Advance one turn (Stages 1-2 only). Returns (reply, state). Never retrieves."""
    if state.user_text is None:
        state.user_text = user_message   # remember the opening complaint (Mechanism 5)
    _update_stance(state, user_message)

    if state.stage is Stage.TRIAGE:
        # The stance question was asked last turn; this turn's words answer it,
        # and the problem type was already settled before it was asked.
        if state.asked_stance and state.problem_type:
            _read_stance_reply(state, user_message)
            if state.problem_type == "noise":
                return _enter_noise_intake(state, user_message)
            return _enter_generic_intake(state, user_message, label=None, message=None)

        result = triage.classify(user_message)
        if result.kind == "noise":
            state.problem_type = "noise"
            # Ask ONCE, and only when the sentence does not say which side he is
            # on. This costs no intake turn: like the discriminating question it
            # is asked in TRIAGE, so MAX_INTAKE_TURNS is untouched.
            if state.stance is None and not state.asked_stance:
                state.asked_stance = True
                return triage.STANCE_QUESTION, state
            return _enter_noise_intake(state, user_message)
        if result.kind == "other" or state.asked_discriminating:
            # Generic fallback (spec §3.4): non-noise problems get the shallow
            # intake instead of a dead end — the corpus covers far more than
            # noise now. Keep the finer other:* label when triage produced one.
            state.problem_type = result.problem_type or "generic"
            # Same rule as the noise path, and the generic ladder needs it just as
            # badly: 申訴 / 檢舉 / 申請理賠 / 存證信函 / 提告 are all the asserting
            # party's moves. Asked in TRIAGE, so the intake budget is untouched.
            if state.stance is None and not state.asked_stance:
                state.asked_stance = True
                preface = f"{result.message}\n" if result.message else ""
                return preface + triage.STANCE_QUESTION_GENERIC, state
            return _enter_generic_intake(
                state, user_message, label=result.label, message=result.message,
            )
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
            batch = batch[:1]
            state.pending_questions = [f.key for f in batch]
            state.asked_keys.update(state.pending_questions)
            return _render_batch(batch), state
        state.pending_questions = []
        state.stage = Stage.READY_FOR_STAGE3
        return _render_ready(state), state

    return "資訊已收集完成,正在整理分析。", state


def handle_turn_smart(state: SessionState, user_message: str,
                      history: list[dict], intake_llm) -> tuple[str, SessionState]:
    """LLM-driven intake with the SAME (reply, state) contract as handle_turn.

    Used by both front ends; when no model is available callers fall back to
    `handle_turn`, which keeps the demo working on HF Spaces free CPU.

    NO retrieval here (spec §3.3): this only calls `intake_llm`.
    """
    from legal_agent.dialogue.smart_intake import field_keys, run_smart_intake_turn

    preface = ""
    # Every turn, not just the first: the model drives this interview, so the
    # only place a correction can land is the user's own next sentence.
    _update_stance(state, user_message)
    if state.user_text is None:
        state.user_text = user_message
        result = triage.classify(user_message)
        state.problem_type = (
            "noise" if result.kind == "noise" else (result.problem_type or "generic")
        )
        state.collected_facts.setdefault(_seed_key(state.problem_type), user_message)
        if result.urgent and result.message:
            preface = f"{result.message}\n"
        state.stage = Stage.INTAKE
        # Same question, same place in the conversation, both front ends. The
        # model drives this interview, so the scripted question is returned
        # directly rather than asked through it — and it costs no intake turn.
        if state.stance is None and not state.asked_stance:
            state.asked_stance = True
            return preface + triage.stance_question(state.problem_type), state
    elif state.asked_stance and state.intake_turns == 0:
        _read_stance_reply(state, user_message)

    # Keep triage's finer type, so each domain gets its own checklist.
    ptype = state.problem_type or "generic"
    turn = run_smart_intake_turn(
        history, state.collected_facts, intake_llm, ptype, state.pending_key,
    )
    state.collected_facts = turn.facts
    state.pending_key = turn.asked
    state.intake_turns += 1

    ready = (
        turn.ready
        or wants_analysis(user_message)
        or all(key in state.collected_facts for key in field_keys(ptype))
        or state.intake_turns >= MAX_INTAKE_TURNS
    )
    if ready:
        state.pending_questions = []
        state.stage = Stage.READY_FOR_STAGE3
    # The model's own last line is the natural bridge into the diagnosis
    # (「我了解了,開始幫你查」); callers that want a fact summary instead read
    # `state` and render their own, which is what the web demo does.
    return preface + turn.reply, state


def missing_fields(state: SessionState) -> list[str]:
    """Checklist fields this answer never got.

    `asked_keys` is NOT usable here: it is only updated inside `handle_turn`, so
    on the default smart path (ollama + SMART_INTAKE) it is empty and every field
    would read as never-asked. The checklist minus what was collected is the
    honest set either way.
    """
    from legal_agent.dialogue.smart_intake import field_keys

    ptype = state.problem_type or "generic"
    return [k for k in field_keys(ptype) if k not in state.collected_facts]


def assumptions_block(state: SessionState) -> str:
    """The seat this answer was written for, then the fields it never got.

    The gap list alone reads as 「you did not answer these」 and hides the
    system's own assumption; a page written for the wrong side must say so.
    """
    lines = [triage.stance_line(state.stance, state.problem_type)]
    missing = missing_fields(state)
    if missing:
        labels = "、".join(intake.FIELD_LABELS.get(k, k) for k in missing)
        lines.append(f"【本次沒有的資訊】{labels}——沒問到或沒答到,結論可能因此不同。")
    return "\n".join(lines)


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
        ladder = solution.build_solution_ladder(
            state.collected_facts, retrieved=s3.retrieved, stance=state.stance,
        )
    else:
        # The articles the ANSWER cited, so the letter and the deadline quote what the
        # case turns on rather than whatever headed the retrieval window.
        cited = tuple(
            (v.citation.statute_id, v.citation.article_no)
            for v in s3.verifications
            if getattr(v, "citation", None) is not None
        )
        ladder = solution.build_generic_ladder(
            state.collected_facts, retrieved=s3.retrieved, cited=cited,
            domain=intake.domain_of(state.problem_type), stance=state.stance,
        )
    return PipelineResult(
        answer=s3.answer,
        honesty_tier=s3.honesty_tier,
        law_section=s3.law_section,
        practice_section=s3.practice_section,
        analysis_section=s3.analysis_section,
        sections_ok=s3.sections_ok,
        practice_disclaimer_ok=s3.practice_disclaimer_ok,
        model_output_ok=s3.model_output_ok,
        verifications=s3.verifications,
        flagged_count=s3.flagged_count,
        premise_flag=s3.premise_flag,
        solution_text=ladder.render(),
        stage3=s3,
        assumptions_text=assumptions_block(state),
    )
