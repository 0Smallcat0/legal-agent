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
def real_conn(tmp_path):
    # isolated noise-corpus copy — tests must never write the live DB
    from tests.conftest import load_noise_fixture

    db = tmp_path / "t.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)
    load_noise_fixture(conn)
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
    # decoupled from scoring (the default thresholds leave the marginal band
    # empty — see honesty.py): force the tier, test the prefix behaviour
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 50.0)])
    monkeypatch.setattr(stage3, "grade_honesty", lambda *a, **k: "marginal")
    res = run_stage3({"noise_type": "深夜"}, llm=lambda p: "這是模型的分析內容。", conn=None)
    assert res.honesty_tier == "marginal"
    assert res.answer.startswith(MARGINAL_PREFIX)


def test_empty_model_output_is_a_failure_not_a_confident_answer(monkeypatch):
    """A blank answer used to pass every gate. Measured 2026-08-06 swapping in
    qwen3:4b, a thinking model that spends the whole `num_predict` budget inside
    <think>: tier 「normal」, 0 flagged citations, and the reader got a green
    「充分」 bar over an empty page. The retrieved articles must survive — the
    deterministic half of the answer is still good — but nothing may claim the
    model said something."""
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 500.0)])
    res = run_stage3({"noise_type": "深夜"}, llm=lambda p: "   \n  ", conn=None)
    assert res.model_output_ok is False
    assert res.answer == stage3.MODEL_EMPTY_TEXT
    assert res.sections_ok is False
    assert res.retrieved == [_STUB]          # the law is still there to read
    assert res.flagged_count == 0


def test_unsegmented_answer_is_kept_and_labelled(monkeypatch):
    """Tolerate the shape, label the gap. `sections_ok` was computed and read by
    nobody, so an answer that ignored the three headings lost its guarantees
    silently — the reader could not tell verbatim law from model prose."""
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 500.0)])
    prose = "房東扣押金要有依據,請對照條文。"
    res = run_stage3({"noise_type": "深夜"}, llm=lambda p: prose, conn=None)
    assert res.model_output_ok is True       # it DID answer
    assert res.sections_ok is False          # just not in three sections
    assert stage3.UNSEGMENTED_NOTICE in res.answer
    assert prose in res.answer               # nothing thrown away


def test_lexical_noise_score_short_circuits_as_insufficient(monkeypatch):
    # a hit below the calibrated floor (6.0) is noise, not an answer: the
    # LLM must not run, the fixed 資料不足 text goes out (oos-01 leak fix)
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 3.89)])
    llm_spy = MagicMock(return_value="不該被呼叫")
    res = run_stage3({"noise_type": "漏水"}, llm=llm_spy, conn=None)
    assert res.honesty_tier == "insufficient"
    assert res.answer == INSUFFICIENT_TEXT
    assert llm_spy.call_count == 0


def test_normal_tier_has_no_prefix(monkeypatch):
    monkeypatch.setattr(retriever, "retrieve_scored", lambda *a, **k: [(_STUB, 250.0)])
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


class _Art:
    def __init__(self, sid, ano, content):
        self.statute_id, self.article_no, self.content = sid, ano, content


_S169 = _Art(
    "民法", "第169條",
    "由自己之行為表示以代理權授與他人，或知他人表示為其代理人而不為反對之表示者，"
    "對於第三人應負授權人之責任。",
)


def test_model_prose_is_moved_out_of_the_statute_section():
    """Measured over eight sessions: 4 of 30 bullets under 法律明文 were the model's
    own inference, and in the 業務 session backwards — §169 makes the COMPANY answer
    for holding the salesman out; the bullet told the reader HE was the agent."""
    answer = (
        "**法律明文**\n"
        "1. 由自己之行為表示以代理權授與他人，或知他人表示為其代理人而不為反對之表示者，"
        "對於第三人應負授權人之責任。\n"
        "2. 根據民法第169條，當初你與業務簽署維護合約時，你沒有表示反對，"
        "他們就把你視為代理人之一。\n\n"
        "**實務見解**\n(無)\n\n"
        "**分析研判**\n1. 你可以向公司主張。\n"
    )
    out = stage3._move_model_prose_out_of_statute_section(answer, [_S169])
    statute_part = out.split("**實務見解**")[0]
    assert "他們就把你視為代理人之一" not in statute_part
    assert "他們就把你視為代理人之一" in out.split("**分析研判**")[1]
    assert "對於第三人應負授權人之責任" in statute_part


def test_a_statute_section_emptied_by_the_move_is_rebuilt_from_the_corpus():
    """Leaving 「(無)」 would hide law that WAS retrieved behind the model's silence."""
    # Long enough to be judged: the check leaves runs under 14 characters alone, so a
    # short assertion under 法律明文 still slips through. No measured session produced
    # one — all four caught were full sentences — and the floor is what stops numbered
    # list markers and 「(無)」 being treated as prose.
    answer = (
        "**法律明文**\n"
        "1. 因為你當初沒有表示反對，所以公司大概要為這個業務簽的約負起全部的責任。\n\n"
        "**實務見解**\n(無)\n\n**分析研判**\n1. 建議蒐證。\n"
    )
    out = stage3._move_model_prose_out_of_statute_section(answer, [_S169])
    statute_part = out.split("**實務見解**")[0]
    assert "民法第169條" in statute_part
    assert "對於第三人應負授權人之責任" in statute_part


def test_insufficient_boilerplate_is_dropped_when_the_answer_has_analysis():
    """Measured on the 婚攝 session: the model wrote four numbered points off
    thirteen retrieved articles and still signed off with 「現有資料不足」. A reader
    who reaches that sentence stops reading."""
    answered = (
        "**分析研判**\n\n"
        "1. 你可以向承攬人請求損害賠償(民法第495條)。\n"
        "2. 對方說硬碟壞掉,依民法第226條不能免責。\n"
        "3. 保留合約、匯款紀錄與對話。\n\n"
        "現有資料不足,建議諮詢律師。"
    )
    out = stage3._drop_insufficient_boilerplate(answered)
    assert "現有資料不足" not in out
    assert "民法第495條" in out


def test_insufficient_boilerplate_survives_when_it_is_the_whole_answer():
    """Then it is a truthful report that the model had nothing to say, and the
    honesty tier is graded on it."""
    only = "現有資料不足,建議諮詢律師。"
    assert stage3._drop_insufficient_boilerplate(only) == only


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
