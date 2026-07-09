"""Tests for the LLM-driven intake and its hand-off to the Stage 3->4 pipeline.

Deterministic: a FAKE llm (canned JSON for intake, canned 3-section answer for
Stage 3) + scripted input. No network.

Run:  python -m pytest tests/test_smart_intake.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent import run  # noqa: E402
from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.dialogue import smart_intake as si  # noqa: E402


def test_parse_extracts_fenced_json():
    txt = 'chatter\n```json\n{"reply":"你好嗎","facts":{"noise_type":"敲打聲"},"ready":false}\n```\ntail'
    t = si.parse_intake_response(txt, {})
    assert t.reply == "你好嗎"
    assert t.facts["noise_type"] == "敲打聲"
    assert t.ready is False


def test_parse_merges_prev_and_drops_unknown_keys():
    t = si.parse_intake_response(
        '{"reply":"ok","facts":{"timing":"晚上","bogus":"x"},"ready":true}',
        {"noise_type": "a"},
    )
    assert t.facts == {"noise_type": "a", "timing": "晚上"}   # bogus dropped, prev kept
    assert t.ready is True


def test_parse_falls_back_when_no_json():
    t = si.parse_intake_response("我只是閒聊沒有輸出 JSON", {"x": "y"})
    assert t.ready is False
    assert "閒聊" in t.reply
    assert t.facts == {"x": "y"}


def test_run_smart_intake_turn_calls_llm_once():
    calls = {"n": 0}

    def fake(_prompt):
        calls["n"] += 1
        return '```json\n{"reply":"再問一題","facts":{"noise_type":"敲打"},"ready":false}\n```'

    t = si.run_smart_intake_turn([{"role": "user", "content": "鄰居很吵"}], {}, fake)
    assert calls["n"] == 1
    assert t.facts["noise_type"] == "敲打"


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


def test_smart_conversation_reaches_stage3_and_4(real_conn):
    # The fake llm plays two roles, told apart by prompt content:
    #  - intake prompt (contains 問診助理): return ready=true with all fields
    #  - Stage-3 prompt: return a 3-section answer
    def fake_llm(prompt):
        if "問診助理" in prompt:
            return (
                '```json\n{"reply":"我了解了,開始幫你查","facts":{'
                '"noise_type":"深夜喧嘩製造噪音","timing":"晚上偶發",'
                '"building_type":"公寓大廈有管委會","impact":"睡眠受影響",'
                '"evidence":"有錄音","actions_taken":"報過警"},"ready":true}\n```'
            )
        return (
            "法律明文:依社會秩序維護法第72條。\n"
            "實務見解:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。(無)\n"
            "分析研判:僅供參考,建議先報警。"
        )

    inputs = iter(["鄰居半夜很吵,受不了"])

    def fake_input(prompt=""):
        try:
            return next(inputs)
        except StopIteration:
            raise EOFError

    outputs = []
    run.run_smart_conversation(fake_llm, real_conn, input_fn=fake_input, output_fn=outputs.append)

    text = "\n".join(outputs)
    assert "我了解了" in text                               # the model's natural reply surfaced
    assert "診斷結果" in text
    assert "法律明文" in text and "實務見解" in text and "分析研判" in text
    assert "報警" in text                                    # Stage 4 ladder rendered


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
