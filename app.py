"""Gradio demo — the five anti-hallucination gates, made visible.

UI follows the conventions of open-source RAG frontends (kotaemon, Verba,
Open WebUI): citations are first-class cards with per-axis verdict chips and
the corpus verbatim one click away; inputs sit left, evidence right; example
inputs are one-click; the first screen already shows a result (auto-run on
load) so a visitor sees the thesis in seconds.

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
    ("noise_type", "噪音主要是什麼?"),
    ("timing", "什麼時段?持續性?"),
    ("building_type", "公寓大廈(有管委會)或透天?"),
    ("impact", "對你的影響?"),
    ("evidence", "有無錄音/錄影等證據?"),
    ("actions_taken", "報過警/反映過管委會嗎?"),
]

_TIER_TEXT = {
    "normal": "🟢 normal — 檢索到高相關法源",
    "marginal": "🟡 marginal — 僅邊緣相關,以下僅供參考",
    "insufficient": "🔴 insufficient — 資料庫未涵蓋,拒絕作答(不編造)",
}

# ── styling (theme + css are passed to launch() in Gradio 6) ─────────────────
CSS = """
.hero {text-align:center; padding:6px 0 0}
.hero h1 {margin:0 0 4px; font-size:26px}
.hero .sub {opacity:.78; font-size:15px; margin:0}
.hero .badges {margin-top:10px}
.badge {display:inline-block; padding:3px 12px; border-radius:999px; font-size:12px;
  font-weight:600; margin:0 3px; border:1px solid var(--border-color-primary);
  background:var(--block-background-fill)}
.disclaimer {text-align:center; font-size:12.5px; opacity:.65; margin-top:10px}

.cite-card {border:1px solid var(--border-color-primary); border-left:5px solid #22c55e;
  border-radius:10px; padding:10px 14px; margin:10px 0; background:var(--block-background-fill)}
