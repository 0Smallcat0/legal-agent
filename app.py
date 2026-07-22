"""Gradio demo — clinic-style legal consultation, with the gates as the trust layer.

The first tab IS the product: describe the problem, the system runs the
pre-designed intake (rule-based, no retrieval), and only when the facts are
complete does it retrieve ONCE and produce the answer — applicable statutes
(verbatim, ranked), the graded explanation, and the low-cost-first action
ladder. Citation verification appears as a quiet status line under the
answer, not as the headline: the user came for the answer; the gates are why
the answer can be trusted.

Stages 1–2 and everything deterministic (retrieval, honesty tier, ladder,
verbatim statutes) work with NO model at all, so the full consultation flow
runs on HF Spaces free CPU with zero keys. A local Ollama, when present,
additionally writes the 分析研判 narrative.

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
from legal_agent.data.seed import seed_source_hierarchy
from legal_agent.data.source_ingest import load_proposals
from legal_agent.dialogue.flow import SessionState, Stage, advance_to_stage3, handle_turn
from legal_agent.dialogue.ollama_llm import ollama_available, ollama_llm
from legal_agent.retrieval.retriever import retrieve_scored

# ── content ──────────────────────────────────────────────────────────────────
GREETING = (
    "請描述你遇到的問題。例:退租後房東不退押金、公司用責任制不給加班費、"
    "網購瑕疵品賣家不退款、樓上半夜噪音。"
)

# A deliberately-broken sample answer mirroring the live 8B model's README-demo
# output: one wrong amount and one TYPO'd statute name (公寀≠公寓) must be
# flagged, while 噪音管制法第8條 must PASS — it was out of corpus in the
# 11-article era but corpus v2 carries the full statute, so it is now a correct
# citation (re-verified 2026-07-21; the tab copy must not promise three flags).
SAMPLE_BAD_ANSWER = (
    "依社會秩序維護法第72條,深夜喧嘩可處新臺幣六萬元以下罰鍰。"
    "另依噪音管制法第8條及公寀大廈管理條例第16條,亦有相關管制。"
)
SAMPLE_GOOD_ANSWER = (
    "依社會秩序維護法第72條,製造噪音或深夜喧嘩妨害公眾安寧、不聽禁止者,"
    "可處新臺幣一萬元以下罰鍰。"
)
# A second broken sample, from the everyday-law side of the corpus. ALL THREE
# defects are ones the verifier actually catches — a demo must not advertise
# a catch it cannot make: an invented fine (§7 caps the deposit and prescribes
# no 罰鍰), the 七日 hesitation period claimed as 十四日 (catchable since the
# period content pass, 2026-07-21 — the very defect this sample had to DROP on
# 07-19), and a nonexistent article number.
SAMPLE_BAD_ANSWER_2 = (
    "依租賃住宅市場發展及管理條例第7條,房東不退押金可處新臺幣五萬元罰鍰;"
    "依消費者保護法第19條,網購商品得於十四日內退回解約;"
    "另依消費者保護法第99條,前述權利不得預先拋棄。"
)
# Retrieval tab default: a noise complaint, because that tab demonstrates the
# POINT-IN-TIME filter and 社維法§72's current slice took effect 2025-06-11.
DEFAULT_QUERY = "深夜喧嘩爭吵 半夜 幾乎每天 公寓大廈 管理委員會"
# Everyday queries for the same tab — they show corpus breadth (rent, labor,
# consumer, inheritance), where the date makes no difference.
RETRIEVAL_EXAMPLES = [
    ["退租後房東不退押金,說要抵違約金"],
    ["公司說責任制,加班沒有加班費"],
    ["網購買到瑕疵品,賣家不讓退貨"],
    ["父親過世,兄弟姊妹要分遺產"],
]

# Intake field keys → 中文 labels. Covers BOTH checklists: the 住宅噪音
# scenario and the generic flow every other problem falls through to.
_FIELD_ZH = {
    # 通用流程
    "problem": "問題與對象",
    "goal": "希望的結果",
    "timeline": "時間與經過",
    # 住宅噪音情境
    "noise_type": "噪音類型",
    "timing": "時段與頻率",
    "building_type": "建物型態",
    "impact": "影響",
    "evidence": "證據",
    # 兩者共用
    "actions_taken": "已採取行動",
}

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
  padding:8px 14px; margin:10px 0; font-size:13.5px; opacity:.92}

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
.retr-card details {margin-top:5px; font-size:12.5px}
.retr-card summary {cursor:pointer; opacity:.6}
.retr-card pre {white-space:pre-wrap; font-size:12.5px; border-radius:6px; padding:10px;
  margin-top:6px; background:var(--background-fill-secondary); line-height:1.7}
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
  <p class="sub">問診式法律諮詢:先收集事實,資料齊備才檢索一次並作答;每筆引用經「存在、內容、時效」查核。</p>
  <p class="meta">180 項測試通過 · 植入錯誤抓取率 10,435/10,435(零誤報) · 不需任何 API 金鑰</p>
</div>
"""

