"""Which side of the complaint the user is on. Deterministic, no LLM, no retrieval.

Measured 2026-08-15 (journal/2026-08-15-owner-noise-respondent.md): the whole
noise path — checklist, ladder, letter template — was written for the party
MAKING the complaint, and run against a respondent it recommended calling the
police and then mediating against the neighbour who had complained about him.

Run:  python -m pytest tests/test_stance.py -q
"""
from __future__ import annotations

from legal_agent.dialogue import triage
from legal_agent.dialogue.flow import (
    MAX_INTAKE_TURNS,
    SessionState,
    Stage,
    assumptions_block,
    handle_turn,
    missing_fields,
)
from legal_agent.dialogue.solution import (
    build_generic_ladder,
    build_respondent_ladder,
    build_solution_ladder,
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


# ── the ladder must not hand him the complainant's actions ───────────────────
class _Article:
    """Minimal stand-in for a retrieved Statute: the ladder reads only these three."""

    def __init__(self, statute_id: str, article_no: str, content: str) -> None:
        self.statute_id = statute_id
        self.article_no = article_no
        self.content = content


# Verbatim from the corpus.
_72 = _Article(
    "社會秩序維護法", "第72條",
    "有左列各款行為之一者，處新臺幣六千元以下罰鍰：三、製造噪音或深夜喧嘩，"
    "妨害公眾安寧者。",
)
_793 = _Article(
    "民法", "第793條",
    "土地所有人於他人之土地、建築物或其他工作物有瓦斯、蒸氣、臭氣、煙氣、熱氣、"
    "灰屑、喧囂、振動及其他與此相類者侵入時，得禁止之。但其侵入輕微，或按土地形狀、"
    "地方習慣，認為相當者，不在此限。",
)

_RESPONDENT_FACTS = {
    "noise_type": "半夜走路、關門的聲音,鄰居說太吵",
    "building_type": "公寓大廈(有管委會)",
    "actions_taken": "管委會來勸導過,警察來過一次",
}


def test_the_respondent_is_never_told_to_report_write_or_sue():
    """The measured defect: with these exact facts the complainant ladder marked
    管委會 and 報警 已嘗試 and recommended 調解 → 存證信函 → 民事訴訟 against the
    neighbour who had complained about him."""
    ladder = build_solution_ladder(
        _RESPONDENT_FACTS, retrieved=[_72, _793], stance="respondent"
    )
    # The note names what was withheld and why, so the banned words are checked
    # where an instruction would live: the rungs themselves, and the heading.
    instructions = ladder.header + "".join(
        r.title + r.what_it_is + r.next_step for r in ladder.rungs
    )
    for banned in ("報警", "110", "存證信函", "提起民事訴訟", "調解", "訴請排除侵害",
                   "打官司", "反映管理委員會"):
        assert banned not in instructions, banned


def test_the_respondent_gets_no_letter_template():
    ladder = build_solution_ladder(
        _RESPONDENT_FACTS, retrieved=[_72, _793], stance="respondent"
    )
    assert ladder.letter_template is None
    assert "請停止製造噪音" not in ladder.render()


def test_the_respondent_is_given_the_articles_own_conditions_verbatim():
    text = build_respondent_ladder(_RESPONDENT_FACTS, retrieved=[_72, _793]).render()
    assert "但其侵入輕微" in text and "不在此限" in text


def test_empty_beats_a_reversed_ladder_and_says_why():
    """Nothing is invented to have something to print — the note explains the
    absence instead."""
    ladder = build_respondent_ladder({"noise_type": "半夜關門"}, retrieved=[])
    assert "被投訴的一方" in ladder.note
    assert len(ladder.rungs) == 1 and ladder.rungs[0].key == "records"


def test_the_assumption_and_the_gaps_are_printed_together():
    """Printing only the gaps reads as 「you did not answer」; the assumption line
    is what lets the reader see the system in the wrong chair."""
    state = SessionState(problem_type="noise", stance="respondent",
                         collected_facts={"noise_type": "半夜關門"})
    block = assumptions_block(state)
    assert "被投訴的一方" in block
    assert "時段與頻率" in block and "受到的影響" in block   # labels, not raw keys
    assert "噪音類型" not in block                          # the one field he gave


def test_the_gap_list_is_empty_when_every_field_was_collected():
    state = SessionState(
        problem_type="noise", stance="complainant",
        collected_facts=dict.fromkeys(
            ("noise_type", "timing", "building_type", "impact", "evidence",
             "actions_taken"), "x"),
    )
    block = assumptions_block(state)
    assert "本次沒有的資訊" not in block
    assert "提出投訴的一方" in block


def test_the_gaps_do_not_come_from_asked_keys():
    """asked_keys is only updated in handle_turn, so on the default smart path it
    is empty — reading gaps off it would call every field never-asked."""
    state = SessionState(problem_type="noise", stance="respondent",
                         collected_facts={"noise_type": "半夜關門"})
    assert state.asked_keys == set()
    assert missing_fields(state) == ["timing", "building_type", "impact",
                                     "evidence", "actions_taken"]


# ── the generic path: four of the five triage domains live here ──────────────
def _generic(stance, domain="labor", retrieved=None):
    return build_generic_ladder(
        {"problem": "x"}, retrieved=retrieved or [], domain=domain, stance=stance,
    )


def test_the_generic_ladder_asserting_rungs_are_the_claimants():
    """All nine domain rungs plus negotiate/authority/litigation are phrased
    申請 / 申訴 / 檢舉 / 聲請 — 39bdece fixed the noise ladder only."""
    text = _generic("complainant").render()
    assert "向勞工局申訴/檢舉" in text and "民事訴訟" in text


def test_the_accused_employer_is_not_told_to_report_the_employee():
    keys = [r.key for r in _generic("respondent").rungs]
    for banned in ("labor_report", "negotiate", "authority", "litigation"):
        assert banned not in keys, banned


def test_an_unknown_stance_is_silenced_too_because_it_may_be_either():
    keys = [r.key for r in _generic(None).rungs]
    assert "labor_report" not in keys and "litigation" not in keys


def test_mediation_survives_with_two_way_wording():
    """The wording was the problem, not the step: both parties attend, either may
    apply, and applying is not an admission."""
    rungs = {r.key: r for r in _generic("respondent").rungs}
    assert "labor_mediate" in rungs
    assert "不等於承認對方的主張" in rungs["labor_mediate"].what_it_is


def test_the_traffic_rung_that_names_the_other_party_is_dropped():
    text = _generic("respondent", domain="traffic").render()
    assert "向對方投保的產險公司申請理賠" not in text


def test_the_claimants_letter_is_withheld_from_everyone_else():
    assert _generic("complainant", retrieved=[_72]).letter_template is not None
    assert _generic("respondent", retrieved=[_72]).letter_template is None
    assert _generic(None, retrieved=[_72]).letter_template is None


def test_the_missing_rungs_are_explained_rather_than_just_absent():
    note = _generic("respondent").note
    assert "刻意的" in note and "提出主張的一方" in note


def test_something_is_still_recommended_after_the_gate():
    """The flagged rung may have been one of the dropped ones."""
    ladder = _generic("respondent")
    assert sum(1 for r in ladder.rungs if r.recommended) == 1


def test_the_generic_deadline_is_relabelled_for_the_respondent():
    ladder = _generic("respondent", retrieved=[_197])
    rung = next(r for r in ladder.rungs if r.key == "other_side_deadline")
    assert "存證信函" not in rung.next_step        # the claimant's move
    assert "對方主張權利的期間" in rung.title


def test_the_generic_stance_question_is_asked_once_and_costs_no_intake_turn():
    state = SessionState()
    reply, state = handle_turn(state, "房東跟我說押金的事")
    assert reply == triage.STANCE_QUESTION_GENERIC
    assert state.intake_turns == 0 and state.stage is Stage.TRIAGE
    reply, state = handle_turn(state, "是他要跟我求償")
    assert state.stance == "respondent" and state.stage is Stage.INTAKE


def test_a_plain_claimant_sentence_is_not_asked():
    state = SessionState()
    reply, state = handle_turn(state, "網購買到瑕疵品,賣家不讓我退貨")
    assert reply != triage.STANCE_QUESTION_GENERIC
    assert state.stance == "complainant" and state.stage is Stage.INTAKE


def test_generic_respondent_phrasings():
    for text in ("房東說我違約要沒收押金", "客人投訴我的店", "對方要我賠修車費",
                 "收到存證信函說我欠款", "前員工告我"):
        assert triage.classify_stance(text) == "respondent", text


# Verbatim from the corpus.
_197 = _Article(
    "民法", "第197條",
    "因侵權行為所生之損害賠償請求權，自請求權人知有損害及賠償義務人時起，"
    "二年間不行使而消滅。",
)


def test_the_noise_ladder_now_surfaces_a_deadline_at_all():
    """It ignored `retrieved` entirely, so the one scenario with a hand-built
    ladder was the only one that never quoted a period."""
    ladder = build_solution_ladder(
        {"building_type": "公寓大廈"}, retrieved=[_197, _72]
    )
    assert ladder.rungs[0].key == "deadline"
    assert ladder.rungs[0].recommended is True
    assert "二年間不行使而消滅" in ladder.render()


def test_the_respondent_gets_the_period_as_the_other_sides_clock():
    ladder = build_solution_ladder(
        _RESPONDENT_FACTS, retrieved=[_197, _793], stance="respondent"
    )
    keys = [r.key for r in ladder.rungs]
    assert "other_side_deadline" in keys and "deadline" not in keys
    rung = ladder.rungs[keys.index("other_side_deadline")]
    assert "對方主張權利的期間" in rung.title
    assert rung.recommended is False        # it is not his to act on
    assert "二年間不行使而消滅" in rung.what_it_is


def test_the_respondents_period_is_not_turned_into_a_you_are_safe_verdict():
    ladder = build_solution_ladder(
        _RESPONDENT_FACTS, retrieved=[_197], stance="respondent"
    )
    # The note says the tool will NOT tell him 這樣不會被罰, so the check belongs
    # where a verdict would live: the rungs.
    rungs = "".join(r.title + r.what_it_is + r.next_step for r in ladder.rungs)
    assert "不會被罰" not in rungs and "沒事" not in rungs
    assert "時效已過" not in rungs


def test_the_complainants_ladder_is_untouched():
    text = build_solution_ladder(
        {"building_type": "公寓大廈", "actions_taken": "報過警"}, retrieved=[_72]
    ).render()
    assert "報警請警察到場" in text and "已嘗試" in text
    assert "民事訴訟" in text


def test_the_stance_line_only_mentions_noise_on_a_noise_case():
    assert "太吵" in triage.stance_line("respondent", "noise")
    rent = triage.stance_line("respondent", "other:rent")
    assert "被投訴的一方" in rent and "太吵" not in rent
