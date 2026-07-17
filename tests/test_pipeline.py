"""End-to-end pipeline tests (step 5a): Stages 1-2 -> READY -> Stage 3 + Stage 4.
Deterministic: a FAKE llm, no network, no API key, no Anthropic client.

Run:  python -m pytest tests/test_pipeline.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.anti_hallucination.honesty import INSUFFICIENT_TEXT  # noqa: E402
from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.dialogue import flow, stage3  # noqa: E402
from legal_agent.dialogue.flow import PipelineResult, SessionState, Stage, handle_turn  # noqa: E402
from legal_agent.retrieval import retriever  # noqa: E402

FAKE_ANSWER = (
    "法律明文:社會秩序維護法第72條。\n"
    "實務見解:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。(無)\n"
    "分析研判:僅供參考。"
)


@pytest.fixture
def real_conn(tmp_path):
    # isolated noise-corpus copy — tests must never write the live DB
    from legal_agent.data.noise_seed import load_noise_statutes

    db = tmp_path / "t.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    load_noise_statutes(conn)
    yield conn
    conn.close()


def _run_intake(monkeypatch, opening):
    """Drive Stages 1-2 to READY and return (state, retrieval spy)."""
    spy = MagicMock(side_effect=retriever.retrieve_scored)
    monkeypatch.setattr(retriever, "retrieve_scored", spy)
    s = SessionState()
    _, s = handle_turn(s, opening)
    _, s = handle_turn(s, "深夜喧嘩爭吵、製造噪音\n半夜,幾乎每天")
    _, s = handle_turn(s, "公寓大廈,有管委會\n睡眠受影響,很嚴重")
    _, s = handle_turn(s, "有錄音\n報過警,反映過管委會")
    return s, spy


def test_end_to_end_single_retrieval_stages_1_2_never_retrieve(real_conn, monkeypatch):
    s, spy = _run_intake(monkeypatch, "鄰居半夜很吵,受不了")
    assert s.stage == Stage.READY_FOR_STAGE3
    assert spy.call_count == 0                      # Stages 1-2 NEVER retrieved

    res = flow.advance_to_stage3(s, llm=lambda p: FAKE_ANSWER, conn=real_conn)
    assert spy.call_count == 1                      # EXACTLY ONE retrieval in the whole run

    assert isinstance(res, PipelineResult)
    assert FAKE_ANSWER in res.answer                # Stage 3 answer surfaced
    assert res.honesty_tier in ("normal", "marginal")
    assert res.law_section is not None and res.analysis_section is not None   # Mech 4 sections
    assert res.solution_text and "報警" in res.solution_text                   # Stage 4 ladder rendered


def test_empty_retrieval_pipeline_no_llm_no_key(real_conn, monkeypatch):
    # FIX 1 end-to-end: empty retrieval -> 資料不足, LLM never called, no client built.
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [])
    boom = MagicMock(side_effect=AssertionError("no client / no key in tests"))
    monkeypatch.setattr(stage3, "default_anthropic_llm", boom)
    s = SessionState(
        stage=Stage.READY_FOR_STAGE3,
        collected_facts={"noise_type": "深夜喧嘩", "building_type": "公寓大廈,有管委會"},
    )
    res = flow.advance_to_stage3(s, llm=None, conn=real_conn)   # llm=None
    assert res.answer == INSUFFICIENT_TEXT
    assert res.honesty_tier == "insufficient"
    assert boom.call_count == 0
    assert res.solution_text                                     # Stage 4 process ladder still offered


def test_wrong_premise_opening_surfaces_premise_flag(real_conn, monkeypatch):
    # FIX 2: the opening complaint is threaded through to Mechanism 5.
    s, _ = _run_intake(monkeypatch, "鄰居半夜走路有聲音,這構成恐嚇罪吧,我要告他")
    assert s.user_text == "鄰居半夜走路有聲音,這構成恐嚇罪吧,我要告他"   # stored at Stage 1
    res = flow.advance_to_stage3(s, llm=lambda p: FAKE_ANSWER, conn=real_conn)
    assert res.premise_flag is True


def test_advance_requires_ready(real_conn):
    with pytest.raises(ValueError):
        flow.advance_to_stage3(SessionState(), llm=lambda p: "x", conn=real_conn)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