FOOTER = """
<p class="disclaimer">工程實驗,非法律意見,不能取代律師。法源為全國法規資料庫官方
公開資料逐字匯入(11 部民生法規 2,560 條+警察分工實務指引);「住宅噪音」有專屬問診流程,
其他問題走通用流程。資料庫未涵蓋的領域,系統會直接說不知道。</p>
"""


# ── data bootstrap ───────────────────────────────────────────────────────────
def ensure_db() -> None:
    """Idempotent: build the SQLite schema and load the hand-verified corpus."""
    init_db(config.DB_PATH)
    conn = connect(config.DB_PATH)
    try:
        seed_source_hierarchy(conn)
        # Corpus source of truth = official-XML proposals (2 560 articles across
        # 11 statutes, plus the police routing note and one capped historical
        # slice). The old hand-typed noise_seed is superseded — loading it
        # here would create duplicate current slices next to the XML rows.
        for proposal_name in ("moj_bulk_v1_proposal.json", "noise_routing_proposal.json"):
            proposal_path = config.CORPUS_DIR / proposal_name
            if proposal_path.exists():
                load_proposals(proposal_path, conn)
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


def _retr_cards(scored, with_fulltext: bool = False) -> str:
    if not scored:
        return '<div class="verdict insufficient">檢索結果為空——系統不作答,不編造</div>'
    top = max(sc for _, sc in scored) or 1.0
    cards = []
    for s, sc in scored:
        width = max(4, int(round(sc / top * 100)))
        excerpt = escape(s.content[:56].replace("\n", " "))
        fulltext = (
            f'<details><summary>條文全文</summary><pre>{escape(s.content)}</pre></details>'
            if with_fulltext else ""
        )
        cards.append(
            '<div class="retr-card"><div class="head">'
            f'<span class="ref">{escape(s.statute_id + s.article_no)}</span>'
            f'<span class="meta">{escape(s.hierarchy_level)} · 生效 {escape(s.effective_from)}'
            f" · 相關度 {sc:.1f}</span></div>"
            f'<div class="excerpt">{excerpt}…</div>{fulltext}'
            f'<div class="bar"><i style="width:{width}%"></i></div></div>'
        )
    return "".join(cards)


def _clean_section(title: str, body: str) -> str:
    """Strip the model's markdown-bold remnants and duplicated heading."""
    base = title.split("(")[0]
    text = body
    for _ in range(3):
        text = text.strip().strip("*:：」「").strip()
        if text.startswith(base):
            text = text[len(base):]
    return text.strip()


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
                f'<div class="b">{escape(_clean_section(title, body))}</div></div>'
            )
    if not blocks:   # model skipped the headings — show the raw answer, flagged
        return (
            '<div class="note">模型未依三段格式作答,以下為原文。</div>'
            f'<div class="seccard"><div class="b">{escape(result.answer)}</div></div>'
        )

    # Reference judgments — deterministic join on the retrieved articles,
    # rendered code-side (the model never writes a case number).
    refs = getattr(getattr(result, "stage3", result), "related_judgments", ())
    if refs:
        rows = "".join(
            f"<li>{escape(r.jid)}({escape(r.case_type or '案由不明')})"
            f"— 同引 {escape('、'.join(r.matched))}</li>"
            for r in refs
        )
        blocks.append(
            '<div class="seccard"><div class="t">相關裁判參考(個案見解,非法律明文,僅供參考)</div>'
            f'<div class="b"><ul>{rows}</ul></div></div>'
        )
    return "".join(blocks)


# ── 法律諮詢(clinic flow;Stages 1–2 rule-based, retrieval fires once) ───────
def _fresh_chat() -> list[dict]:
    return [{"role": "assistant", "content": GREETING}]


