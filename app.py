"""Gradio demo — the five anti-hallucination gates, made visible.

Design notes: this is a serious tool, so the UI is deliberately austere —
monochrome theme, no emoji, no badge pills, CJK-first typography, and the
fewest words that still say the thing. Citations render as verdict cards
(per-axis ✓/✗, corpus verbatim one click away); inputs left, evidence right;
the playground auto-runs on load so the first screen already shows a result.

Runs with ZERO keys and ZERO paid API:
  - 引用查核 / 法規檢索 tabs are fully deterministic (no LLM at all).
  - 完整流程 tab works in "manual" style anywhere (assemble the retrieval-first
    prompt -> paste it into any chat you already have -> paste the answer back
    -> all five gates run over it). If a local Ollama server is reachable, a
    one-click live-generation button appears too.

Local:      python app.py
HF Spaces:  push this repo with app.py at the root (sdk: gradio) — see
            docs/DEPLOY_SPACES.md.
"""
from __future__ import annotations

from html import escape

import gradio as gr

from legal_agent import config
from legal_agent.anti_hallucination.honesty import grade_honesty
from legal_agent.anti_hallucination.verifier import verify_answer
from legal_agent.data.database import connect, init_db
from legal_agent.data.noise_seed import load_noise_statutes
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals
from legal_agent.dialogue.flow import SessionState, Stage, advance_to_stage3
from legal_agent.dialogue.ollama_llm import ollama_available, ollama_llm
from legal_agent.dialogue.stage3 import assemble_fact_query, build_model_input
from legal_agent.retrieval.retriever import retrieve_scored

# ── content ──────────────────────────────────────────────────────────────────
# A deliberately-broken sample answer: one wrong amount, one statute not in the
# corpus, and one TYPO'd statute name (公寀≠公寓) — mirrors what the live 8B
# model actually did in the README demo. Every defect must be flagged.
SAMPLE_BAD_ANSWER = (
    "依社會秩序維護法第72條,深夜喧嘩可處新臺幣六萬元以下罰鍰。"
    "另依噪音管制法第8條及公寀大廈管理條例第16條,亦有相關管制。"
)
SAMPLE_GOOD_ANSWER = (
    "依社會秩序維護法第72條,製造噪音或深夜喧嘩妨害公眾安寧、不聽禁止者,"
    "可處新臺幣一萬元以下罰鍰。"
)
DEFAULT_QUERY = "深夜喧嘩爭吵 半夜 幾乎每天 公寓大廈 管理委員會"

_EXAMPLE_FACTS = {
    "noise_type": "深夜喧嘩爭吵、摔東西撞擊地板",
    "timing": "半夜十二點以後,幾乎每天,已持續三個月",
    "building_type": "公寓大廈,設有管理委員會",
    "impact": "長期失眠,精神耗弱",
    "evidence": "有錄音與分貝App紀錄",
    "actions_taken": "報過警兩次,也向管委會反映過,對方不聽勸阻",
}
_DOG_FACTS = {
    "noise_type": "鄰居飼養的犬隻長時間吠叫",
    "timing": "白天晚上都有,斷斷續續",
    "building_type": "公寓大廈,設有管理委員會",
    "impact": "無法休息",
    "evidence": "有錄影",
    "actions_taken": "口頭反映過,對方不改善",
}
_FIELD_LABELS = [
    ("noise_type", "噪音類型"),
    ("timing", "時段與頻率"),
    ("building_type", "建物型態"),
    ("impact", "影響"),
    ("evidence", "證據"),
    ("actions_taken", "已採取行動"),
]

_TIER_TEXT = {
    "normal": "充分——檢索到高相關法源",
    "marginal": "邊緣——未找到直接對應法條,僅供參考",
    "insufficient": "不足——資料庫未涵蓋,不作答",
}

# ── styling(theme + css are passed to launch() in Gradio 6) ─────────────────
FONT_STACK = [
    "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "system-ui", "sans-serif",
]

