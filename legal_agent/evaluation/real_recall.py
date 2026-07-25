"""Retrieval recall on REAL user wording (SPEC §4.2, Tier-1 companion).

The golden set scores the pipeline on cases written FOR the pipeline. This
harness scores retrieval on nine problems typed into the assistant as ordinary
people type them — the transcripts that exposed most of the 2026-07-25 defect
list (evals/HISTORY.md §6).

Deliberately narrow:
  * input is the user's own turns, so the number does not depend on how well
    the intake extracted facts that day;
  * only retrieval runs — no LLM, no network — so it is deterministic and cheap;
  * scoring is hit@k on articles a careful person would want surfaced, each
    verified to exist verbatim in the corpus before it was written down.

It measures RECALL, not legal correctness. A hit means the article reached the
window the model may cite from; what the model then does with it is graded by
the golden set and, for the parts that must be right, by the gates.

Run:  python -m legal_agent.evaluation.real_recall [evals/real_sessions.json]
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaseRecall:
    id: str
    label: str
    expected: list[str]
    hit: list[str]
    missed: list[str]
    window: list[str]

    @property
    def score(self) -> str:
        return f"{len(self.hit)}/{len(self.expected)}"


@dataclass
class RecallReport:
    cases: list[CaseRecall]

    @property
    def expected_total(self) -> int:
        return sum(len(c.expected) for c in self.cases)

    @property
    def hit_total(self) -> int:
        return sum(len(c.hit) for c in self.cases)

    @property
    def rate(self) -> float:
        return (self.hit_total / self.expected_total) if self.expected_total else 0.0

    def render(self) -> str:
        lines = ["═══════ 真實情境檢索召回(以使用者原話為輸入) ═══════"]
        for c in self.cases:
            lines.append(f"\n【{c.label}({c.id})】 {c.score}")
            for ref in c.expected:
                mark = "HIT " if ref in c.hit else "MISS"
                lines.append(f"   {mark} {ref}")
            lines.append(f"   檢索窗口:{'、'.join(c.window)}")
        lines.append("")
        lines.append(
            f"hit@k 總計:{self.hit_total}/{self.expected_total}({self.rate:.0%})"
            "——量的是「該出現的條文有沒有進入模型可引用的窗口」,不是法律判斷正確性"
        )
        return "\n".join(lines)


def load_cases(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_real_recall(path, conn=None, k: int | None = None) -> RecallReport:
    """Retrieve for every case and score hit@k. `conn` defaults to the corpus."""
    from legal_agent.retrieval.retriever import DEFAULT_K, retrieve

    own = None
    if conn is None:
        from legal_agent.config import DB_PATH
        from legal_agent.data.database import connect

        own = connect(DB_PATH)
        conn = own
    try:
        cases = []
        for case in load_cases(path):
            expected = list(case.get("expected_statutes", []))
            found = retrieve(case["query"], k=k or DEFAULT_K, conn=conn)
            window = [f"{s.statute_id}{s.article_no}" for s in found]
            cases.append(CaseRecall(
                id=case.get("id", ""),
                label=case.get("label", case.get("id", "")),
                expected=expected,
                hit=[e for e in expected if e in window],
                missed=[e for e in expected if e not in window],
                window=window,
            ))
    finally:
        if own is not None:
            own.close()
    return RecallReport(cases)


if __name__ == "__main__":   # python -m legal_agent.evaluation.real_recall [path]
    import sys as _sys

    target = _sys.argv[1] if len(_sys.argv) > 1 else "evals/real_sessions.json"
    print(run_real_recall(target).render())
