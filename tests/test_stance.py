"""Which side of the complaint the user is on. Deterministic, no LLM, no retrieval.

Measured 2026-08-15 (journal/2026-08-15-owner-noise-respondent.md): the whole
noise path — checklist, ladder, letter template — was written for the party
MAKING the complaint, and run against a respondent it recommended calling the
police and then mediating against the neighbour who had complained about him.

Run:  python -m pytest tests/test_stance.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.dialogue import triage  # noqa: E402
from legal_agent.dialogue.flow import (  # noqa: E402
    MAX_INTAKE_TURNS,
    SessionState,
    Stage,
    handle_turn,
)


# ── inference ────────────────────────────────────────────────────────────────
def test_the_owners_own_sentence_is_read_as_the_respondent():
    assert triage.classify_stance(
        "目前我被鄰居投訴太吵了,不是鄰居太吵,這套系統如何幫助我保障自身權益?"
    ) == "respondent"


def test_respondent_phrasings():
    for text in (
        "鄰居投訴我家太吵",
        "被檢舉噪音,管委會來勸導過",
        "樓下說我半夜關門很大聲",
        "有人反映我這邊太吵",
    ):
        assert triage.classify_stance(text) == "respondent", text


def test_complainant_phrasings():
    for text in (
        "樓上很吵,每天半夜跑跳",
        "隔壁裝修吵到我睡不著",
        "鄰居的狗一直叫,受不了",
    ):
        assert triage.classify_stance(text) == "complainant", text


def test_respondent_wins_the_tie_because_the_complainant_list_is_the_loose_one():
    # 「鄰居說我太吵」 carries 鄰居 (complainant hint) and 說我太吵 at once.
    assert triage.classify_stance("鄰居說我太吵") == "respondent"


def test_a_sentence_that_says_neither_returns_none_rather_than_guessing():
    assert triage.classify_stance("有噪音問題想問") is None


# ── it is asked, not assumed ─────────────────────────────────────────────────
def test_an_unclear_opening_is_asked_which_side_before_the_checklist():
    state = SessionState()
    reply, state = handle_turn(state, "有噪音問題想問")
    assert reply == triage.STANCE_QUESTION
    assert state.stage is Stage.TRIAGE      # not yet in the checklist
    assert state.asked_stance is True


def test_the_stance_question_costs_no_intake_turn():
    """It is asked in TRIAGE, like the discriminating question — the intake
    budget is three turns and this change may not spend one of them."""
    state = SessionState()
    _, state = handle_turn(state, "有噪音問題想問")
    assert state.intake_turns == 0
    assert MAX_INTAKE_TURNS == 3


def test_the_answer_to_the_stance_question_lands_and_the_checklist_follows():
    state = SessionState()
    _, state = handle_turn(state, "有噪音問題想問")
    reply, state = handle_turn(state, "是有人投訴我")
    assert state.stance == "respondent"
    assert state.stage is Stage.INTAKE
    assert "被投訴的一方" in reply


def test_a_clear_opening_is_never_asked():
    state = SessionState()
    reply, state = handle_turn(state, "鄰居投訴我家太吵,管委會也來勸導過")
    assert reply != triage.STANCE_QUESTION
    assert state.asked_stance is False
    assert state.stance == "respondent"
    assert state.stage is Stage.INTAKE


# ── it is visible, and it can be corrected ───────────────────────────────────
def test_the_assumption_is_printed_on_the_page():
    state = SessionState()
    reply, _ = handle_turn(state, "樓上很吵,半夜一直跑跳")
    assert "【本次假設】" in reply
    assert "提出投訴的一方" in reply


def test_the_respondent_assumption_names_the_right_side():
    state = SessionState()
    reply, _ = handle_turn(state, "鄰居投訴我家太吵")
    assert "被投訴的一方" in reply


def test_a_later_sentence_flips_it():
    """The correction mechanism is the user's own next sentence — an assumption
    nobody can contradict is worse than no assumption."""
    state = SessionState()
    _, state = handle_turn(state, "樓上很吵,半夜一直跑跳")
    assert state.stance == "complainant"
    _, state = handle_turn(state, "不對,是鄰居投訴我")
    assert state.stance == "respondent"


def test_silence_does_not_flip_it():
    state = SessionState()
    _, state = handle_turn(state, "鄰居投訴我家太吵")
    _, state = handle_turn(state, "深夜十一點以後")
    assert state.stance == "respondent"


def test_the_unconfirmed_line_says_what_it_is_defaulting_to():
    line = triage.stance_line(None)
    assert "還沒確認" in line and "提出投訴的一方" in line