CSS = """
.gradio-container {font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",system-ui,sans-serif}
.gradio-container p, .gradio-container li {line-height:1.75}

.hero {padding:14px 0 2px}
.hero h1 {margin:0; font-size:22px; font-weight:650; letter-spacing:.02em}
.hero .sub {margin:6px 0 0; font-size:14.5px; opacity:.8}
.hero .meta {margin:4px 0 0; font-size:12.5px; opacity:.5}
.disclaimer {font-size:12px; opacity:.55; margin-top:14px}

.verdict {border:1px solid var(--border-color-primary); border-left-width:3px;
  border-radius:6px; padding:9px 14px; font-weight:600; font-size:14px; margin:2px 0 10px}
.verdict.normal       {border-left-color:#2f7d4f}
.verdict.marginal     {border-left-color:#b07d24}
.verdict.insufficient {border-left-color:#b3372f}

.note {border:1px solid var(--border-color-primary); border-radius:6px;
  padding:8px 14px; margin:2px 0 10px; font-size:13.5px; opacity:.92}

.cite-card {border:1px solid var(--border-color-primary); border-left:3px solid #2f7d4f;
  border-radius:6px; padding:10px 14px; margin:8px 0}
.cite-card.bad {border-left-color:#b3372f}
.cite-card .ref {font-weight:650; font-size:14.5px}
.ax {font-size:12.5px; margin-left:12px; white-space:nowrap}
.ax.ok  {color:#2f7d4f}
.ax.bad {color:#b3372f}
.cite-card .why {margin-top:5px; font-size:13px; opacity:.85}
.cite-card details {margin-top:6px; font-size:12.5px}
.cite-card summary {cursor:pointer; opacity:.6}
.cite-card pre {white-space:pre-wrap; font-size:12.5px; border-radius:6px; padding:10px;
  margin-top:6px; background:var(--background-fill-secondary); line-height:1.7}

.retr-card {border:1px solid var(--border-color-primary); border-radius:6px;
  padding:9px 14px; margin:8px 0}
.retr-card .head {display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap}
.retr-card .ref {font-weight:650; font-size:14px}
.retr-card .meta {font-size:12px; opacity:.6}
.retr-card .excerpt {font-size:12.5px; opacity:.75; margin-top:3px}
.bar {height:4px; border-radius:2px; background:var(--background-fill-secondary);
  margin-top:8px; overflow:hidden}
.bar > i {display:block; height:100%; background:#64748b}

.compare {display:grid; grid-template-columns:1fr 1fr; gap:14px}
@media (max-width:860px){.compare {grid-template-columns:1fr}}
.compare .colhead {font-weight:650; font-size:13.5px; margin:2px 0 4px; opacity:.8}

.statgrid {display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:12px; margin:8px 0 6px}
.stat {border:1px solid var(--border-color-primary); border-radius:6px;
  padding:16px 10px; text-align:center}
.stat .num {font-size:24px; font-weight:700; line-height:1.15}
.stat .lbl {font-size:12.5px; opacity:.65; margin-top:6px; line-height:1.6}

.seccard {border:1px solid var(--border-color-primary); border-radius:6px;
  padding:10px 14px; margin:8px 0}
.seccard .t {font-weight:650; font-size:13.5px; margin-bottom:4px}
.seccard .b {white-space:pre-wrap; font-size:13.5px; line-height:1.8}
.ladder {white-space:pre-wrap; font-size:12.5px; border-radius:6px; padding:12px;
  background:var(--background-fill-secondary); line-height:1.8}
h4.blockhead {margin:16px 0 2px; font-size:14px; font-weight:650; opacity:.85}
"""

HERO = """
<div class="hero">
  <h1>Legal Agent</h1>
  <p class="sub">模型只能引用檢索到的法源;每筆引用經「存在、內容、時效」三軸查核——錯了,使用者會知道錯在哪。</p>
  <p class="meta">134 項測試通過 · 植入錯誤抓取率 31/31 · 不需任何 API 金鑰</p>
</div>
"""

FOOTER = """
<p class="disclaimer">工程實驗,非法律意見,不能取代律師。法源為官方公開資料逐字節錄;
現僅涵蓋「住宅噪音」單一情境(11 筆,全數人工核對)。</p>
"""


