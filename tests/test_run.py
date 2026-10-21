"""Tests for the interactive entry point (step 5c). Deterministic: a FAKE llm +
scripted input, no network, no Anthropic client.

Run:  python -m pytest tests/test_run.py -q
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from legal_agent import config, run
from legal_agent.data.database import connect, init_db
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.dialogue import stage3


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
            raise EOFError from None

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


def test_a_clean_verification_still_prints_and_states_what_it_did_not_check():
    """`_format_result` used to render the verification block ONLY when
    something was flagged, so a clean run showed nothing — and silence reads as
    endorsement. Four of eight already-decided rental disputes were reasoned
    the wrong way round with `flagged_count` 0 in every one of them."""
    from legal_agent.anti_hallucination.verifier import (
        Citation,
        VerificationResult,
        verification_status_line,
    )

    clean = VerificationResult(
        citation=Citation("社會秩序維護法第72條", "社會秩序維護法", "第72條"),
        exists=True, content_match=True, in_force=True,
        verbatim_source="…", flagged=False, reason="",
    )
    result = MagicMock(
        honesty_tier="normal", sections_ok=True,
        law_section="「法律明文」:x", practice_section="「實務見解」:x",
        analysis_section="「分析研判」:x", practice_disclaimer_ok=True,
        verifications=[clean], premise_flag=False, solution_text="ladder",
    )
    result.stage3.retrieved = ()
    result.stage3.related_judgments = ()

    text = run._format_result(result)

    assert "引用查核" in text, "a clean run must not render silence"
    assert "1 筆引用全數可回溯至資料庫" in text
    assert "沒有查核這些條文是否適用於你的處境" in text
    assert verification_status_line([clean]) in text


def test_the_web_and_the_cli_state_the_same_limits():
    """A limit stated on one surface only is a limit half-stated."""
    import app
    from legal_agent.anti_hallucination.verifier import VERIFIED_SCOPE_NOTE

    assert VERIFIED_SCOPE_NOTE in app._quiet_verification([])
    assert "引用查核" in app._quiet_verification([])


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
