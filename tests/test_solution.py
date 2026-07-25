"""Tests for the Stage 4 solution ladder (step 4c). Deterministic, no LLM.

Run:  python -m pytest tests/test_solution.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.dialogue.solution import build_solution_ladder  # noqa: E402

_COST_RANK = {"免費": 0, "低": 1, "中": 2, "高": 3}

APARTMENT = {"building_type": "公寓大廈,有管委會", "noise_type": "深夜喧嘩爭吵", "actions_taken": ""}
HOUSE = {"building_type": "透天厝,無管委會", "noise_type": "深夜喧嘩爭吵", "actions_taken": ""}


def _keys(ladder):
    return [r.key for r in ladder.rungs]


def test_apartment_includes_hoa_rung():
    assert "hoa" in _keys(build_solution_ladder(APARTMENT))


def test_house_omits_hoa_rung():
    ladder = build_solution_ladder(HOUSE)
    assert "hoa" not in _keys(ladder)
    assert "police" in _keys(ladder)   # the rest of the ladder remains


def test_litigation_is_last_and_cost_is_non_decreasing():
    for facts in (APARTMENT, HOUSE):
        ladder = build_solution_ladder(facts)
        assert ladder.rungs[-1].key == "litigation"       # sue last
        ranks = [_COST_RANK[r.cost] for r in ladder.rungs]
        assert ranks == sorted(ranks), f"cost not cheap->costly: {ranks}"


def test_epa_section9_note_is_present():
    ladder = build_solution_ladder(APARTMENT)
    assert "環保局" in ladder.note and "§9" in ladder.note


def test_recommended_is_first_rung_when_nothing_tried():
    ladder = build_solution_ladder(APARTMENT)
    recommended = [r for r in ladder.rungs if r.recommended]
    assert len(recommended) == 1 and recommended[0].key == "hoa"


def test_already_reported_marks_police_done_and_points_to_next():
    facts = {"building_type": "透天厝", "noise_type": "深夜喧嘩", "actions_taken": "已經報過警了,沒用"}
    ladder = build_solution_ladder(facts)
    police = next(r for r in ladder.rungs if r.key == "police")
    assert police.done is True                              # marked done
    recommended = [r for r in ladder.rungs if r.recommended]
    assert len(recommended) == 1 and recommended[0].key == "mediation"   # next rung highlighted


def test_costs_stay_qualitative_no_ntd():
    ladder = build_solution_ladder(APARTMENT)
    for r in ladder.rungs:
        assert r.cost in {"免費", "低", "中", "高"}   # no invented NT$ figures


def test_letter_template_is_clearly_a_template():
    ladder = build_solution_ladder(APARTMENT)
    assert ladder.letter_template and "範本" in ladder.letter_template
    assert "非法律意見" in ladder.letter_template


def test_render_contains_note_and_orders_rungs():
    text = build_solution_ladder(APARTMENT).render()
    assert "環保局" in text
    assert text.index("反映管理委員會") < text.index("民事訴訟")   # cheap before litigation


# ── Generic ladder: name the window, and say free help exists ────────────────
def _statute(sid):
    from legal_agent.data.models import Statute

    return Statute(sid, "第1條", "內容", "2020-01-01", None, "法律", "http://x")


def test_authority_rung_is_named_from_the_retrieved_statute():
    from legal_agent.dialogue.solution import build_generic_ladder

    labour = build_generic_ladder({}, retrieved=[_statute("勞動基準法")]).render()
    assert "勞工局" in labour and "勞資爭議調解" in labour

    consumer = build_generic_ladder({}, retrieved=[_statute("消費者保護法")]).render()
    assert "1950" in consumer

    rental = build_generic_ladder({}, retrieved=[_statute("租賃住宅市場發展及管理條例")]).render()
    assert "住宅" in rental and "調處" in rental


def test_authority_rung_falls_back_when_the_domain_is_unknown():
    from legal_agent.dialogue.solution import build_generic_ladder

    text = build_generic_ladder({}, retrieved=[_statute("民法")]).render()
    assert "主管機關申訴/檢舉" in text


def test_refusal_recommends_the_free_consultation_not_evidence_gathering():
    # When retrieval came back empty the user has just been told 「這個問題我的
    # 資料庫沒有涵蓋」 — pointing at 蒐證 as the next step answers nothing.
    from legal_agent.dialogue.solution import build_generic_ladder

    refused = build_generic_ladder({}, retrieved=[]).render()
    recommended = [line for line in refused.splitlines() if "建議下一步" in line]
    assert recommended and "法律扶助" in recommended[0]

    answered = build_generic_ladder({}, retrieved=[_statute("勞動基準法")]).render()
    recommended = [line for line in answered.splitlines() if "建議下一步" in line]
    assert recommended and "蒐證" in recommended[0]


def test_generic_ladder_offers_free_legal_help_before_litigation():
    from legal_agent.dialogue.solution import build_generic_ladder

    text = build_generic_ladder({}).render()
    assert "法律扶助" in text
    assert text.index("法律扶助") < text.index("民事訴訟")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