# ── data bootstrap ───────────────────────────────────────────────────────────
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


# ── html renderers ───────────────────────────────────────────────────────────
def _axis(label: str, ok: bool) -> str:
    mark = "✓" if ok else "✗"
    return f'<span class="ax {"ok" if ok else "bad"}">{label} {mark}</span>'


def _cite_cards(vs) -> str:
    if not vs:
        return "<p>(未偵測到法條或文號引用)</p>"
    cards = []
    for v in vs:
        axes = (
            _axis("存在", v.exists)
            + _axis("內容", v.content_match)
            + _axis("時效", v.in_force)
        )
        reason = v.reason.replace("corpus", "資料庫")   # display only; backend strings are load-bearing in tests/docs
        why = (
            f'<div class="why">{escape(reason)}</div>'
            if v.flagged
            else '<div class="why">可回溯至資料庫條文</div>'
        )
        details = ""
        if v.flagged and v.verbatim_source:
            details = (
                "<details><summary>條文原文</summary>"
                f"<pre>{escape(v.verbatim_source)}</pre></details>"
            )
        cards.append(
            f'<div class="cite-card{" bad" if v.flagged else ""}">'
            f'<span class="ref">{escape(v.citation.raw)}</span>{axes}{why}{details}</div>'
        )
    return "".join(cards)


def _tier_bar(tier: str) -> str:
    return f'<div class="verdict {escape(tier)}">{_TIER_TEXT.get(tier, escape(tier))}</div>'


def _retr_cards(scored) -> str:
    if not scored:
        return '<div class="verdict insufficient">檢索結果為空——系統不作答,不編造</div>'
    top = max(sc for _, sc in scored) or 1.0
    cards = []
    for s, sc in scored:
        width = max(4, int(round(sc / top * 100)))
        excerpt = escape(s.content[:56].replace("\n", " "))
        cards.append(
            '<div class="retr-card"><div class="head">'
            f'<span class="ref">{escape(s.statute_id + s.article_no)}</span>'
            f'<span class="meta">{escape(s.hierarchy_level)} · 生效 {escape(s.effective_from)}'
            f" · 相關度 {sc:.1f}</span></div>"
            f'<div class="excerpt">{excerpt}…</div>'
            f'<div class="bar"><i style="width:{width}%"></i></div></div>'
        )
    return "".join(cards)


# ── 引用查核(無模型,純決定論) ────────────────────────────────────────────────
def check_citations(answer_text: str, as_of: str) -> str:
    conn = connect(config.DB_PATH)
    try:
        vs = verify_answer(answer_text or "", [], as_of_date=(as_of or None), conn=conn)
    except ValueError as exc:
        return f'<div class="note">{escape(str(exc))}</div>'
    finally:
        conn.close()
    flagged = sum(1 for v in vs if v.flagged)
    tone = "insufficient" if flagged else "normal"
    return (
        f'<div class="verdict {tone}">{len(vs)} 筆引用,{flagged} 筆未通過</div>'
        + _cite_cards(vs)
    )


# ── 法規檢索 ─────────────────────────────────────────────────────────────────
def explore_retrieval(query: str, as_of: str) -> str:
    conn = connect(config.DB_PATH)
    try:
        scored = retrieve_scored(query or "", as_of_date=(as_of or None), conn=conn)
    except ValueError as exc:
        return f'<div class="note">{escape(str(exc))}</div>'
    finally:
        conn.close()
    tier = grade_honesty([s for s, _ in scored], [sc for _, sc in scored])
    return _tier_bar(tier) + _retr_cards(scored)


def compare_timeslice(query: str) -> str:
    """現行 vs 2024-06-01 — 2025-06-11 生效的社維法§72 只應出現在左欄。"""
    conn = connect(config.DB_PATH)
    try:
        now = retrieve_scored(query or "", None, conn=conn)
        then = retrieve_scored(query or "", "2024-06-01", conn=conn)
    finally:
        conn.close()
    return (
        '<div class="compare">'
        f'<div><div class="colhead">現行</div>{_retr_cards(now)}</div>'
        f'<div><div class="colhead">基準日 2024-06-01</div>{_retr_cards(then)}</div>'
        "</div>"
        '<div class="note">失效或尚未生效的版本,於排序之前即被排除,不會成為候選。</div>'
    )


