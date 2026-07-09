"""Tests for Stage 3 orchestration + Mechanisms 3/4/5 wiring (steps 4b, 4d, 5a).
Deterministic: a FAKE llm, no network, and NO Anthropic client construction.
(The Stage 3 -> 4 pipeline bridge is tested in test_pipeline.py.)

Run:  python -m pytest tests/test_stage3.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.anti_hallucination.honesty import INSUFFICIENT_TEXT, MARGINAL_PREFIX  # noqa: E402
from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.models import Statute  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.dialogue import stage3  # noqa: E402
from legal_agent.dialogue.stage3 import SYSTEM_PROMPT, run_stage3  # noqa: E402
from legal_agent.retrieval import retriever  # noqa: E402

NOISE_FACTS = {
    "noise_type": "鄰居深夜喧嘩爭吵、製造噪音",
    "timing": "半夜,幾乎每天,持續性",
    "building_type": "公寓大廈,有管委會",
    "impact": "睡眠受影響,精神很困擾,很嚴重",
    "evidence": "有錄音",
    "actions_taken": "報過警,也反映過管委會",
}
_STUB = Statute("民法", "第793條", "土地所有人於他人之土地...", "2009-07-23", None, "法律", "http://x")


@pytest.fixture
def real_conn():
    from legal_agent.config import DB_PATH
    from legal_agent.data.noise_seed import load_noise_statutes

    init_db(DB_PATH)
    conn = connect(DB_PATH)
    seed_source_hierarchy(conn)
    load_noise_statutes(conn)
    yield conn
    conn.close()


def test_retrieve_fires_exactly_once(real_conn, monkeypatch):
    spy = MagicMock(side_effect=retriever.retrieve_scored)   # the single retrieval call
    monkeypatch.setattr(retriever, "retrieve_scored", spy)
    run_stage3(NOISE_FACTS, llm=lambda p: "民法第793條規定得禁止喧囂侵入。", conn=real_conn)
    assert spy.call_count == 1


def test_llm_input_is_retrieval_first(real_conn):
    captured = {}

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return "民法第793條。"

    run_stage3(NOISE_FACTS, llm=fake_llm, conn=real_conn)
    assert SYSTEM_PROMPT in captured["prompt"]
    assert "檢索到的現行有效法條" in captured["prompt"]


def test_system_prompt_wires_three_section_mech4_and_mech5():
    for token in ("法律明文", "實務見解", "分析研判", "非法律明文", "糾正", "附和"):
        assert token in SYSTEM_PROMPT


def test_empty_retrieval_short_circuits_the_llm(real_conn, monkeypatch):
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [])
    llm_spy = MagicMock(side_effect=AssertionError("LLM must NOT be called when insufficient"))
    res = run_stage3(NOISE_FACTS, llm=llm_spy, conn=real_conn)
    assert res.honesty_tier == "insufficient"
    assert res.answer == INSUFFICIENT_TEXT
    assert llm_spy.call_count == 0
    assert res.verifications == []


def test_insufficient_short_circuit_binds_no_llm(real_conn, monkeypatch):
    # FIX 1: with llm=None AND empty retrieval, the default (real) LLM must NOT be
    # bound — the 資料不足 answer needs no API key / no client construction.
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [])
    boom = MagicMock(side_effect=AssertionError("default_anthropic_llm must NOT be built"))
    monkeypatch.setattr(stage3, "default_anthropic_llm", boom)
    res = run_stage3(NOISE_FACTS, llm=None, conn=real_conn)   # llm=None !
    assert res.answer == INSUFFICIENT_TEXT
    assert boom.call_count == 0


def test_marginal_tier_prepends_prefix(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 0.1)])
    res = run_stage3({"noise_type": "深夜"}, llm=lambda p: "這是模型的分析內容。", conn=None)
    assert res.honesty_tier == "marginal"
    assert res.answer.startswith(MARGINAL_PREFIX)


def test_normal_tier_has_no_prefix(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 99.0)])
    res = run_stage3({"noise_type": "深夜"}, llm=lambda p: "這是模型的分析內容。", conn=None)
    assert res.honesty_tier == "normal"
    assert MARGINAL_PREFIX not in res.answer


def test_faithful_citation_all_pass_not_flagged(real_conn):
    answer = "依社會秩序維護法第72條,製造噪音可處新臺幣一萬元以下罰鍰。"
    res = run_stage3(NOISE_FACTS, llm=lambda p: answer, conn=real_conn)
    assert answer in res.answer     # possibly prefixed if graded marginal
    assert any(s.statute_id == "社會秩序維護法" and s.article_no == "第72條" for s in res.retrieved), \
        f"§72 should have been retrieved; got {[(s.statute_id, s.article_no) for s in res.retrieved]}"
    v = next(x for x in res.verifications if x.citation.article_no == "第72條")
    assert v.exists and v.content_match and v.in_force and not v.flagged
    assert res.flagged_count == 0


def test_fabricated_citation_is_flagged(real_conn):
    res = run_stage3(NOISE_FACTS, llm=lambda p: "依噪音管制法第99條,住戶製造噪音應受處罰。", conn=real_conn)
    v = next(x for x in res.verifications if x.citation.article_no == "第99條")
    assert v.exists is False and v.flagged is True
    assert res.flagged_count >= 1


def test_premise_flag_surfaced_from_user_text(real_conn):
    res = run_stage3(
        NOISE_FACTS, llm=lambda p: "分析內容。", conn=real_conn,
        user_text="這一定告得成,他一定要賠",
    )
    assert res.premise_flag is True


def test_no_anthropic_client_constructed(real_conn, monkeypatch):
    boom = MagicMock(side_effect=AssertionError("must NOT build a real client in tests"))
    monkeypatch.setattr(stage3, "default_anthropic_llm", boom)
    run_stage3(NOISE_FACTS, llm=lambda p: "民法第793條。", conn=real_conn)
    assert boom.call_count == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
