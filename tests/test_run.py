"""Tests for the interactive entry point (step 5c). Deterministic: a FAKE llm +
scripted input, no network, no Anthropic client.

Run:  python -m pytest tests/test_run.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent import config, run  # noqa: E402
from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.dialogue import stage3  # noqa: E402


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


def test_scripted_conversation_reaches_stage3_and_4(real_conn, monkeypatch):
    # If a real client were built the test would fail loudly.
    monkeypatch.setattr(stage3, "default_anthropic_llm",
                        MagicMock(side_effect=AssertionError("no real client in tests")))

    lines = iter([
        "鄰居半夜很吵,受不了",          # opening -> triage: noise
        "深夜喧嘩爭吵、製造噪音",         # noise_type
        "半夜,幾乎每天",               # timing
        "公寓大廈,有管委會",           # building_type
        "睡眠受影響,很嚴重",           # impact
        "有錄音",                     # evidence
        "報過警,也反映過管委會",         # actions_taken -> READY -> Stage 3 + 4
    ])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:      # loop should end before this
            raise EOFError

    outputs = []
    fake_llm = lambda p: (
        "法律明文:依社會秩序維護法第72條。\n"
        "實務見解:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。(無)\n"
        "分析研判:僅供參考,建議先報警。"
    )

    run.run_conversation(fake_llm, real_conn, input_fn=fake_input, output_fn=outputs.append)

    text = "\n".join(outputs)
    assert "診斷結果" in text
    assert "法律明文" in text and "實務見解" in text and "分析研判" in text   # Mech 4 three sections
    assert "非法律明文" in text                        # 實務見解 disclaimer surfaced
    assert "報警" in text                              # Stage 4 ladder rendered


def test_placeholder_model_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")         # test the paid path's guard
    monkeypatch.setattr(config, "MODEL", config.MODEL_PLACEHOLDER)   # still the placeholder
    with pytest.raises(SystemExit) as exc:
        run.build_runtime_llm()
    assert exc.value.code == 2
    assert "模型" in capsys.readouterr().out            # clear message, no traceback


def test_missing_api_key_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setattr(config, "load_env", lambda: None)
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "MODEL", "claude-sonnet-5")          # model IS configured
    monkeypatch.setattr(config, "get_anthropic_api_key", lambda: None)
    with pytest.raises(SystemExit) as exc:
        run.build_runtime_llm()
    assert exc.value.code == 2
    assert config.ANTHROPIC_API_KEY_ENV in capsys.readouterr().out


def test_bad_as_of_exits_cleanly(monkeypatch, capsys):
    # --as-of validation happens before any client build.
    monkeypatch.setattr(run, "build_runtime_llm", MagicMock(side_effect=AssertionError("should not reach")))
    with pytest.raises(SystemExit) as exc:
        run.main(["--as-of", "2025/01/01"])
    assert exc.value.code == 2
    assert "YYYY-MM-DD" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
