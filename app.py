"""Gradio demo — the five anti-hallucination gates, made visible.

Runs with ZERO keys and ZERO paid API:
  - 引用查核 / 檢索 tabs are fully deterministic (no LLM at all).
  - 完整流程 tab works in "manual" style anywhere (assemble the retrieval-first
    prompt -> paste it into any chat you already have -> paste the answer back
    -> all five gates run over it). If a local Ollama server is reachable, a
    one-click live-generation button appears too.

Local:      python app.py
HF Spaces:  push this repo with app.py at the root (sdk: gradio) — see
            docs/DEPLOY_SPACES.md.
"""
from __future__ import annotations

import gradio as gr

from legal_agent import config
from legal_agent.anti_hallucination.verifier import verify_answer
from legal_agent.data.database import connect, init_db
from legal_agent.data.noise_seed import load_noise_statutes
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals
from legal_agent.dialogue.flow import SessionState, Stage, advance_to_stage3
from legal_agent.dialogue.ollama_llm import ollama_available, ollama_llm
from legal_agent.dialogue.stage3 import assemble_fact_query, build_model_input
from legal_agent.retrieval.retriever import retrieve_scored

DISCLAIMER = (
    "> ⚠ 工程實驗展示,**非法律意見**、不能取代律師。參考法源為官方公開資料之逐字節錄;"
    "corpus 僅涵蓋「住宅噪音」單一情境(11 筆,全數人工核對)。"
)

# A deliberately-broken sample answer: one wrong amount, one statute not in the
# corpus, and one TYPO'd statute name (公寀≠公寓) — mirrors what the live 8B
# model actually did in the README demo. Every defect must be flagged.
SAMPLE_BAD_ANSWER = (
    "依社會秩序維護法第72條,深夜喧嘩可處新臺幣六萬元以下罰鍰。"
    "另依噪音管制法第8條及公寀大廈管理條例第16條,亦有相關管制。"
)

_EXAMPLE_FACTS = {
    "noise_type": "深夜喧嘩爭吵、摔東西撞擊地板",
    "timing": "半夜十二點以後,幾乎每天,已持續三個月",
    "building_type": "公寓大廈,設有管理委員會",
    "impact": "長期失眠,精神耗弱",
    "evidence": "有錄音與分貝App紀錄",
    "actions_taken": "報過警兩次,也向管委會反映過,對方不聽勸阻",
}
_FIELD_LABELS = [
    ("noise_type", "噪音主要是什麼?"),
    ("timing", "什麼時段?持續性?"),
    ("building_type", "公寓大廈(有管委會)或透天?"),
    ("impact", "對你的影響?"),
    ("evidence", "有無錄音/錄影等證據?"),
    ("actions_taken", "報過警/反映過管委會嗎?"),
]


def ensure_db() -> None:
    """Idempotent: build the SQLite schema and load the hand-verified corpus."""
    init_db(config.DB_PATH)
    conn = connect(config.DB_PATH)
    try:
        seed_source_hierarchy(conn)
        load_noise_statutes(conn)
        proposals = config.CORPUS_DIR / "noise_routing_proposal.json"
        if proposals.exists():
            load_proposals(proposals, conn)
    finally:
        conn.close()


def _fmt_verifications(vs) -> str:
    if not vs:
        return "(答案中未偵測到任何法條/文號引用)"
    ok = "✅"
    bad = "🚩"
    lines = [
        "| 引用 | 存在 | 內容相符 | 現行有效 | 判定 |",
        "|---|---|---|---|---|",
    ]
    for v in vs:
        lines.append(
            f"| {v.citation.raw} | {ok if v.exists else bad} | "
            f"{ok if v.content_match else bad} | {ok if v.in_force else bad} | "
            f"{'🚩 ' + v.reason if v.flagged else '✅ 可回溯到 corpus'} |"
        )
    for v in vs:
        if v.flagged and v.verbatim_source:
            lines.append(
                f"\n<details><summary>🚩 {v.citation.raw} — corpus 條文原文對照</summary>\n\n"
                f"```\n{v.verbatim_source}\n```\n</details>"
            )
    return "\n".join(lines)