.cite-card.bad {border-left-color:#ef4444}
.cite-card .ref {font-weight:700; font-size:15px; margin-right:2px}
.chip {display:inline-block; padding:1px 10px; border-radius:999px; font-size:12px;
  font-weight:600; margin:2px 0 2px 6px; border:1px solid transparent; white-space:nowrap}
.chip.ok  {background:rgba(34,197,94,.14);  border-color:rgba(34,197,94,.5)}
.chip.bad {background:rgba(239,68,68,.14); border-color:rgba(239,68,68,.55)}
.cite-card .why {margin-top:6px; font-size:13.5px; opacity:.92}
.cite-card details {margin-top:8px; font-size:13px}
.cite-card summary {cursor:pointer; opacity:.8}
.cite-card pre {white-space:pre-wrap; font-size:12.5px; border-radius:8px; padding:10px;
  margin-top:6px; background:var(--background-fill-secondary)}

.tierbar {border-radius:10px; padding:10px 14px; font-weight:700; margin:4px 0 10px; border:1px solid}
.tierbar.normal       {background:rgba(34,197,94,.10);  border-color:rgba(34,197,94,.4)}
.tierbar.marginal     {background:rgba(245,158,11,.10); border-color:rgba(245,158,11,.45)}
.tierbar.insufficient {background:rgba(239,68,68,.10);  border-color:rgba(239,68,68,.45)}
.alert {border-radius:10px; padding:8px 14px; margin:4px 0 10px; font-size:14px;
  border:1px dashed rgba(245,158,11,.6); background:rgba(245,158,11,.07)}

.retr-card {border:1px solid var(--border-color-primary); border-radius:10px;
  padding:10px 14px; margin:8px 0; background:var(--block-background-fill)}
.retr-card .head {display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap}
.retr-card .ref {font-weight:700}
.retr-card .meta {font-size:12px; opacity:.7}
.retr-card .excerpt {font-size:13px; opacity:.85; margin-top:4px}
.bar {height:7px; border-radius:4px; background:rgba(99,102,241,.18); margin-top:8px; overflow:hidden}
.bar > i {display:block; height:100%; background:#6366f1}

.compare {display:grid; grid-template-columns:1fr 1fr; gap:14px}
@media (max-width:860px){.compare {grid-template-columns:1fr}}
.compare .colhead {font-weight:700; margin:2px 0 6px}

.statgrid {display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:12px; margin:8px 0 6px}
.stat {border:1px solid var(--border-color-primary); border-radius:12px; padding:16px 10px;
  text-align:center; background:var(--block-background-fill)}
.stat .num {font-size:25px; font-weight:800; line-height:1.15}
.stat .lbl {font-size:12.5px; opacity:.72; margin-top:6px}

.seccard {border:1px solid var(--border-color-primary); border-radius:10px;
  padding:10px 14px; margin:8px 0; background:var(--block-background-fill)}
.seccard .t {font-weight:700; margin-bottom:4px}
.seccard .b {white-space:pre-wrap; font-size:13.5px}
.ladder {white-space:pre-wrap; font-size:13px; border-radius:10px; padding:12px;
  background:var(--background-fill-secondary)}
h4.blockhead {margin:14px 0 2px}
"""

HERO = """
<div class="hero">
  <h1>⚖️ Legal Agent — 讓模型「引用不了它沒讀到的法條」</h1>
  <p class="sub">retrieval-first 管線:模型只能引用檢索到的逐字法源;每筆引用經
  <b>存在 / 內容相符 / 現行有效</b> 三軸查核 — 錯了,使用者會知道錯在哪。</p>
  <div class="badges">
    <span class="badge">💸 $0 · 零金鑰</span>
    <span class="badge">🔬 134 tests</span>
    <span class="badge">🧪 verifier 抓取率 31/31</span>
    <span class="badge">🕰️ time-sliced corpus</span>
    <span class="badge">MIT</span>
  </div>
</div>
"""

FOOTER = """
<p class="disclaimer">⚠ 工程實驗展示,<b>非法律意見</b>、不能取代律師。
法源為官方公開資料逐字節錄;corpus 僅涵蓋「住宅噪音」單一情境(11 筆,全數人工核對)。</p>
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
def _chip(label: str, ok: bool) -> str:
    return f'<span class="chip {"ok" if ok else "bad"}">{label} {"✅" if ok else "🚩"}</span>'


def _cite_cards(vs) -> str:
    if not vs:
        return "<p>(答案中未偵測到任何法條/文號引用)</p>"
    cards = []
    for v in vs:
        chips = (
            _chip("存在", v.exists)
            + _chip("內容相符", v.content_match)
            + _chip("現行有效", v.in_force)
        )
        why = (
            f'<div class="why">🚩 {escape(v.reason)}</div>'
            if v.flagged
            else '<div class="why">✅ 可回溯到 corpus 逐字條文</div>'
        )
        details = ""
        if v.flagged and v.verbatim_source:
            details = (
                "<details><summary>corpus 條文原文對照</summary>"
                f"<pre>{escape(v.verbatim_source)}</pre></details>"
            )
        cards.append(
            f'<div class="cite-card{" bad" if v.flagged else ""}">'
            f'<span class="ref">{escape(v.citation.raw)}</span>{chips}{why}{details}</div>'
        )
    return "".join(cards)


def _tier_bar(tier: str) -> str:
    return f'<div class="tierbar {escape(tier)}">{_TIER_TEXT.get(tier, escape(tier))}</div>'


def _retr_cards(scored) -> str:
    if not scored:
        return '<div class="tierbar insufficient">🔴 檢索結果為空 — 系統會拒答,不會編造</div>'
    top = max(sc for _, sc in scored) or 1.0
    cards = []
    for s, sc in scored:
        width = max(4, int(round(sc / top * 100)))
        excerpt = escape(s.content[:64].replace("\n", " "))
        cards.append(
            '<div class="retr-card"><div class="head">'
            f'<span class="ref">{escape(s.statute_id + s.article_no)}</span>'
            f'<span class="meta">位階 {escape(s.hierarchy_level)} · 生效 {escape(s.effective_from)}'
            f" · BM25 {sc:.2f}</span></div>"
            f'<div class="excerpt">{excerpt}…</div>'
            f'<div class="bar"><i style="width:{width}%"></i></div></div>'
        )
    return "".join(cards)


# ── tab 1: citation-verifier playground(no LLM, deterministic) ──────────────
def check_citations(answer_text: str, as_of: str) -> str:
    conn = connect(config.DB_PATH)
    try:
        vs = verify_answer(answer_text or "", [], as_of_date=(as_of or None), conn=conn)
    except ValueError as exc:
        return f'<div class="alert">⚠ {escape(str(exc))}</div>'
    finally:
        conn.close()
    flagged = sum(1 for v in vs if v.flagged)
    tone = "insufficient" if flagged else "normal"
    head = (
        f'<div class="tierbar {tone}">{len(vs)} 筆引用,{flagged} 筆被標記'
        f'{" — 每筆附 corpus 原文可對照" if flagged else ""}</div>'
    )
    return head + _cite_cards(vs)


# ── tab 2: retrieval + time-slice explorer ───────────────────────────────────
def explore_retrieval(query: str, as_of: str) -> str:
    conn = connect(config.DB_PATH)
    try:
        scored = retrieve_scored(query or "", as_of_date=(as_of or None), conn=conn)
    except ValueError as exc:
        return f'<div class="alert">⚠ {escape(str(exc))}</div>'
    finally:
        conn.close()
    tier = grade_honesty([s for s, _ in scored], [sc for _, sc in scored])
    return _tier_bar(tier) + _retr_cards(scored)


def compare_timeslice(query: str) -> str:
    """現行 vs 2024-06-01 side by side — the 2025-06-11 社維法§72 slice must
    appear on the left and vanish on the right (point-in-time filter)."""
    conn = connect(config.DB_PATH)
    try:
        now = retrieve_scored(query or "", None, conn=conn)
        then = retrieve_scored(query or "", "2024-06-01", conn=conn)
    finally:
        conn.close()
    return (
        '<div class="compare">'
        f'<div><div class="colhead">現行(as-of 今天)</div>{_retr_cards(now)}</div>'
        f'<div><div class="colhead">as-of 2024-06-01</div>{_retr_cards(then)}</div>'
        "</div>"
        '<div class="alert">🕰️ 社維法§72 的庫內版本 2025-06-11 生效 — 右欄(2024 時點)'
        "由 point-in-time filter 在<b>排序之前</b>就排除,失效/未生效版本連候選都當不成。</div>"
    )


# ── tab 3: full five-gate flow(manual paste / local Ollama) ─────────────────
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


def _sections_html(result) -> str:
    blocks = []
    for title, body in (
        ("法律明文(可回溯逐字條文)", result.law_section),
        ("實務見解(非法律明文,僅供參考)", result.practice_section),
        ("分析研判(模型推論,僅供參考)", result.analysis_section),
    ):
        if body:
            blocks.append(
                f'<div class="seccard"><div class="t">{title}</div>'
                f'<div class="b">{escape(body.strip())}</div></div>'
            )
    if not blocks:   # model skipped the headings — show the raw answer, flagged
        return (
            '<div class="alert">⚠ 模型未依三段格式作答(sections_ok=False),以下為原文。</div>'
            f'<div class="seccard"><div class="b">{escape(result.answer)}</div></div>'
        )
    return "".join(blocks)


def _run_gates(llm, user_text: str, as_of: str, *values: str) -> str:
    facts = _facts_from_inputs(*values)
    if not facts:
        return '<div class="alert">⚠ 請至少填一個欄位。</div>'
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
        '<div class="alert">⚠ <b>前提警示(Gate 5 反迎合)</b>:你的描述包含法律結論斷言,'
        "系統已優先查證而非附和。</div>"
        if result.premise_flag else ""
    )
    return (
        _tier_bar(result.honesty_tier)
        + premise
        + '<h4 class="blockhead">引用查核(Gate 2:存在/內容/現行)</h4>'
        + _cite_cards(result.verifications)
        + '<h4 class="blockhead">回答(Gate 4:三段分離)</h4>'
        + _sections_html(result)
        + '<h4 class="blockhead">解法階梯(低成本 → 高成本;訴訟最後)</h4>'
        + f'<div class="ladder">{escape(result.solution_text)}</div>'
    )


def run_gates_on_pasted(pasted_answer: str, user_text: str, as_of: str, *values: str) -> str:
    if not (pasted_answer or "").strip():
        return '<div class="alert">⚠ 請先把外部模型的回答貼進來(或改用本機 Ollama 按鈕)。</div>'
    return _run_gates(lambda _p: pasted_answer, user_text, as_of, *values)


def run_gates_live(user_text: str, as_of: str, *values: str) -> str:
    if not ollama_available():
        return (
            '<div class="alert">⚠ 本機 Ollama 未啟動(demo 站上不可用)。'
            "請改用「組裝提示詞 → 貼回答」流程 — 這正是零成本 manual 模式。</div>"
        )
    return _run_gates(ollama_llm(), user_text, as_of, *values)


# ── tab 4: measured numbers ──────────────────────────────────────────────────
STATS = """
<div class="statgrid">
  <div class="stat"><div class="num">31/31</div><div class="lbl">verifier 抓取率(植入錯誤)· 0 誤報</div></div>
  <div class="stat"><div class="num">84%</div><div class="lbl">golden set 法條涵蓋 pass+partial(llama3.1 8B)</div></div>
  <div class="stat"><div class="num">100%</div><div class="lbl">反迎合前提偵測(25/25)</div></div>
  <div class="stat"><div class="num">0–5%</div><div class="lbl">裸模型憑記憶引用之可回溯率(gated 下全數查核)</div></div>
</div>
"""


def load_results_md() -> str:
    path = config.PROJECT_ROOT / "evals" / "RESULTS.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "(evals/RESULTS.md 尚未產生 — 依 evals/README.md 跑三個評測指令。)"


# ── layout ───────────────────────────────────────────────────────────────────
ensure_db()

with gr.Blocks(title="Legal Agent — 防幻覺五閘門 Demo") as demo:
    gr.HTML(HERO)

    with gr.Tab("🔍 引用查核 Playground"):
        gr.Markdown(
            "把任何「AI 法律回答」貼進來,verifier 逐筆對照 corpus——"
            "**頁面載入就先跑一發**,預填範例含三個真實缺陷:金額錯、引用庫外法條、法規名錯字(公寀)。"
        )
        with gr.Row():
            with gr.Column(scale=5):
                ans_in = gr.Textbox(value=SAMPLE_BAD_ANSWER, lines=5, label="AI 回答文字")
                asof_1 = gr.Textbox(
                    value="", label="as-of 日期", placeholder="YYYY-MM-DD,留空=現行"
                )
                btn_check = gr.Button("跑引用查核", variant="primary")
                gr.Examples(
                    examples=[
                        [SAMPLE_BAD_ANSWER, ""],
                        [SAMPLE_GOOD_ANSWER, ""],
                        [SAMPLE_GOOD_ANSWER, "2024-06-01"],
                    ],
                    inputs=[ans_in, asof_1],
                    label="一鍵範例:壞答案 / 正確答案 / 正確條文但 2024 時點(版本未生效→標記)",
                )
            with gr.Column(scale=7):
                out_check = gr.HTML()
        btn_check.click(check_citations, [ans_in, asof_1], out_check)

    with gr.Tab("⚖️ 完整流程(五閘門)"):
        gr.Markdown(
            "1️⃣ 填案情 → 組裝 retrieval-first 提示詞(零金鑰:複製到你自己的任何聊天工具)"
            " → 2️⃣ 把模型回答貼回來 → 五道閘門全跑。本機有 Ollama 可一鍵直跑。"
        )
        with gr.Row():
            with gr.Column(scale=5):
                user_text_in = gr.Textbox(
                    value="樓上鄰居幾乎每天半夜大聲喧嘩,這構成恐嚇罪吧,我要告他!",
                    label="一句話描述(Gate 5 前提偵測吃這句)",
                )
                field_inputs = [
                    gr.Textbox(value=_EXAMPLE_FACTS[key], label=label)
                    for key, label in _FIELD_LABELS
                ]
                asof_3 = gr.Textbox(value="", label="as-of 日期", placeholder="YYYY-MM-DD,留空=現行")
                gr.Examples(
                    examples=[
                        [_EXAMPLE_FACTS[k] for k, _ in _FIELD_LABELS],
                        [_DOG_FACTS[k] for k, _ in _FIELD_LABELS],
                    ],
                    inputs=field_inputs,
                    label="一鍵案情:深夜喧嘩 / 公寓犬吠",
                )
                btn_prompt = gr.Button("1️⃣ 組裝提示詞(檢索只發生這一次)")
                prompt_out = gr.Code(label="提示詞(複製到任何聊天工具)", language="markdown")
                pasted_in = gr.Textbox(lines=6, label="2️⃣ 把模型回答貼回這裡")
                btn_gates = gr.Button("跑五閘門(用貼上的回答)", variant="primary")
                btn_live = gr.Button("或:本機 Ollama 直接生成+跑閘門")
            with gr.Column(scale=7):
                gates_out = gr.HTML()
        btn_prompt.click(assemble_prompt, [asof_3, *field_inputs], prompt_out)
        btn_gates.click(
            run_gates_on_pasted, [pasted_in, user_text_in, asof_3, *field_inputs], gates_out
        )
        btn_live.click(run_gates_live, [user_text_in, asof_3, *field_inputs], gates_out)

    with gr.Tab("🕰️ 檢索 + Time-slice"):
        gr.Markdown(
            "同一組事實、兩個時點——庫內社維法§72 只有 **2025-06-11 生效版**,"
            "在 2024 時點會於排序前就被 point-in-time filter 排除。"
        )
        q_in = gr.Textbox(value=DEFAULT_QUERY, label="事實描述(檢索查詢)")
        with gr.Row():
            asof_2 = gr.Textbox(value="", label="as-of 日期", placeholder="YYYY-MM-DD,留空=現行", scale=3)
            btn_retr = gr.Button("檢索", variant="primary", scale=1)
            btn_cmp = gr.Button("現行 vs 2024-06-01 對照", scale=2)
        out_retr = gr.HTML()
        btn_retr.click(explore_retrieval, [q_in, asof_2], out_retr)
        btn_cmp.click(compare_timeslice, [q_in], out_retr)

    with gr.Tab("📊 評測數字"):
        gr.HTML(STATS)
        gr.Markdown(load_results_md())

    gr.HTML(FOOTER)
    demo.load(check_citations, [ans_in, asof_1], out_check)
    demo.load(compare_timeslice, [q_in], out_retr)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft(primary_hue="indigo"), css=CSS)