# ── 完整流程(手動貼回 / 本機 Ollama) ─────────────────────────────────────────
def _facts_from_inputs(*values: str) -> dict:
    return {
        key: v.strip()
        for (key, _), v in zip(_FIELD_LABELS, values)
        if v and v.strip()
    }


def assemble_prompt(as_of: str, *values: str) -> str:
    facts = _facts_from_inputs(*values)
    if not facts:
        return "請至少填一個欄位。"
    conn = connect(config.DB_PATH)
    try:
        scored = retrieve_scored(assemble_fact_query(facts), as_of_date=(as_of or None), conn=conn)
    finally:
        conn.close()
    return build_model_input([s for s, _ in scored], facts)


def _sections_html(result) -> str:
    blocks = []
    for title, body in (
        ("法律明文", result.law_section),
        ("實務見解(非法律明文)", result.practice_section),
        ("分析研判(模型推論)", result.analysis_section),
    ):
        if body:
            blocks.append(
                f'<div class="seccard"><div class="t">{title}</div>'
                f'<div class="b">{escape(body.strip())}</div></div>'
            )
    if not blocks:   # model skipped the headings — show the raw answer, flagged
        return (
            '<div class="note">模型未依三段格式作答,以下為原文。</div>'
            f'<div class="seccard"><div class="b">{escape(result.answer)}</div></div>'
        )
    return "".join(blocks)


def _run_gates(llm, user_text: str, as_of: str, *values: str) -> str:
    facts = _facts_from_inputs(*values)
    if not facts:
        return '<div class="note">請至少填一個欄位。</div>'
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

    premise = (
        '<div class="note">前提警示:描述含法律結論斷言,系統優先查證而非附和。</div>'
        if result.premise_flag else ""
    )
    return (
        _tier_bar(result.honesty_tier)
        + premise
        + '<h4 class="blockhead">引用查核</h4>'
        + _cite_cards(result.verifications)
        + '<h4 class="blockhead">回答(依法源位階分段)</h4>'
        + _sections_html(result)
        + '<h4 class="blockhead">建議處理順序(低成本優先,訴訟最後)</h4>'
        + f'<div class="ladder">{escape(result.solution_text)}</div>'
    )


def run_gates_on_pasted(pasted_answer: str, user_text: str, as_of: str, *values: str) -> str:
    if not (pasted_answer or "").strip():
        return '<div class="note">請先貼入模型回答,或使用本機 Ollama。</div>'
    return _run_gates(lambda _p: pasted_answer, user_text, as_of, *values)


def run_gates_live(user_text: str, as_of: str, *values: str) -> str:
    if not ollama_available():
        return '<div class="note">本機 Ollama 未啟動。請改用「產生提示詞、貼回回答」流程。</div>'
    return _run_gates(ollama_llm(), user_text, as_of, *values)


# ── 評測結果 ─────────────────────────────────────────────────────────────────
STATS = """
<div class="statgrid">
  <div class="stat"><div class="num">31/31</div><div class="lbl">植入錯誤抓取率(零誤報)</div></div>
  <div class="stat"><div class="num">84%</div><div class="lbl">法條涵蓋率(含部分命中)</div></div>
  <div class="stat"><div class="num">100%</div><div class="lbl">錯誤前提偵測(25/25)</div></div>
  <div class="stat"><div class="num">0–5%</div><div class="lbl">裸模型引用可回溯率(對照組)</div></div>
</div>
"""


def load_results_md() -> str:
    path = config.PROJECT_ROOT / "evals" / "RESULTS.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "(尚未產生 evals/RESULTS.md;執行 evals/README.md 所列指令即可重現。)"


# ── layout ───────────────────────────────────────────────────────────────────
ensure_db()