def _tier_badge(tier: str) -> str:
    return {
        "normal": "🟢 normal — 檢索到高相關法源",
        "marginal": "🟡 marginal — 僅邊緣相關,以下僅供參考",
        "insufficient": "🔴 insufficient — 資料庫未涵蓋,拒絕作答(不編造)",
    }.get(tier, tier)


# ── Tab 1: 引用查核 playground(無 LLM,純決定論) ────────────────────────────
def check_citations(answer_text: str, as_of: str) -> str:
    conn = connect(config.DB_PATH)
    try:
        vs = verify_answer(answer_text or "", [], as_of_date=(as_of or None), conn=conn)
    except ValueError as exc:
        return f"⚠ {exc}"
    finally:
        conn.close()
    flagged = sum(1 for v in vs if v.flagged)
    head = f"**{len(vs)} 筆引用,{flagged} 筆被標記。**\n\n"
    return head + _fmt_verifications(vs)


# ── Tab 2: 檢索 + time-slice explorer ────────────────────────────────────────
def explore_retrieval(query: str, as_of: str) -> str:
    from legal_agent.anti_hallucination.honesty import grade_honesty

    conn = connect(config.DB_PATH)
    try:
        scored = retrieve_scored(query or "", as_of_date=(as_of or None), conn=conn)
    except ValueError as exc:
        return f"⚠ {exc}"
    finally:
        conn.close()
    tier = grade_honesty([s for s, _ in scored], [sc for _, sc in scored])
    lines = [f"**誠實分級:{_tier_badge(tier)}**", ""]
    if not scored:
        lines.append("(檢索結果為空 — 系統會拒答,不會編造)")
    for s, sc in scored:
        lines.append(
            f"- `BM25 {sc:.2f}` **{s.statute_id}{s.article_no}**"
            f"(位階:{s.hierarchy_level};生效 {s.effective_from}) "
            f"{s.content[:60].replace(chr(10), ' ')}…"
        )
    lines.append("")
    lines.append("試試 as-of 換成 `2024-06-01`:社維法§72 的 2025-06-11 版會從候選中消失(time-slice)。")
    return "\n".join(lines)


# ── Tab 3: 完整流程(manual 貼上 / 本機 Ollama) ──────────────────────────────
def _facts_from_inputs(*values: str) -> dict:
    return {
        key: v.strip()
        for (key, _), v in zip(_FIELD_LABELS, values)
        if v and v.strip()
    }


def assemble_prompt(as_of: str, *values: str) -> str:
    facts = _facts_from_inputs(*values)
    if not facts:
        return "⚠ 請至少填一個欄位。"
    conn = connect(config.DB_PATH)
    try:
        scored = retrieve_scored(assemble_fact_query(facts), as_of_date=(as_of or None), conn=conn)
    finally:
        conn.close()
    return build_model_input([s for s, _ in scored], facts)


def _run_gates(llm, user_text: str, as_of: str, *values: str) -> str:
    facts = _facts_from_inputs(*values)
    if not facts:
        return "⚠ 請至少填一個欄位。"
    state = SessionState(
        stage=Stage.READY_FOR_STAGE3,
        collected_facts=facts,
        user_text=(user_text or None),
    )
    conn = connect(config.DB_PATH)
    try:
        result = advance_to_stage3(state, llm=llm, as_of_date=(as_of or None), conn=conn)
    finally:
        conn.close()
    parts = [
        f"### 誠實分級:{_tier_badge(result.honesty_tier)}",
        ("⚠ **前提警示(反迎合)**:你的描述包含法律結論斷言,系統已優先查證而非附和。"
         if result.premise_flag else ""),
        "#### 引用查核(Gate 2)",
        _fmt_verifications(result.verifications),
        "#### 回答(法律明文/實務見解/分析研判 三段分離)",
        result.answer,
        "#### 解法階梯(低成本 → 高成本)",
        f"```\n{result.solution_text}\n```",
    ]
    return "\n\n".join(p for p in parts if p)


def run_gates_on_pasted(pasted_answer: str, user_text: str, as_of: str, *values: str) -> str:
    if not (pasted_answer or "").strip():
        return "⚠ 請先把外部模型的回答貼進來(或改用本機 Ollama 按鈕)。"
    return _run_gates(lambda _p: pasted_answer, user_text, as_of, *values)


