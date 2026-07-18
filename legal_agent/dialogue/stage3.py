"""Stage 3 — assemble facts -> retrieve ONCE -> LLM answer (retrieval-first) ->
verify, with Mechanisms 3/4/5 wired in (spec §3.2, §3.3, §2.2/§2.3/§2.4/§2.5/§2.6).

Mechanism 4 is now THREE sections sorted by 位階: 法律明文 (rank<=3) / 實務見解
(rank 4-5, must carry a 非法律明文 disclaimer) / 分析研判. The LLM is
DEPENDENCY-INJECTED and bound LAZILY (after the insufficient short-circuit).
Retrieval fires EXACTLY ONCE (retrieve_scored) on the complete fact set (§3.3).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from legal_agent import config
from legal_agent.anti_hallucination import verifier
from legal_agent.anti_hallucination.answer_structure import PRACTICE_DISCLAIMER, split_sections
from legal_agent.anti_hallucination.honesty import (
    INSUFFICIENT_TEXT,
    MARGINAL_PREFIX,
    grade_honesty,
)
from legal_agent.anti_hallucination.sycophancy import check_premise
from legal_agent.anti_hallucination.verifier import VerificationResult
from legal_agent.data.models import Statute
from legal_agent.retrieval import retriever

# Mechanism 1 — retrieval-first (§2.2). Mechanism 4 — THREE-section 法律明文 / 實務見解
# / 分析研判 by 位階 (§2.5). Mechanism 5 — anti-sycophancy (§2.6).
SYSTEM_PROMPT = (
    "你是協助理解台灣法律的助理。你只能引用我在下方提供的法源;不得憑記憶補充、"
    "或引用未提供的內容。若提供的資料不足以回答,必須明說「現有資料不足」並建議"
    "諮詢律師。回答時標明所依據的條號或文號。以下為檢索到的現行有效法源(逐字),"
    "每一筆都標了「位階(hierarchy_level)」;另附使用者陳述的事實。"
    "\n\n【回答格式(務必遵守;三段標題都要出現)】請依每筆法源的位階,放進正確段落:"
    "\n「法律明文」:只放 憲法 / 法律 / 命令(位階較高者);寫出條號與能被逐字條文"
    "直接支持的陳述。"
    "\n「實務見解」:放 函釋 / 行政實務見解;本段開頭必須先寫一行"
    "「以下為主管機關實務見解/處理原則,非法律明文,僅供參考」,再列出文號與內容。"
    "切勿把實務見解寫進「法律明文」。"
    "\n「分析研判」:你的推論與研判;此段為模型推論、僅供參考,並非法律本身。"
    "\n(若某段沒有對應的檢索結果,仍要保留該段標題並寫「(無)」。)"
    "\n\n【立場(重要)】當使用者的陳述包含錯誤的法律判斷(例如把不構成的行為說成"
    "犯罪、或斷定「一定告得成」「他一定要賠」),糾正其錯誤優先於附和。請說明法律"
    "實際上如何規定,而不是使用者想聽的話。"
)


@dataclass
class Stage3Result:
    answer: str
    retrieved: list[Statute]
    verifications: list[VerificationResult]
    retrieval_count: int
    retrieval_scores: list[float] | None = None
    flagged_count: int = 0
    # Mechanism 3 — three-tier honesty.
    honesty_tier: str = "normal"        # "normal" | "marginal" | "insufficient"
    honesty_label: str | None = None
    # Mechanism 4 — three-section separation.
    law_section: str | None = None          # 法律明文 (rank<=3)
    practice_section: str | None = None     # 實務見解 (rank 4-5)
    analysis_section: str | None = None     # 分析研判
    sections_ok: bool = True                # False if any of the three headings is missing
    practice_disclaimer_ok: bool = True     # False if 實務見解 present without the 非法律明文 label
    # Mechanism 5 — anti-sycophancy.
    premise_flag: bool = False


def assemble_fact_query(collected_facts: dict) -> str:
    return "  ".join(str(v).strip() for v in collected_facts.values() if str(v).strip())


# GENERIC-flow content fields carry the semantic core; process facts
# (timeline, actions_taken) are dense noise — measured: 勞基§24 ranks 34 on
# the full fact string, 5 on problem+goal alone. Scenario checklists (noise)
# deliberately DON'T focus: there 「報過警」/「管委會」 are content, and
# focusing measurably hurt golden coverage — their dense half keeps the full
# fact string (assemble returns None).
_DENSE_QUERY_FIELDS = ("problem", "goal")


def assemble_dense_query(collected_facts: dict) -> str | None:
    """Focused text for the dense half of hybrid retrieval; None -> the full
    fact query is used for both halves (nothing focused to offer)."""
    parts = [
        str(collected_facts[f]).strip()
        for f in _DENSE_QUERY_FIELDS
        if str(collected_facts.get(f) or "").strip()
    ]
    return "  ".join(parts) or None


def _render_articles(retrieved: list[Statute]) -> str:
    if not retrieved:
        return "(未檢索到任何法源)"
    return "\n\n".join(
        f"【{s.statute_id}{s.article_no}｜位階:{s.hierarchy_level}】"
        f"(生效日 {s.effective_from};來源 {s.source_url})\n{s.content}"
        for s in retrieved
    )


def _render_facts(collected_facts: dict) -> str:
    if not collected_facts:
        return "(無)"
    return "\n".join(f"- {k}: {v}" for k, v in collected_facts.items())


def build_model_input(retrieved: list[Statute], collected_facts: dict) -> str:
    return (
        SYSTEM_PROMPT
        + "\n\n===== 檢索到的現行有效法條(逐字) =====\n"
        + _render_articles(retrieved)
        + "\n\n===== 使用者陳述的事實 =====\n"
        + _render_facts(collected_facts)
        + "\n\n請根據上述法源回答;若不足以回答,請說「現有資料不足」。"
    )


def default_anthropic_llm() -> Callable[[str], str]:
    """Bind the REAL Anthropic client (built here, not at import). NEVER called in
    tests — run_stage3 is always handed a fake `llm` there."""
    try:
        from dotenv import load_dotenv
        load_dotenv(config.PROJECT_ROOT / ".env")
    except Exception:
        pass

    import anthropic  # lazy: tests never need the SDK imported

    key = config.get_anthropic_api_key()
    if not key:
        raise RuntimeError(
            f"{config.ANTHROPIC_API_KEY_ENV} not set — put it in a (gitignored) .env "
            "or the environment before running Stage 3 for real."
        )
    client = anthropic.Anthropic(api_key=key)

    def llm(prompt: str) -> str:
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )

    return llm


def run_stage3(
    collected_facts: dict,
    llm: Callable[[str], str] | None = None,
    as_of_date: str | None = None,
    conn=None,
    user_text: str | None = None,
) -> Stage3Result:
    """Assemble facts -> retrieve ONCE -> (Mech 3 grade) -> LLM (retrieval-first)
    -> verify, splitting the answer into 法律明文/實務見解/分析研判 (Mech 4) and flagging
    an asserted premise (Mech 5). Flagged citations are NOT deleted/regenerated (§2.3).
    """
    fact_query = assemble_fact_query(collected_facts)
    scored = retriever.retrieve_scored(
        fact_query, as_of_date, conn=conn,
        dense_query=assemble_dense_query(collected_facts),
    )  # EXACTLY ONCE
    retrieved = [s for s, _ in scored]
    scores = [sc for _, sc in scored]

    premise_flag = check_premise(user_text) if user_text else False
    tier = grade_honesty(retrieved, scores)

    if tier == "insufficient":   # short-circuit BEFORE the LLM (never fabricate)
        return Stage3Result(
            answer=INSUFFICIENT_TEXT,
            retrieved=[], verifications=[],
            retrieval_count=0, retrieval_scores=[], flagged_count=0,
            honesty_tier="insufficient", honesty_label=INSUFFICIENT_TEXT,
            law_section=None, practice_section=None, analysis_section=None,
            sections_ok=False, practice_disclaimer_ok=False,
            premise_flag=premise_flag,
        )

    if llm is None:              # bind the real LLM LAZILY, only now that we need it
        llm = default_anthropic_llm()

    answer = llm(build_model_input(retrieved, collected_facts))

    honesty_label = None
    if tier == "marginal":
        honesty_label = MARGINAL_PREFIX
        answer = MARGINAL_PREFIX + "\n" + answer

    verifications = verifier.verify_answer(answer, retrieved, as_of_date)
    flagged = sum(1 for v in verifications if v.flagged)

    law_section, practice_section, analysis_section = split_sections(answer)
    sections_ok = all(s is not None for s in (law_section, practice_section, analysis_section))
    practice_disclaimer_ok = practice_section is not None and PRACTICE_DISCLAIMER in practice_section

    return Stage3Result(
        answer=answer,
        retrieved=retrieved,
        verifications=verifications,
        retrieval_count=len(retrieved),
        retrieval_scores=scores,
        flagged_count=flagged,
        honesty_tier=tier,
        honesty_label=honesty_label,
        law_section=law_section,
        practice_section=practice_section,
        analysis_section=analysis_section,
        sections_ok=sections_ok,
        practice_disclaimer_ok=practice_disclaimer_ok,
        premise_flag=premise_flag,
    )