with gr.Blocks(title="Legal Agent") as demo:
    gr.HTML(HERO)

    with gr.Tab("引用查核"):
        gr.Markdown("貼入任一 AI 法律回答,逐筆比對資料庫。預設範例含三處錯誤。")
        with gr.Row():
            with gr.Column(scale=5):
                ans_in = gr.Textbox(value=SAMPLE_BAD_ANSWER, lines=5, label="回答內容")
                asof_1 = gr.Textbox(value="", label="基準日", placeholder="YYYY-MM-DD,留空為現行")
                btn_check = gr.Button("查核", variant="primary")
                gr.Examples(
                    examples=[
                        [SAMPLE_BAD_ANSWER, ""],
                        [SAMPLE_GOOD_ANSWER, ""],
                        [SAMPLE_GOOD_ANSWER, "2024-06-01"],
                    ],
                    inputs=[ans_in, asof_1],
                    label="範例:錯誤回答 / 正確回答 / 正確條文但 2024 時點尚未生效",
                )
            with gr.Column(scale=7):
                out_check = gr.HTML()
        btn_check.click(check_citations, [ans_in, asof_1], out_check)

    with gr.Tab("完整流程"):
        gr.Markdown(
            "填入案情,產生提示詞,貼到任一對話工具;把回答貼回來,執行五道閘門。"
            "本機有 Ollama 可直接生成。"
        )
        with gr.Row():
            with gr.Column(scale=5):
                user_text_in = gr.Textbox(
                    value="樓上鄰居幾乎每天半夜大聲喧嘩,這構成恐嚇罪吧,我要告他!",
                    label="問題描述(一句話)",
                )
                field_inputs = [
                    gr.Textbox(value=_EXAMPLE_FACTS[key], label=label)
                    for key, label in _FIELD_LABELS
                ]
                asof_3 = gr.Textbox(value="", label="基準日", placeholder="YYYY-MM-DD,留空為現行")
                gr.Examples(
                    examples=[
                        [_EXAMPLE_FACTS[k] for k, _ in _FIELD_LABELS],
                        [_DOG_FACTS[k] for k, _ in _FIELD_LABELS],
                    ],
                    inputs=field_inputs,
                    label="範例案情:深夜喧嘩 / 公寓犬吠",
                )
                btn_prompt = gr.Button("產生提示詞")
                prompt_out = gr.Code(label="提示詞(複製至任一對話工具)", language="markdown")
                pasted_in = gr.Textbox(lines=6, label="貼回模型回答")
                btn_gates = gr.Button("執行五道閘門", variant="primary")
                btn_live = gr.Button("以本機 Ollama 生成")
            with gr.Column(scale=7):
                gates_out = gr.HTML()
        btn_prompt.click(assemble_prompt, [asof_3, *field_inputs], prompt_out)
        btn_gates.click(
            run_gates_on_pasted, [pasted_in, user_text_in, asof_3, *field_inputs], gates_out
        )
        btn_live.click(run_gates_live, [user_text_in, asof_3, *field_inputs], gates_out)

    with gr.Tab("法規檢索"):
        gr.Markdown("同一事實、不同基準日:2025-06-11 生效的社維法第72條,在 2024 時點不會成為候選。")
        q_in = gr.Textbox(value=DEFAULT_QUERY, label="事實描述")
        with gr.Row():
            asof_2 = gr.Textbox(value="", label="基準日", placeholder="YYYY-MM-DD,留空為現行", scale=3)
            btn_retr = gr.Button("檢索", variant="primary", scale=1)
            btn_cmp = gr.Button("現行與 2024-06-01 對照", scale=2)
        out_retr = gr.HTML()
        btn_retr.click(explore_retrieval, [q_in, asof_2], out_retr)
        btn_cmp.click(compare_timeslice, [q_in], out_retr)

    with gr.Tab("評測結果"):
        gr.HTML(STATS)
        gr.Markdown(load_results_md())

    gr.HTML(FOOTER)
    demo.load(check_citations, [ans_in, asof_1], out_check)
    demo.load(compare_timeslice, [q_in], out_retr)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Monochrome(font=FONT_STACK), css=CSS)
