"""Tier 1 — Golden Set runner (spec §4.2). Loads human-verified Q&A from a JSON
file, runs each through the pipeline with an INJECTED llm, and scores the ONE
machine-checkable dimension: are the expected statutes surfaced (cited-and-real,
or retrieved)?

CRITICAL: legal-JUDGMENT correctness is HUMAN-compared. This harness does NOT
auto-pass legal correctness — the scorecard shows the agent answer AND the
expected answer SIDE BY SIDE for a human to compare. Only statute coverage is
auto-scored (pass / partial / miss).

Golden file schema (a JSON list of cases):
    {
      "id": str,
      "question": str,
      "as_of_date": "YYYY-MM-DD",        # optional
      "facts": {"noise_type": ..., "building_type": ..., ...},
      "expected_statutes": ["社會秩序維護法第72條", ...],   # corpus-format refs
      "expected_action": str,
      "expected_tier": "normal|marginal|insufficient",   # optional, auto-scored
      "expected_premise_flag": bool,      # optional, auto-scored (Mechanism 5)
      "notes": str                        # optional
    }
The real ~20-30 cases are authored separately (human-verified) and dropped in as
a JSON file; a tiny INVENTED fixture lives under tests/fixtures/ for this
harness's own tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CaseResult:
    id: str
    question: str
    statute_score: str            # "pass" | "partial" | "miss" | "n/a"
    expected_statutes: list[str]
    matched_statutes: list[str]
    missing_statutes: list[str]
    agent_answer: str             # shown SIDE BY SIDE with expected (human compares)
    expected_action: str
    honesty_tier: str
    flagged_citation_count: int
    # Optional machine-checkable expectations (None when the case omits them).
    top_score: float | None = None          # top BM25 score (calibration input)
    expected_tier: str | None = None
    tier_ok: bool | None = None             # honesty_tier == expected_tier
    expected_premise_flag: bool | None = None
    premise_flag: bool = False              # Mechanism-5 detector output
    premise_ok: bool | None = None          # premise_flag == expected_premise_flag


@dataclass
class Scorecard:
    cases: list[CaseResult]

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def statute_pass(self) -> int:
        return sum(1 for c in self.cases if c.statute_score == "pass")

    @property
    def statute_partial(self) -> int:
        return sum(1 for c in self.cases if c.statute_score == "partial")

    @property
    def statute_miss(self) -> int:
        return sum(1 for c in self.cases if c.statute_score == "miss")

    @property
    def statute_na(self) -> int:
        return sum(1 for c in self.cases if c.statute_score == "n/a")

    @property
    def statute_pass_rate(self) -> float:
        scored = self.total - self.statute_na
        return (self.statute_pass / scored) if scored else 0.0

    @property
    def tier_checked(self) -> int:
        return sum(1 for c in self.cases if c.tier_ok is not None)

    @property
    def tier_correct(self) -> int:
        return sum(1 for c in self.cases if c.tier_ok)

    @property
    def tier_accuracy(self) -> float:
        return (self.tier_correct / self.tier_checked) if self.tier_checked else 0.0

    @property
    def premise_checked(self) -> int:
        return sum(1 for c in self.cases if c.premise_ok is not None)

    @property
    def premise_correct(self) -> int:
        return sum(1 for c in self.cases if c.premise_ok)

    @property
    def premise_accuracy(self) -> float:
        return (self.premise_correct / self.premise_checked) if self.premise_checked else 0.0

    def render(self) -> str:
        lines = [
            "═══════ Tier 1 Golden-Set 計分表 ═══════",
            f"案例數:{self.total}｜法條涵蓋 pass {self.statute_pass}"
            f" / partial {self.statute_partial} / miss {self.statute_miss} / n-a {self.statute_na}",
            f"法條涵蓋通過率:{self.statute_pass_rate:.0%}",
            f"誠實分級正確率:{self.tier_correct}/{self.tier_checked}"
            f"({self.tier_accuracy:.0%})｜前提偵測正確率:"
            f"{self.premise_correct}/{self.premise_checked}({self.premise_accuracy:.0%})",
            "",
            "⚠ 本表只『自動計分法條涵蓋』(expected_statutes 是否被引用或檢索到)。",
            "  法律判斷是否正確,必須由『人工』比對下方 [代理人回答] 與 [預期行動];",
            "  本 harness 不做、也不宣稱法律正確性自動通過。",
            "",
        ]
        for c in self.cases:
            lines.append(f"── [{c.id}] {c.question}")
            lines.append(
                f"   法條涵蓋:{c.statute_score}"
                f"(預期 {c.expected_statutes};命中 {c.matched_statutes};缺 {c.missing_statutes})"
            )
            tier_note = "" if c.tier_ok is None else f"(預期 {c.expected_tier};{'✓' if c.tier_ok else '✗'})"
            premise_note = (
                "" if c.premise_ok is None
                else f"｜前提偵測:{c.premise_flag}(預期 {c.expected_premise_flag};{'✓' if c.premise_ok else '✗'})"
            )
            score_note = "" if c.top_score is None else f"｜top BM25:{c.top_score:.2f}"
            lines.append(
                f"   誠實分級:{c.honesty_tier}{tier_note}｜被標記引用數:"
                f"{c.flagged_citation_count}{premise_note}{score_note}"
            )
            lines.append(f"   [代理人回答] {c.agent_answer}")
            lines.append(f"   [預期行動]   {c.expected_action}   ← 需人工比對法律判斷")
            lines.append("")
        return "\n".join(lines)


def load_golden_set(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _article_ref(ref: str) -> str:
    """Normalize a ref to article level ('民法第195條第1項' -> '民法第195條')."""
    idx = ref.find("條")
    return ref[: idx + 1] if idx != -1 else ref


def _covered_statutes(answer: str, retrieved, conn) -> set[str]:
    """Article-level refs the agent surfaced: retrieved refs + cited refs that
    actually EXIST in the corpus (re-verified against the corpus, not just what
    was retrieved)."""
    from legal_agent.anti_hallucination.verifier import verify_answer

    covered = {_article_ref(f"{s.statute_id}{s.article_no}") for s in retrieved}
    for v in verify_answer(answer, [], conn=conn):
        if v.exists:
            covered.add(_article_ref(f"{v.citation.statute_id}{v.citation.article_no}"))
    return covered


def _statute_score(expected: list[str], matched: list[str]) -> str:
    if not expected:
        return "n/a"
    if len(matched) == len(expected):
        return "pass"
    if matched:
        return "partial"
    return "miss"


def _run_case(case: dict, llm, conn) -> CaseResult:
    from legal_agent.dialogue.flow import SessionState, Stage, advance_to_stage3

    state = SessionState(
        stage=Stage.READY_FOR_STAGE3,
        collected_facts=dict(case.get("facts", {})),
        user_text=case.get("question"),
    )
    result = advance_to_stage3(state, llm=llm, as_of_date=case.get("as_of_date"), conn=conn)

    expected = list(case.get("expected_statutes", []))
    covered = _covered_statutes(result.answer, result.stage3.retrieved, conn)
    matched = [e for e in expected if _article_ref(e) in covered]
    missing = [e for e in expected if _article_ref(e) not in covered]

    scores = result.stage3.retrieval_scores or []
    top_score = max(scores) if scores else None
    expected_tier = case.get("expected_tier")
    expected_premise = case.get("expected_premise_flag")

    return CaseResult(
        id=case.get("id", ""),
        question=case.get("question", ""),
        statute_score=_statute_score(expected, matched),
        expected_statutes=expected,
        matched_statutes=matched,
        missing_statutes=missing,
        agent_answer=result.answer,
        expected_action=case.get("expected_action", ""),
        honesty_tier=result.honesty_tier,
        flagged_citation_count=result.flagged_count,
        top_score=top_score,
        expected_tier=expected_tier,
        tier_ok=None if expected_tier is None else result.honesty_tier == expected_tier,
        expected_premise_flag=expected_premise,
        premise_flag=result.premise_flag,
        premise_ok=None if expected_premise is None else result.premise_flag == expected_premise,
    )


def run_golden_set(golden_path, llm, conn=None) -> Scorecard:
    """Run every golden case through the pipeline with the injected `llm` and score
    statute coverage. `llm` is real at runtime, a fake in tests."""
    own = None
    if conn is None:
        from legal_agent.config import DB_PATH
        from legal_agent.data.database import connect

        own = connect(DB_PATH)
        conn = own
    try:
        cases = load_golden_set(golden_path)
        results = [_run_case(c, llm, conn) for c in cases]
    finally:
        if own is not None:
            own.close()
    return Scorecard(results)


if __name__ == "__main__":  # python -m legal_agent.evaluation.golden_set <golden.json>
    import sys as _sys

    if len(_sys.argv) < 2:
        print("用法:python -m legal_agent.evaluation.golden_set <golden.json>")
        raise SystemExit(2)
    from legal_agent.run import build_runtime_llm  # reuses the model/key config checks

    _llm = build_runtime_llm()   # exits cleanly if MODEL/key not set
    print(run_golden_set(_sys.argv[1], llm=_llm).render())

