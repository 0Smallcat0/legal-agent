"""Tests for dialogue Stages 1-2 (triage + intake + flow); deterministic, no LLM.
Includes the HARD no-retrieval invariant (spec §3.3).

Run:  python -m pytest tests/test_dialogue.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.dialogue import intake, triage  # noqa: E402
from legal_agent.dialogue.flow import SessionState, Stage, handle_turn  # noqa: E402


# ── Stage 1: triage ──────────────────────────────────────────────────────────
def test_triage_noise_complaint():
    r = triage.classify("鄰居三更半夜很吵,一直有腳步聲")
    assert r.kind == "noise"
    assert r.problem_type == "noise"


def test_triage_vague_returns_discriminating_question():
    r = triage.classify("我有惡鄰居")
    assert r.kind == "ambiguous"
    assert r.problem_type is None
    assert r.question and "?" in r.question   # it asks, it does not answer


def test_triage_non_noise_routes_to_the_generic_flow():
    r = triage.classify("樓上漏水滲到我家天花板")
    assert r.kind == "other"
    assert r.problem_type == "other:leak"
    assert r.label == "漏水"          # a human one-liner, not a tour of the plumbing
    assert r.message is None          # nothing actionable to say -> say nothing


def test_everyday_domains_are_recognised_instead_of_asked_about():
    # The web demo asked 「這是租屋、勞資、消費、車禍、家事,還是鄰里的問題?」 after a
    # visitor had plainly written 退租/押金/房東 — classify what was described.
    for complaint, expected in [
        ("我去年租的房子上個月退租,房東說牆壁有釘孔要扣我兩個月押金", "other:rent"),
        ("公司說我們是責任制,加班都沒有加班費", "other:labor"),
        ("網購買到瑕疵品,賣家不讓我退貨退款", "other:consumer"),
        ("我騎機車跟汽車擦撞,對方要我賠五萬", "other:traffic"),
        ("父親過世,兄弟姊妹要分遺產", "other:family"),
    ]:
        assert triage.classify(complaint).problem_type == expected, complaint
    # a genuinely vague opening still gets the one discriminating question
    assert triage.classify("我有惡鄰居").kind == "ambiguous"


def test_an_answer_is_filed_by_what_it_says_not_only_by_position():
    # Web-demo transcript: the visitor wrote 「公寓大廈有管委會」 and was then asked
    # 「有管委會的公寓大廈,還是透天/無管委會?」 — the thing they had just answered.
    state = SessionState()
    handle_turn(state, "樓上小孩每天晚上跑跳,受不了")      # -> noise intake
    _reply, state = handle_turn(state, "公寓大廈有管委會")
    assert state.collected_facts.get("building_type") == "公寓大廈有管委會"
    assert "building_type" not in state.pending_questions


def test_routing_leaves_ambiguous_lines_to_the_positional_rule():
    state = SessionState()
    handle_turn(state, "鄰居半夜很吵,受不了")
    state.collected_facts.pop("noise_type")        # as if the seed were absent
    state.pending_questions = ["noise_type", "timing"]
    _reply, state = handle_turn(state, "腳步聲、拖家具\n深夜,幾乎每天")
    assert state.collected_facts["noise_type"] == "腳步聲、拖家具"   # positional
    assert state.collected_facts["timing"] == "深夜,幾乎每天"        # routed


def test_user_can_end_the_questioning():
    from legal_agent.dialogue.flow import MAX_INTAKE_TURNS

    state = SessionState()
    _reply, state = handle_turn(state, "網購買到瑕疵品,賣家不讓我退貨")
    assert state.stage is Stage.INTAKE
    _reply, state = handle_turn(state, "請幫我分析")
    assert state.stage is Stage.READY_FOR_STAGE3   # the exit the web demo lacked

    # ...and an unanswerable checklist cannot trap the visitor forever
    state = SessionState()
    handle_turn(state, "網購買到瑕疵品,賣家不讓我退貨")
    for _ in range(MAX_INTAKE_TURNS):
        _reply, state = handle_turn(state, "不太確定")
    assert state.stage is Stage.READY_FOR_STAGE3


def test_personal_safety_beats_the_noise_keywords():
    # Measured on a lived session: 「前男友…半夜按我家電鈴…我很害怕」 hit the noise
    # keyword 半夜, so someone describing being stalked got the noise
    # questionnaire (「你住公寓大廈還是透天?」) and an answer about 深夜喧嘩.
    r = triage.classify("我跟前男友分手後他一直傳訊息、半夜按我家電鈴,還在我上班的地方等我,我很害怕")
    assert r.problem_type == "other:safety"
    assert r.message and "110" in r.message and "113" in r.message
    assert triage.classify("鄰居半夜對我大聲辱罵、威脅我").problem_type == "other:safety"


def test_being_someones_ex_is_not_a_safety_signal():
    # Regression: 前夫/前妻/前男友/分手 were safety keywords for one round, so a
    # divorced father asking about visitation was told 「請撥 110」 and had his
    # question answered out of 家暴法 — the model even called it 違反保護令罪.
    r = triage.classify("我跟前妻離婚,監護權判給她,她現在都不讓我見小孩")
    assert r.problem_type == "other:family"
    assert r.urgent is False
    # the harm words still route, with the 110/113 pointer
    stalked = triage.classify("前男友一直傳訊息,還跟蹤我,我很害怕")
    assert stalked.problem_type == "other:safety" and stalked.urgent is True


def test_triage_recognises_noise_described_as_behaviour():
    # How the complaint is actually typed — no 「噪音」, no 「吵」 anywhere.
    for complaint in ("樓上小孩每天晚上跑跳到十一二點,還會拖椅子",
                      "隔壁小孩半夜哭鬧尖叫",
                      "樓上一直甩門"):
        assert triage.classify(complaint).kind == "noise", complaint


# ── Stage 2: intake ──────────────────────────────────────────────────────────
def _intake_state():
    return SessionState(stage=Stage.INTAKE, problem_type="noise")


def test_intake_first_batch_is_2_to_3():
    batch = intake.next_questions(_intake_state())
    assert 2 <= len(batch) <= 3
    assert [f.key for f in batch] == ["noise_type", "timing"]


# What a person actually types for each noise field. Placeholder strings like
# 「a_evidence」 no longer work here on purpose: a line that answers nothing is
# now kept as narrative instead of being stamped with the pending field's label.
REALISTIC_ANSWERS = {
    "noise_type": "腳步聲跟拖椅子的聲音",
    "timing": "每天晚上十一點,持續半年了",
    "building_type": "公寓大廈,有管委會",
    "evidence": "有錄影,沒有分貝檢測",
    "actions_taken": "跟管委會反映過,也報過警",
    "impact": "睡不好,白天上班很累",
}


def test_intake_walks_all_batches_then_completes():
    s = _intake_state()
    seen = 0
    while True:
        batch = intake.next_questions(s)
        if not batch:
            break
        assert 2 <= len(batch) <= 3          # every turn asks 2-3
        seen += 1
        s.pending_questions = [f.key for f in batch]
        s.asked_keys.update(s.pending_questions)     # as flow.handle_turn does
        intake.record_answers(s, "\n".join(REALISTIC_ANSWERS[f.key] for f in batch))
    assert seen == 3
    assert set(s.collected_facts) >= set(intake.ALL_FIELD_KEYS)
    assert intake.next_questions(s) == []    # complete


def test_a_line_that_answers_nothing_is_not_given_the_pending_label():
    """Measured on the model-free web demo (the HF Spaces configuration): asked
    「你希望達成什麼結果?」 the visitor typed lease details, and every field ended
    up one place off — their goal 「我想拿回押金」 was shown as 已採取行動. Under-
    labelling is the safe error here; the words are kept verbatim either way."""
    s = SessionState(problem_type="generic", pending_questions=["goal"],
                     collected_facts={"problem": "退租後房東要扣押金"})
    s.asked_keys.add("goal")
    intake.record_answers(s, "租約到期才搬走,押金16000,有書面租約")
    assert "goal" not in s.collected_facts
    assert "押金16000" in s.collected_facts["problem"]      # nothing is dropped

    # …and the real goal, whenever it arrives, is filed correctly.
    s.pending_questions = ["actions_taken"]
    intake.record_answers(s, "我想拿回押金")
    assert s.collected_facts["goal"] == "我想拿回押金"
    assert "actions_taken" not in s.collected_facts


def test_record_answers_maps_lines_positionally():
    s = SessionState(pending_questions=["noise_type", "timing"])
    intake.record_answers(s, "腳步聲\n深夜,持續性")
    assert s.collected_facts == {"noise_type": "腳步聲", "timing": "深夜,持續性"}


# ── flow: full transcript ────────────────────────────────────────────────────
def test_flow_full_transcript_reaches_ready_and_collects_facts():
    facts = {
        "noise_type": "鄰居半夜很吵,受不了",   # seeded from the opening complaint
        "timing": "深夜,幾乎每天",
        "building_type": "有管委會的公寓大廈",
        "impact": "睡眠受影響,很嚴重",
        "evidence": "有錄音",
        "actions_taken": "報過警,也反映過管委會",
    }
    s = SessionState()
    _, s = handle_turn(s, "鄰居半夜很吵,受不了")
    assert s.stage == Stage.INTAKE and s.problem_type == "noise"
    # the opening complaint already answers 「噪音主要是什麼」 — seeded, not asked
    assert s.collected_facts["noise_type"] == "鄰居半夜很吵,受不了"
    assert s.pending_questions == ["timing"]
    _, s = handle_turn(s, facts["timing"])
    assert s.pending_questions == ["building_type"]      # ONE question per turn
    _, s = handle_turn(s, f"{facts['building_type']}\n{facts['impact']}")
    assert s.pending_questions == ["impact"]
    _, s = handle_turn(s, f"{facts['evidence']}\n{facts['actions_taken']}")
    # Three answers is the cap: the diagnosis is worth more than a complete form.
    assert s.stage == Stage.READY_FOR_STAGE3
    for key in ("noise_type", "timing", "building_type", "evidence", "actions_taken"):
        assert s.collected_facts[key] == facts[key]


def test_flow_vague_opening_then_clarify_to_noise():
    s = SessionState()
    reply, s = handle_turn(s, "我有惡鄰居")
    assert s.stage == Stage.TRIAGE           # did not advance; asked a question
    assert "?" in reply
    _, s = handle_turn(s, "主要是噪音,很吵")
    assert s.stage == Stage.INTAKE


# ── HARD INVARIANT (spec §3.3): retrieval never runs in Stages 1-2 ───────────
def test_no_retrieval_called_in_stages_1_2(monkeypatch):
    import legal_agent.retrieval.retriever as retriever_mod

    spy = MagicMock(side_effect=AssertionError("retrieval must NOT run in Stages 1-2"))
    monkeypatch.setattr(retriever_mod, "retrieve", spy)

    s = SessionState()
    for msg in ["鄰居半夜很吵", "腳步\n深夜", "公寓有管委會\n很嚴重", "有錄音\n報過警"]:
        _, s = handle_turn(s, msg)

    assert s.stage == Stage.READY_FOR_STAGE3   # a full triage+intake ran
    assert spy.call_count == 0                 # and retrieval was never called


def test_non_noise_problem_reaches_ready_via_generic_flow():
    # corpus v2: a deposit dispute must NOT dead-end in the noise-only triage.
    s = SessionState()
    r1, s = handle_turn(s, "退租時房東要扣我兩個月押金當違約金,合理嗎?")
    assert "噪音、漏水、占用空間" not in r1        # old noise-era phrasing is gone
    _, s = handle_turn(s, "租屋押金糾紛,房東拒還押金")   # clarification -> generic intake
    assert s.stage == Stage.INTAKE
    assert "押金" in s.collected_facts["problem"]   # opening complaint preserved
    _, s = handle_turn(s, "拿回押金")                 # goal
    _, s = handle_turn(s, "上個月退租\n口頭要求被拒") # timeline + actions_taken
    assert s.stage == Stage.READY_FOR_STAGE3
    assert set(s.collected_facts) == {"problem", "goal", "timeline", "actions_taken"}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
