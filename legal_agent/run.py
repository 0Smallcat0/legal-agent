"""Interactive entry point — talk to the 住宅噪音 legal assistant.

    python -m legal_agent.run [--as-of YYYY-MM-DD]

Glue only: drives dialogue Stages 1-2 (intake) turn by turn, then on READY runs
Stage 3 (retrieve ONCE + LLM under retrieval-first + all gates) + Stage 4
(solution ladder) and prints the combined result. Two intake styles:
  * manual provider  -> rule-based checklist intake (run_conversation)
  * ollama/anthropic -> the model DRIVES the intake (run_smart_conversation)
The runtime backend is chosen by config.LLM_PROVIDER; a missing/unusable backend
exits with a clear message (no traceback).
"""
from __future__ import annotations

import sys
from datetime import date

from legal_agent import config
from legal_agent.dialogue import flow

_WELCOME = (
    "住宅噪音法律助理(個人用;非正式法律意見,重大爭議請諮詢律師)。\n"
    "請描述你的鄰居噪音困擾;我會先問幾個問題,再『一次』檢索法條並給出建議。\n"
    "(每行回答一題;輸入 quit 離開)"
)

_WELCOME_SMART = (
    "住宅噪音法律助理(個人用;非正式法律意見,重大爭議請諮詢律師)。\n"
    "用你自己的話描述鄰居噪音困擾就好——我會像諮詢一樣跟你聊、問幾個問題,\n"
    "問清楚後再『一次』檢索法條並給出建議。(輸入 quit 離開)"
)


def _die(message: str, code: int = 2) -> None:
    """Print a clear message and exit — SystemExit, so no traceback."""
    print(message)
    raise SystemExit(code)


def build_runtime_llm():
    """Return the runtime llm callable for config.LLM_PROVIDER, or exit CLEANLY
    with a helpful message (no traceback)."""
    config.load_env()
    provider = getattr(config, "LLM_PROVIDER", "anthropic")

    if provider == "manual":
        # Zero-cost human-in-the-loop: no model id and no API key required.
        from legal_agent.dialogue.manual_llm import manual_llm

        return manual_llm()

    if provider == "ollama":
        # Free local model. Needs the Ollama service running with a pulled model.
        from legal_agent.dialogue.ollama_llm import ollama_available, ollama_llm

        host = getattr(config, "OLLAMA_HOST", "http://localhost:11434")
        model = getattr(config, "OLLAMA_MODEL", "qwen2.5:7b")
        if not ollama_available(host):
            _die(
                f"⚠ 連不到本機 Ollama({host})。請先:\n"
                "  1) 安裝 Ollama:https://ollama.com/download\n"
                f"  2) 下載模型:ollama pull {model}\n"
                "  3) 確認服務在跑(安裝後通常自動啟動;或執行 `ollama serve`),再重跑本程式。\n"
                "  (或把 legal_agent/config.py 的 LLM_PROVIDER 改回 'manual'。)"
            )
        return ollama_llm()

    if provider == "anthropic":
        if not config.is_model_configured():
            _die(
                "⚠ 尚未設定模型。請編輯 legal_agent/config.py,將 MODEL 從占位符 "
                f"'{config.MODEL_PLACEHOLDER}' 改成真正的模型 id"
                "(例如 claude-sonnet-5 / claude-opus-4-8 / claude-haiku-4-5-20251001);"
                "或把 LLM_PROVIDER 改成 'manual' 用免費的手動模式。"
            )
        if not config.get_anthropic_api_key():
            _die(
                "⚠ 找不到 API 金鑰。請在環境變數或(被 gitignore 的).env 設定 "
                f"{config.ANTHROPIC_API_KEY_ENV}=你的金鑰;或把 LLM_PROVIDER 改成 'manual'。"
            )
        from legal_agent.dialogue.stage3 import default_anthropic_llm

        try:
            return default_anthropic_llm()
        except RuntimeError as exc:
            _die(f"⚠ 無法建立 Anthropic 客戶端:{exc}")

    _die(
        f"⚠ 未知的 LLM_PROVIDER:{provider!r}。目前支援:'manual' / 'ollama' / 'anthropic'。"
        "請改 legal_agent/config.py。"
    )


def _format_result(result) -> str:
    """Format a PipelineResult for the terminal, in the required order."""
    out = ["\n══════════════ 診斷結果 ══════════════"]

    # Mechanism 3 — honesty tier / label.
    if result.honesty_tier == "insufficient":
        out.append(f"【資料涵蓋】不足:{result.answer}")
    else:
        if result.honesty_tier == "marginal" and result.honesty_label:
            out.append(f"【提醒】{result.honesty_label}")
        # Mechanism 4 — three sections by 位階: 法律明文 / 實務見解 / 分析研判.
        if result.sections_ok:
            out.append("\n" + (result.law_section or ""))
            out.append("\n" + (result.practice_section or ""))
            out.append("\n" + (result.analysis_section or ""))
            if not result.practice_disclaimer_ok:
                out.append("\n⚠ 注意:實務見解段未標明「非法律明文」,請人工確認。")
        else:
            out.append("\n(模型未依「法律明文 / 實務見解 / 分析研判」三段格式,以下為原始回答)")
            out.append(result.answer)

    # Mechanism 2 — verification flags WITH the attached corpus verbatim.
    flagged = [v for v in result.verifications if v.flagged]
    if flagged:
        out.append("\n⚠ 引用查核(下列引用有疑慮,請對照條文原文):")
        for v in flagged:
            out.append(f"  - {v.citation.statute_id}{v.citation.article_no}:{v.reason}")
            if v.verbatim_source:
                out.append(f"    條文原文:{v.verbatim_source}")

    # Mechanism 5 — premise correction note.
    if result.premise_flag:
        out.append(
            "\n📝 註:你的描述似乎已先下了法律判斷(例如「構成某罪」「一定告得成」)。"
            "本工具以法律實際規定為準——若與你的預期不同,請以上方【法條依據】為主,"
            "必要時諮詢律師。"
        )

    # Stage 4 — solution ladder.
    out.append("\n" + result.solution_text)
    return "\n".join(out)


