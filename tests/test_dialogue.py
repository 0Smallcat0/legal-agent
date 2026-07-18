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


def test_triage_non_noise_flags_generic_not_built():
    r = triage.classify("樓上漏水滲到我家天花板")
    assert r.kind == "other"
    assert r.problem_type == "other:leak"
    assert r.message and "尚未建立" in r.message


# ── Stage 2: intake ──────────────────────────────────────────────────────────
def _intake_state():
    return SessionState(stage=Stage.INTAKE, problem_type="noise")


def test_intake_first_batch_is_2_to_3():
    batch = intake.next_questions(_intake_state())
    assert 2 <= len(batch) <= 3
    assert [f.key for f in batch] == ["noise_type", "timing"]


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
        intake.record_answers(s, "\n".join(f"a_{f.key}" for f in batch))
    assert seen == 3
    assert set(s.collected_facts) == set(intake.ALL_FIELD_KEYS)
    assert intake.next_questions(s) == []    # complete


def test_record_answers_maps_lines_positionally():
    s = SessionState(pending_questions=["noise_type", "timing"])
    intake.record_answers(s, "腳步聲\n深夜,持續性")
    assert s.collected_facts == {"noise_type": "腳步聲", "timing": "深夜,持續性"}


# ── flow: full transcript ────────────────────────────────────────────────────
def test_flow_full_transcript_reaches_ready_and_collects_facts():
    facts = {
        "noise_type": "腳步聲、拖家具",
        "timing": "深夜,幾乎每天",
        "building_type": "有管委會的公寓大廈",
        "impact": "睡眠受影響,很嚴重",
        "evidence": "有錄音",
        "actions_taken": "報過警,也反映過管委會",
    }
    s = SessionState()
    _, s = handle_turn(s, "鄰居半夜很吵,受不了")
    assert s.stage == Stage.INTAKE and s.problem_type == "noise"
    assert s.pending_questions == ["noise_type", "timing"]
    _, s = handle_turn(s, f"{facts['noise_type']}\n{facts['timing']}")
    assert s.pending_questions == ["building_type", "impact"]
    _, s = handle_turn(s, f"{facts['building_type']}\n{facts['impact']}")
    assert s.pending_questions == ["evidence", "actions_taken"]
    _, s = handle_turn(s, f"{facts['evidence']}\n{facts['actions_taken']}")
    assert s.stage == Stage.READY_FOR_STAGE3
    assert s.collected_facts == facts


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
