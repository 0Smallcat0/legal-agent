"""Tier 2 — Automated citation check (spec §4.2). Reuses the Mechanism-2 verifier
over a BATCH of answers to compute a citation-integrity rate: the fraction of
answers containing ANY flagged citation (fabricated / content-mismatch /
out-of-date). Pure — no LLM. Complements Tier 1 (which needs a human for the
legal judgment): Tier 1 asks "is the legal judgment right", Tier 2 asks "are the
citations real".
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnswerCheck:
    answer: str
    flagged: bool
    results: list          # list[VerificationResult]


@dataclass
class HallucinationReport:
    per_answer: list        # list[AnswerCheck]

    @property
    def total(self) -> int:
        return len(self.per_answer)

    @property
    def flagged_answers(self) -> int:
        return sum(1 for a in self.per_answer if a.flagged)

    @property
    def clean_answers(self) -> int:
        return self.total - self.flagged_answers

    @property
    def flag_rate(self) -> float:
        return (self.flagged_answers / self.total) if self.total else 0.0

    def render(self) -> str:
        lines = [
            "═══════ Tier 2 引用完整性檢查 ═══════",
            f"答案數:{self.total}｜含被標記引用:{self.flagged_answers}｜乾淨:{self.clean_answers}",
            f"被標記率:{self.flag_rate:.0%}(越低越好;鎖定最致命的錯誤——捏造/內容不符/失效法條)",
            "",
        ]
        for a in self.per_answer:
            mark = "⚠ 被標記" if a.flagged else "✔ 乾淨"
            lines.append(f"{mark}｜{a.answer[:60]}")
            for v in a.results:
                if v.flagged:
                    lines.append(f"     - {v.citation.statute_id}{v.citation.article_no}:{v.reason}")
        return "\n".join(lines)


def check_answers(answers, conn=None, as_of_date=None) -> HallucinationReport:
    """Verify each answer's citations against the corpus; aggregate the flag rate.

    `answers` is a batch of answer strings. Pure — no LLM. Provide `conn` (the
    corpus) so existence / content-match / in-force are checked against ground
    truth. This is the Mechanism-2 verifier reused as the Tier-2 eval tool.
    """
    from legal_agent.anti_hallucination.verifier import verify_answer

    per_answer = []
    for answer in answers:
        results = verify_answer(answer, [], as_of_date=as_of_date, conn=conn)
        per_answer.append(
            AnswerCheck(answer=answer, flagged=any(v.flagged for v in results), results=results)
        )
    return HallucinationReport(per_answer=per_answer)
