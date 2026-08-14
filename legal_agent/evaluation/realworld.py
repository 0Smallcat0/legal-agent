"""Retrieval and refusal, scored against disputes that already ENDED (spec §4.2).

Every other harness in this project grades the system against expectations this
project wrote. That is a closed loop: the same hand that built the retriever
decided which article should have surfaced. This one closes a different loop —
the cases come from government dispute-resolution case tables, and the article
each case turns on is the one the deciding body ITSELF cited in its 法令依據
column. Nobody here chose it.

Two numbers come out, and they answer the two halves of the real question a
person has before deciding whether to pay a lawyer:

  * hit@k  — did the article the authority actually applied reach the window
             the model may cite from?
  * refusal — when it did NOT, did the system say so, or answer anyway?

What this refuses to measure: whether the ANSWER's reasoning matches what
actually happened. `--answers` prints the model's 分析研判 beside the recorded
outcome for a human to compare, and never scores it — the same refusal
golden_set.py makes about legal correctness. A harness that auto-graded legal
reasoning would be the exact sin this project exists to avoid.

Label provenance is tracked and NOT pooled. Cases whose source table published
its own 法令依據 are `official`; cases where this project inferred the article
from a narrative outcome are `derived` and are reported separately, because a
number is only as external as its weakest label.

Run:  python -m legal_agent.evaluation.realworld [evals/realworld_v1.json]
      python -m legal_agent.evaluation.realworld --answers   # + LLM, human read
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CASES = "evals/realworld_v1.json"


@dataclass
class CaseOutcome:
    id: str
    domain: str
    label_source: str
    expected: list[str]
    hit: list[str]
    window: list[str]
    tier: str
    real_outcome: str
    analysis: str | None = None

    @property
    def missed(self) -> list[str]:
        return [e for e in self.expected if e not in self.hit]

    @property
    def refused(self) -> bool:
        return self.tier == "insufficient"

    @property
    def silent_miss(self) -> bool:
        """Missed every governing article AND answered anyway — the shape that
        sends a person into a dispute believing they are covered."""
        return not self.hit and not self.refused


@dataclass
class OutcomeReport:
    cases: list[CaseOutcome]
    dense_fallbacks: int = 0
    sources: list[dict] = field(default_factory=list)

    def subset(self, label_source: str) -> list[CaseOutcome]:
        return [c for c in self.cases if c.label_source == label_source]

    @staticmethod
    def _rate(cases: list[CaseOutcome]) -> tuple[int, int]:
        return (
            sum(len(c.hit) for c in cases),
            sum(len(c.expected) for c in cases),
        )

    def render(self) -> str:
        lines = ["═══════ 真實已結案爭議:檢索與拒答(輸入只有當事人最初陳述) ═══════"]
        for label in ("official", "derived"):
            group = self.subset(label)
            if not group:
                continue
            head = {
                "official": "外部標註(案例表自帶「法令依據」欄)",
                "derived": "本專案反推的標註(僅供參考,不計入 headline)",
            }[label]
            lines.append(f"\n── {head} ── {len(group)} 案")
            for c in group:
                flag = "拒答" if c.refused else ("靜默漏接" if c.silent_miss else "    ")
                lines.append(
                    f"\n【{c.id}】{len(c.hit)}/{len(c.expected)} tier={c.tier} {flag}"
                )
                for ref in c.expected:
                    lines.append(f"   {'HIT ' if ref in c.hit else 'MISS'} {ref}")
                if c.analysis is not None:
                    lines.append(f"   [模型分析] {c.analysis.strip()[:200]}")
                    lines.append(f"   [真實結局] {c.real_outcome[:200]}")
            hit, total = self._rate(group)
            refused = sum(1 for c in group if c.refused)
            silent = sum(1 for c in group if c.silent_miss)
            pct = f"{hit / total:.0%}" if total else "n/a"
            lines.append(
                f"\n   hit@k {hit}/{total}({pct})"
                f" · 拒答 {refused}/{len(group)}"
                f" · 靜默漏接 {silent}/{len(group)}"
            )
        lines.append("")
        lines.append(
            "hit@k 量的是「權責機關實際引用的條文有沒有進入模型可引用的窗口」。"
            "靜默漏接 = 一條都沒命中卻照樣作答,是這裡最該看的數字。"
        )
        lines.append(
            "本 harness 不自動評分法律推論是否正確 —— --answers 只把分析與真實結局"
            "並排印出來給人讀,與 golden_set 對法律正確性的拒絕相同。"
        )
        if self.dense_fallbacks:
            lines.append(
                f"⚠ 這個數字不是混合檢索的:{self.dense_fallbacks}/{len(self.cases)} "
                "個查詢的 dense 半邊失敗並退回純 BM25(Ollama 未載入 bge-m3?)。"
            )
        else:
            lines.append("dense 全程參與(0 次退回),此數可與已發布數字相比。")
        for src in self.sources:
            lines.append(f"來源[{src.get('label_source')}] {src.get('title')} — {src.get('url')}")
        return "\n".join(lines)


def load_document(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ref(entry: dict) -> str:
    return f"{entry['statute_id']}{entry['article_no']}"


class BadLabelError(ValueError):
    """A governing article does not exist in the corpus under that name."""


def check_labels(document: dict, conn) -> None:
    """Every governing article must exist in the corpus, or the whole run is a
    bad ruler: a label the corpus can never match scores 0 no matter how good
    retrieval is, and the harness would report a confident wrong miss.

    This is not hypothetical. The first run of this file labelled 民法 as
    「中華民國民法」 (the corpus spells 刑法 that way, 民法 not) and published a
    fake 1/9. Fail loudly instead — see RESULTS.md §5 on bad rulers.
    """
    rows = {
        f"{sid}{ano}"
        for sid, ano in conn.execute("SELECT statute_id, article_no FROM statutes")
    }
    unknown = sorted({
        _ref(entry)
        for case in document["cases"]
        for entry in case["governing_statutes"]
        if _ref(entry) not in rows
    })
    if unknown:
        raise BadLabelError(
            "這些標註的條文不存在於 corpus,分數會是假的 miss,先修標註或補語料:"
            + "、".join(unknown)
        )


def run_realworld(path=DEFAULT_CASES, conn=None, k: int | None = None,
                  llm=None) -> OutcomeReport:
    """Retrieve for every case, grade the honesty tier, and score hit@k against
    the article the deciding authority cited. `llm` is optional and only feeds
    the side-by-side print — it never affects a score."""
    from legal_agent.anti_hallucination.honesty import grade_honesty
    from legal_agent.retrieval.lexicon import expansions
    from legal_agent.retrieval.retriever import (
        DEFAULT_K,
        dense_fallback_count,
        reset_dense_fallbacks,
        retrieve_scored,
    )

    reset_dense_fallbacks()
    document = load_document(path)
    own = None
    if conn is None:
        from legal_agent.config import DB_PATH
        from legal_agent.data.database import connect

        own = connect(DB_PATH)
        conn = own
    try:
        check_labels(document, conn)
        results = []
        for case in document["cases"]:
            query = case["initial_text"]
            scored = retrieve_scored(query, k=k or DEFAULT_K, conn=conn)
            retrieved = [s for s, _ in scored]
            scores = [sc for _, sc in scored]
            window = [f"{s.statute_id}{s.article_no}" for s in retrieved]
            phrases = expansions(query)
            lexicon_hit = any(
                phrase in (s.content or "") for s in retrieved for phrase in phrases
            )
            tier = grade_honesty(retrieved, scores, lexicon_hit=lexicon_hit, query=query)
            expected = [_ref(e) for e in case["governing_statutes"]]
            analysis = None
            if llm is not None:
                from legal_agent.dialogue.stage3 import run_stage3

                stage3 = run_stage3({"problem": query}, llm=llm, conn=conn,
                                    user_text=query)
                analysis = stage3.analysis_section or stage3.answer
            results.append(CaseOutcome(
                id=case["id"],
                domain=case.get("domain", ""),
                label_source=case.get("label_source", "derived"),
                expected=expected,
                hit=[e for e in expected if e in window],
                window=window,
                tier=tier,
                real_outcome=case["real_outcome"],
                analysis=analysis,
            ))
    finally:
        if own is not None:
            own.close()
    return OutcomeReport(
        results,
        dense_fallbacks=dense_fallback_count(),
        sources=document.get("sources", []),
    )


if __name__ == "__main__":   # python -m legal_agent.evaluation.realworld [path]
    import sys as _sys

    from legal_agent.evaluation import enable_utf8_stdout

    enable_utf8_stdout()
    argv = [a for a in _sys.argv[1:] if a != "--answers"]
    want_answers = "--answers" in _sys.argv[1:]
    target = argv[0] if argv else DEFAULT_CASES
    runtime_llm = None
    if want_answers:
        from legal_agent.run import build_runtime_llm

        runtime_llm = build_runtime_llm()
    print(run_realworld(target, llm=runtime_llm).render())