def _stub_llm(_prompt: str) -> str:
    """No-model fallback: keep the three-section contract, add no citations,
    and say plainly what is and is not machine-generated."""
    return (
        "「法律明文」:未連接語言模型;適用條文見右欄「適用法源」,均為資料庫逐字內容。\n"
        "「實務見解」:以下為主管機關實務見解/處理原則,非法律明文,僅供參考:見右欄所列實務見解來源。\n"
        "「分析研判」:未連接語言模型,不產生推論。啟動本機 Ollama 後重新諮詢,可取得此段分析。"
    )


def _clean_ladder(text: str) -> str:
    """Display-side cleanup of CLI-oriented ladder text (emoji marker, variable name)."""
    return text.replace("👉 ", "").replace("letter_template", "存證信函範本")


def _quiet_verification(vs) -> str:
    if not vs:
        return '<div class="note">引用查核:本回答未含條號引用。</div>'
    flagged = [v for v in vs if v.flagged]
    if not flagged:
        return f'<div class="note">引用查核:{len(vs)} 筆引用全數可回溯至資料庫。</div>'
    return (
        f'<div class="note">引用查核:{len(vs)} 筆引用中 {len(flagged)} 筆有疑慮,逐筆如下。</div>'
        + _cite_cards(flagged)
    )


def _consult_result_html(result) -> str:
    if result.honesty_tier == "insufficient":
        return (
            _tier_bar("insufficient")
            + f'<div class="note">{escape(result.answer)}</div>'
            + '<h4 class="blockhead">一般性處理順序(不涉法條)</h4>'
            + f'<div class="ladder">{escape(_clean_ladder(result.solution_text))}</div>'
        )
    parts = [_tier_bar(result.honesty_tier)]
    if result.premise_flag:
        parts.append(
            '<div class="note">前提提醒:你的描述含法律結論斷言;以下以法規實際規定為準,而非附和。</div>'
        )
    scored = list(zip(result.stage3.retrieved, result.stage3.retrieval_scores or []))
    parts.append('<h4 class="blockhead">適用法源(本次檢索,逐字)</h4>')
    parts.append(_retr_cards(scored, with_fulltext=True))
    parts.append('<h4 class="blockhead">說明</h4>')
    parts.append(_sections_html(result))
    parts.append('<h4 class="blockhead">建議處理順序(低成本優先,訴訟最後)</h4>')
    parts.append(f'<div class="ladder">{escape(_clean_ladder(result.solution_text))}</div>')
    parts.append(_quiet_verification(result.verifications))
    return "".join(parts)


def _ready_summary(state: SessionState) -> str:
    lines = ["事實已收集完成,開始檢索與診斷。", ""]
    lines += [
        f"・{_FIELD_ZH.get(k, k)}:{v}" for k, v in state.collected_facts.items()
    ]
    return "\n".join(lines)


def consult_step(message: str, history: list[dict], state: SessionState):
    message = (message or "").strip()
    if not message:
        return history, state, gr.update(), ""
    if state.stage is Stage.READY_FOR_STAGE3:   # previous case closed — start anew
        history, state = _fresh_chat(), SessionState()

    reply, state = handle_turn(state, message)
    history = history + [{"role": "user", "content": message}]

    if state.stage is not Stage.READY_FOR_STAGE3:
        history.append({"role": "assistant", "content": reply})
        return history, state, gr.update(), ""

    # facts complete: replace the CLI-oriented ready-text with a plain summary,
    # then run the one-shot retrieval + gates + ladder.
    history.append({"role": "assistant", "content": _ready_summary(state)})
    llm = ollama_llm() if ollama_available() else _stub_llm
    conn = connect(config.DB_PATH)
    try:
        result = advance_to_stage3(state, llm=llm, conn=conn)
    finally:
        conn.close()
    history.append({"role": "assistant", "content": "診斷完成,結果見右側。按「重新開始」可諮詢下一件。"})
    return history, state, _consult_result_html(result), ""


def consult_reset():
    return _fresh_chat(), SessionState(), "", ""


# ── 引用查核(獨立工具,無模型) ────────────────────────────────────────────────
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
        f'<div class="verdict {tone}">{len(vs)} 筆引用,{flagged} 筆有疑慮</div>'
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