def run_conversation(llm, conn, as_of_date=None, input_fn=input, output_fn=print) -> None:
    """Rule-based intake loop (used in manual mode). `llm`, `conn`, `input_fn`,
    `output_fn` are injected so this is fully testable with a fake llm + scripted
    input."""
    state = flow.SessionState()
    output_fn(_WELCOME)
    while True:
        try:
            msg = input_fn("\n你 > ")
        except (EOFError, KeyboardInterrupt):
            output_fn("\n(結束對話)")
            return
        if msg is None:
            output_fn("\n(結束對話)")
            return
        if msg.strip().lower() in ("quit", "exit", "/quit", "/exit"):
            output_fn("(結束對話)")
            return

        reply, state = flow.handle_turn(state, msg)
        output_fn(reply)

        if state.stage is flow.Stage.READY_FOR_STAGE3:
            output_fn("\n(資訊已足夠——開始檢索法條並診斷;這一步只檢索一次)")
            result = flow.advance_to_stage3(state, llm=llm, as_of_date=as_of_date, conn=conn)
            output_fn(_format_result(result))
            return   # clinic-style: one diagnosis per session


_DONE_PHRASES = ("請幫我分析", "請分析", "開始分析", "幫我看", "可以分析")
_DONE_WORDS = {"沒有了", "沒了", "就這樣", "夠了", "可以了", "沒有其他", "沒別的了"}


def run_smart_conversation(llm, conn, as_of_date=None, input_fn=input,
                           output_fn=print, max_turns=12, intake_llm=None) -> None:
    """LLM-driven intake loop: the model DRIVES the conversation (natural replies,
    its own follow-ups, free-form fact extraction), then on ready runs the SAME
    Stage 3 -> 4 pipeline. No retrieval happens during intake (spec §3.3);
    retrieval fires exactly once inside advance_to_stage3. `intake_llm` (falls back
    to `llm`) can be a JSON-constrained backend so a small local model extracts
    facts reliably. Injectable IO for tests.
    """
    from legal_agent.dialogue.intake import ALL_FIELD_KEYS
    from legal_agent.dialogue.smart_intake import run_smart_intake_turn

    intake_llm = intake_llm or llm
    output_fn(_WELCOME_SMART)
    history: list[dict] = []
    facts: dict = {}
    user_text: str | None = None
    turns = 0
    while True:
        try:
            msg = input_fn("\n你 > ")
        except (EOFError, KeyboardInterrupt):
            output_fn("\n(結束對話)")
            return
        if msg is None:
            output_fn("\n(結束對話)")
            return
        if msg.strip().lower() in ("quit", "exit", "/quit", "/exit"):
            output_fn("(結束對話)")
            return

        if user_text is None:
            user_text = msg
        history.append({"role": "user", "content": msg})
        turns += 1

        turn = run_smart_intake_turn(history, facts, intake_llm)
        facts = turn.facts
        history.append({"role": "assistant", "content": turn.reply})
        output_fn(turn.reply)

        done_signal = msg.strip() in _DONE_WORDS or any(p in msg for p in _DONE_PHRASES)
        ready = turn.ready or done_signal or all(k in facts for k in ALL_FIELD_KEYS) or turns >= max_turns
        if ready:
            output_fn("\n(資訊已足夠——開始檢索法條並診斷;這一步只檢索一次)")
            state = flow.SessionState(
                stage=flow.Stage.READY_FOR_STAGE3,
                problem_type="noise",
                collected_facts=facts,
                user_text=user_text,
            )
            result = flow.advance_to_stage3(state, llm=llm, as_of_date=as_of_date, conn=conn)
            output_fn(_format_result(result))
            return   # clinic-style: one diagnosis per session


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    import argparse

    parser = argparse.ArgumentParser(
        prog="legal_agent.run", description="住宅噪音法律助理(個人用)"
    )
    parser.add_argument(
        "--as-of", dest="as_of", default=None,
        help="時間點 YYYY-MM-DD:依該日有效的法條版本回答",
    )
    args = parser.parse_args(argv)

    if args.as_of:
        try:
            date.fromisoformat(args.as_of)
        except ValueError:
            _die(f"--as-of 需為 YYYY-MM-DD 格式,得到 {args.as_of!r}")

    llm = build_runtime_llm()   # exits cleanly if the backend is missing/unusable

    from legal_agent.data.database import connect

    conn = connect(config.DB_PATH)
    provider = getattr(config, "LLM_PROVIDER", "anthropic")
    smart = provider != "manual" and getattr(config, "SMART_INTAKE", True)
    intake_llm = None
    if smart and provider == "ollama":
        # Constrain the local model to valid JSON so fact extraction is reliable.
        from legal_agent.dialogue.ollama_llm import ollama_llm

        intake_llm = ollama_llm(fmt="json")
    try:
        if smart:
            run_smart_conversation(llm, conn, as_of_date=args.as_of, intake_llm=intake_llm)
        else:
            run_conversation(llm, conn, as_of_date=args.as_of)
    except KeyboardInterrupt:
        print("\n(已中止)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
