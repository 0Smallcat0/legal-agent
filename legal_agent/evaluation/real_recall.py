"""Retrieval recall on REAL user wording (SPEC §4.2, Tier-1 companion).

The golden set scores the pipeline on cases written FOR the pipeline. This
harness scores retrieval on 168 problems typed into the assistant as ordinary
people type them — by the AUTHOR, not by outside users (`evals/HISTORY.md` §A6
and §A7 name the first twelve). Vocabulary rows were curated against them
through 2026-07-31, so this is a TUNED-ON number (in the sense RESULTS.md
uses for 25/27).

Deliberately narrow:
  * input is the user's own turns, so the number does not depend on how well
    the intake extracted facts that day;
  * only retrieval runs — no LLM, no network — so it is deterministic and cheap;
  * scoring is hit@k on articles a careful person would want surfaced, each
    verified to exist verbatim in the corpus before it was written down.

It measures RECALL, not legal correctness. A hit means the article reached the
window the model may cite from; what the model then does with it is graded by
the golden set and, for the parts that must be right, by the gates.

Confirm the printed dense_fallbacks is 0 before comparing to a published
number: without dense retrieval the hybrid silently degrades to pure BM25.

Run:  python -m legal_agent.evaluation.real_recall [evals/real_sessions.json]
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from legal_agent.config import PROJECT_ROOT
from legal_agent.evaluation import corpus_connection


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
    # Queries whose dense half silently failed and fell back to pure BM25.
    dense_fallbacks: int = 0

    @property
    def expected_total(self) -> int:
        return sum(len(c.expected) for c in self.cases)

    @property
    def hit_total(self) -> int:
        return sum(len(c.hit) for c in self.cases)

    @property
    def rate(self) -> float:
        return (self.hit_total / self.expected_total) if self.expected_total else 0.0

    # ── window cost: what the reader wades through ──────────────────────────
    # Without this a wider window always looks free. `expected_statutes` is not
    # an exhaustive relevance label, so absolute precision is a FLOOR; only a
    # comparison of settings on a fixed case set is meaningful.
    @property
    def window_total(self) -> int:
        return sum(len(c.window) for c in self.cases)

    @property
    def precision(self) -> float:
        """Share of delivered articles that were expected. A FLOOR (see above)."""
        return (self.hit_total / self.window_total) if self.window_total else 0.0

    @property
    def unexpected_per_session(self) -> float:
        """Articles per session outside the expectation — the wading cost."""
        if not self.cases:
            return 0.0
        return (self.window_total - self.hit_total) / len(self.cases)

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
        lines.append(
            f"視窗成本:每次諮詢送出 {self.window_total / max(len(self.cases), 1):.1f} 條,"
            f"其中 {self.unexpected_per_session:.1f} 條不在期待清單內"
            f"(precision 下限 {self.precision:.0%})"
            "——期待清單不是完整的相關性標註,故此為下限;跨設定比較才有意義。"
        )
        if self.dense_fallbacks:
            lines.append(
                f"⚠ 這個數字不是混合檢索的:{self.dense_fallbacks}/{len(self.cases)} "
                "個查詢的 dense 半邊失敗並退回純 BM25(Ollama 未載入 bge-m3?)。"
                "重跑前先確認 Ollama,否則此數不可與已發布數字相比。"
            )
        else:
            lines.append("dense 全程參與(0 次退回),此數可與已發布數字相比。")
        return "\n".join(lines)


def load_cases(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_real_recall(path, conn=None, k: int | None = None) -> RecallReport:
    """Retrieve for every case and score hit@k. `conn` defaults to the corpus."""
    from legal_agent.retrieval.retriever import (
        DEFAULT_K,
        dense_fallback_count,
        reset_dense_fallbacks,
        retrieve,
    )

    reset_dense_fallbacks()
    with corpus_connection(conn) as conn:
        cases = []
        for case in load_cases(path):
            expected = list(case.get("expected_statutes", []))
            found = retrieve(case["query"], k=DEFAULT_K if k is None else k, conn=conn)
            window = [f"{s.statute_id}{s.article_no}" for s in found]
            cases.append(CaseRecall(
                id=case.get("id", ""),
                label=case.get("label", case.get("id", "")),
                expected=expected,
                hit=[e for e in expected if e in window],
                missed=[e for e in expected if e not in window],
                window=window,
            ))
    return RecallReport(cases, dense_fallbacks=dense_fallback_count())


if __name__ == "__main__":   # python -m legal_agent.evaluation.real_recall [path]
    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()
    import sys as _sys

    target = _sys.argv[1] if len(_sys.argv) > 1 else PROJECT_ROOT / "evals" / "real_sessions.json"
    print(run_real_recall(target).render())
