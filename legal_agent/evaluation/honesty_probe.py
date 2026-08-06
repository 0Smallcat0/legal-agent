"""Honesty tier, both directions (evals/RESULTS.md, 2026-08-06).

The golden set carries 5 out-of-scope cases. That is enough to notice the tier
is over-confident and far too few to decide anything: a signal tuned to separate
5 cases is fitted, and this project retracted a published number the day before
for exactly that. So the probe is a purpose-built ruler with both error
directions in it:

    20 out-of-scope   — each governed by a statute verified ABSENT from the
                        corpus's statute_ids. Refusing is correct.
    15 in-scope, thin — each expecting an article verified verbatim IN the
                        corpus, phrased the way a layperson phrases it.
                        Refusing is a false refusal: the answer was there and
                        the reader was turned away.

Two numbers come out, and they trade against each other. Reporting only the
first is how the floor at 70 spent a week refusing 勞基法§11 資遣 (top 39.19)
while answering 15 of 20 questions the corpus cannot support.

Deliberately narrow, like real_recall:
  * retrieval only — the tier is decided from scores BEFORE the LLM, so this
    needs no model and reproduces exactly;
  * the query is assembled exactly as `stage3.run_stage3` assembles it, so the
    numbers are what the live tier sees rather than an approximation;
  * `dense_fallbacks` is reported, because a silently BM25-only run is a
    different measurement wearing the same number.

Run:  python -m legal_agent.evaluation.honesty_probe [evals/honesty_probe_v1.json]
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CASES = "evals/honesty_probe_v1.json"


@dataclass
class ProbeCase:
    id: str
    expected_tier: str
    must_not_refuse: bool
    absent_statute: str | None
    tier: str
    top_score: float
    lexicon_hit: bool
    window: list[str]

    @property
    def refused(self) -> bool:
        return self.tier == "insufficient"


@dataclass
class ProbeReport:
    cases: list[ProbeCase]
    dense_fallbacks: int = 0

    @property
    def out_of_scope(self) -> list[ProbeCase]:
        return [c for c in self.cases if c.expected_tier == "insufficient"]

    @property
    def in_scope(self) -> list[ProbeCase]:
        return [c for c in self.cases if c.must_not_refuse]

    @property
    def refused_out_of_scope(self) -> int:
        return sum(1 for c in self.out_of_scope if c.refused)

    @property
    def falsely_refused(self) -> int:
        return sum(1 for c in self.in_scope if c.refused)

    def render(self) -> str:
        lines = [
            "═══════ 誠實分級雙向探針(僅檢索,不呼叫模型) ═══════", "", "【範圍外:應拒答】",
        ]
        for c in self.out_of_scope:
            mark = "REFUSED " if c.refused else "ANSWERED"
            lines.append(
                f"   {mark} {c.id:30s} top {c.top_score:7.2f}  tier {c.tier:12s}"
                f"  缺席法規 {c.absent_statute or '-'}"
            )
        lines.append("")
        lines.append("【語料內但詞彙弱:不得拒答】")
        for c in self.in_scope:
            mark = "誤拒 <-- " if c.refused else "ok       "
            lines.append(
                f"   {mark} {c.id:30s} top {c.top_score:7.2f}  tier {c.tier:12s}"
                f"  首條 {c.window[0] if c.window else '(無)'}"
            )
        oos, ins = self.out_of_scope, self.in_scope
        lines += [
            "",
            f"範圍外拒答:{self.refused_out_of_scope}/{len(oos)}"
            "——只攔得住 coverage 表列舉過的缺席法規;沒被列舉、"
            "使用者也沒說出法規名的問題仍會被回答。",
            f"語料內誤拒:{self.falsely_refused}/{len(ins)}"
            "——條文就在語料裡,讀者卻被擋掉,這是比過度自信更貴的一邊。",
        ]
        if self.dense_fallbacks:
            lines.append(
                f"⚠ 這個數字不是混合檢索的:{self.dense_fallbacks}/{len(self.cases)} "
                "個查詢的 dense 半邊失敗並退回純 BM25(Ollama 未載入 bge-m3?),"
                "不可與已發布數字相比。"
            )
        else:
            lines.append("dense 全程參與(0 次退回),此數可與已發布數字相比。")
        return "\n".join(lines)


def run_honesty_probe(path=DEFAULT_CASES, conn=None) -> ProbeReport:
    """Grade every probe case exactly as Stage 3 would, retrieval only."""
    from legal_agent.anti_hallucination.honesty import grade_honesty
    from legal_agent.dialogue.stage3 import assemble_dense_query, assemble_fact_query
    from legal_agent.retrieval import retriever
    from legal_agent.retrieval.lexicon import expansions

    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    retriever.reset_dense_fallbacks()
    own = None
    if conn is None:
        from legal_agent.config import DB_PATH
        from legal_agent.data.database import connect

        own = connect(DB_PATH)
        conn = own
    try:
        results = []
        for case in cases:
            facts = dict(case.get("facts", {}))
            # Mirrors run_stage3: the distilled facts plus the user's own ask.
            fact_query = assemble_fact_query(facts)
            ask = (case.get("question") or "").strip()
            if ask and ask not in fact_query:
                fact_query = f"{fact_query}  {ask}" if fact_query else ask
            dense_query = assemble_dense_query(facts)
            if dense_query is not None and ask and ask not in dense_query:
                dense_query = f"{dense_query}  {ask}"

            scored = retriever.retrieve_scored(
                fact_query, None, conn=conn, dense_query=dense_query,
            )
            retrieved = [s for s, _ in scored]
            scores = [sc for _, sc in scored]
            phrases = expansions(fact_query)
            lexicon_hit = any(
                p in (s.content or "") for s in retrieved for p in phrases
            )
            results.append(ProbeCase(
                id=case.get("id", ""),
                expected_tier=case.get("expected_tier", ""),
                must_not_refuse=bool(case.get("must_not_refuse")),
                absent_statute=case.get("absent_statute"),
                tier=grade_honesty(
                    retrieved, scores, lexicon_hit=lexicon_hit, query=fact_query,
                ),
                top_score=max(scores) if scores else 0.0,
                lexicon_hit=lexicon_hit,
                window=[f"{s.statute_id}{s.article_no}" for s in retrieved],
            ))
    finally:
        if own is not None:
            own.close()
    return ProbeReport(results, dense_fallbacks=retriever.dense_fallback_count())


if __name__ == "__main__":   # python -m legal_agent.evaluation.honesty_probe [path]
    import sys as _sys

    from legal_agent.evaluation import enable_utf8_stdout

    enable_utf8_stdout()
    target = _sys.argv[1] if len(_sys.argv) > 1 else DEFAULT_CASES
    print(run_honesty_probe(target).render())