# ── 評測結果 ─────────────────────────────────────────────────────────────────
STATS = """
<div class="statgrid">
  <div class="stat"><div class="num">10,435/10,435</div><div class="lbl">植入錯誤抓取率(零誤報)</div></div>
  <div class="stat"><div class="num">96%</div><div class="lbl">法條涵蓋率(含部分命中)</div></div>
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

    with gr.Tab("法律諮詢"):
        gr.Markdown("描述問題,依提問補齊事實;資料齊備後,系統檢索一次並給出法源、說明與處理順序。")
        with gr.Row():
            with gr.Column(scale=5):
                chat = gr.Chatbot(value=_fresh_chat(), label="諮詢對話", height=460)
                msg_in = gr.Textbox(label="輸入", lines=2, placeholder="多個問題可分行回答")
                with gr.Row():
                    btn_send = gr.Button("送出", variant="primary")
                    btn_reset = gr.Button("重新開始")
                gr.Examples(
                    examples=[
                        ["退租後房東說房子有損耗,要扣我兩個月押金,合理嗎?"],
                        ["公司說我們是責任制,加班都沒有加班費,這樣合法嗎?"],
                        ["網購買到瑕疵品,賣家不讓我退貨退款,怎麼辦?"],
                        ["樓上鄰居半夜一直搬東西敲打,幾乎每天,我有錄影,報過警但沒用"],
                        ["樓上半夜有腳步聲,這構成恐嚇罪吧,我要告他!"],
                        ["我的品牌名稱被別人搶先註冊商標,可以要回來嗎?"],
                    ],
                    inputs=[msg_in],
                    label="範例開場(最後一則資料庫未涵蓋,系統應誠實說不知道)",
                )
            with gr.Column(scale=7):
                consult_out = gr.HTML(label="諮詢結果")
        consult_state = gr.State(SessionState())
        btn_send.click(
            consult_step, [msg_in, chat, consult_state], [chat, consult_state, consult_out, msg_in]
        )
        msg_in.submit(
            consult_step, [msg_in, chat, consult_state], [chat, consult_state, consult_out, msg_in]
        )
        btn_reset.click(consult_reset, [], [chat, consult_state, consult_out, msg_in])

    with gr.Tab("引用查核"):
        gr.Markdown(
            "獨立工具:檢驗任一 AI 法律回答的引用能否回溯至資料庫 —— "
            "條號是否存在、內容與逐字條文是否相符、在基準日是否仍有效。"
            "預設範例三筆引用中兩處錯誤(金額誇大、法規名稱錯字)會被標記,"
            "另一筆(噪音管制法第8條)為正確引用,應通過查核 —— 抓錯也不誤殺;"
            "第二則是民生法規版(押金罰鍰虛構、七日猶豫期寫成十四日、"
            "消保法條號不存在)。"
        )
        with gr.Row():
            with gr.Column(scale=5):
                ans_in = gr.Textbox(value=SAMPLE_BAD_ANSWER, lines=5, label="回答內容")
                asof_1 = gr.Textbox(value="", label="基準日", placeholder="YYYY-MM-DD,留空為現行")
                btn_check = gr.Button("查核", variant="primary")
                gr.Examples(
                    examples=[
                        [SAMPLE_BAD_ANSWER, ""],
                        [SAMPLE_BAD_ANSWER_2, ""],
                        [SAMPLE_GOOD_ANSWER, ""],
                        [SAMPLE_GOOD_ANSWER, "2024-06-01"],
                    ],
                    inputs=[ans_in, asof_1],
                    label="範例:噪音錯誤版 / 民生錯誤版 / 正確版 / 正確條文但 2024 時點尚未生效",
                )
            with gr.Column(scale=7):
                out_check = gr.HTML()
        btn_check.click(check_citations, [ans_in, asof_1], out_check)

    with gr.Tab("法規檢索"):
        gr.Markdown(
            "資料庫收錄 11 部民生法規、2,560 條條文(民法、刑法、消保法、勞基法、"
            "道交條例、公寓大廈、租賃住宅、家暴法、噪音管制、社維法)。\n\n"
            "同一事實、不同基準日:2025-06-11 生效的社維法第72條,在 2024 時點不會成為候選。"
        )
        q_in = gr.Textbox(value=DEFAULT_QUERY, label="事實描述")
        with gr.Row():
            asof_2 = gr.Textbox(value="", label="基準日", placeholder="YYYY-MM-DD,留空為現行", scale=3)
            btn_retr = gr.Button("檢索", variant="primary", scale=1)
            btn_cmp = gr.Button("現行與 2024-06-01 對照", scale=2)
        gr.Examples(examples=RETRIEVAL_EXAMPLES, inputs=[q_in], label="其他民生範例")
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