def run_gates_live(user_text: str, as_of: str, *values: str) -> str:
    if not ollama_available():
        return "⚠ 本機 Ollama 未啟動(demo 站上不可用)。請改用「組裝提示詞 → 貼回答」流程。"
    return _run_gates(ollama_llm(), user_text, as_of, *values)


# ── Tab 4: 評測數字 ──────────────────────────────────────────────────────────
def load_results_md() -> str:
    path = config.PROJECT_ROOT / "evals" / "RESULTS.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "(evals/RESULTS.md 尚未產生 — 依 evals/README.md 跑三個評測指令。)"


ensure_db()

with gr.Blocks(title="Legal Agent — 防幻覺五閘門 Demo") as demo:
    gr.Markdown(
        "# Legal Agent — 讓模型「引用不了它沒讀到的法條」\n"
        "retrieval-first 管線:模型只能引用檢索到的逐字法源;每筆引用經"
        "**存在/內容相符/現行有效**三軸查核;錯了,使用者會知道錯在哪。\n\n"
        + DISCLAIMER
    )
    with gr.Tab("引用查核 Playground"):
        gr.Markdown(
            "把任何「AI 法律回答」貼進來,verifier 逐筆對照 corpus。"
            "預填範例含三個真實缺陷:金額錯、引用庫外法條、法規名打錯字(公寀)。"
        )
        ans_in = gr.Textbox(value=SAMPLE_BAD_ANSWER, lines=4, label="AI 回答文字")
        asof_1 = gr.Textbox(value="", label="as-of 日期(YYYY-MM-DD,留空=現行)")
        out_1 = gr.Markdown()
        gr.Button("跑引用查核", variant="primary").click(
            check_citations, [ans_in, asof_1], out_1
        )
    with gr.Tab("檢索 + Time-slice"):
        q_in = gr.Textbox(
            value="深夜喧嘩爭吵 半夜 幾乎每天 公寓大廈 管理委員會",
            label="事實描述(檢索查詢)",
        )
        asof_2 = gr.Textbox(value="", label="as-of 日期(YYYY-MM-DD,留空=現行)")
        out_2 = gr.Markdown()
        gr.Button("檢索", variant="primary").click(explore_retrieval, [q_in, asof_2], out_2)
    with gr.Tab("完整流程(五閘門)"):
        gr.Markdown(
            "1️⃣ 填事實 → 組裝 retrieval-first 提示詞(零金鑰:貼到你自己的任何聊天工具)"
            " → 2️⃣ 把模型回答貼回來 → 五道閘門全跑。本機有 Ollama 可一鍵直跑。"
        )
        user_text_in = gr.Textbox(
            value="樓上鄰居幾乎每天半夜大聲喧嘩,這構成恐嚇罪吧,我要告他!",
            label="一句話描述(供 Gate 5 前提偵測)",
        )
        field_inputs = [
            gr.Textbox(value=_EXAMPLE_FACTS[key], label=label)
            for key, label in _FIELD_LABELS
        ]
        asof_3 = gr.Textbox(value="", label="as-of 日期(YYYY-MM-DD,留空=現行)")
        prompt_out = gr.Textbox(lines=8, label="組裝好的提示詞(複製到任何聊天工具)")
        gr.Button("1️⃣ 組裝提示詞").click(assemble_prompt, [asof_3, *field_inputs], prompt_out)
        pasted_in = gr.Textbox(lines=6, label="2️⃣ 把模型回答貼回這裡")
        gates_out = gr.Markdown()
        gr.Button("跑五閘門(用貼上的回答)", variant="primary").click(
            run_gates_on_pasted, [pasted_in, user_text_in, asof_3, *field_inputs], gates_out
        )
        gr.Button("或:本機 Ollama 直接生成+跑閘門").click(
            run_gates_live, [user_text_in, asof_3, *field_inputs], gates_out
        )
    with gr.Tab("評測數字"):
        gr.Markdown(load_results_md())

if __name__ == "__main__":
    demo.launch()
