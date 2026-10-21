"""Is the reference judgment about the reader's KIND of problem? (SPEC §1.2)

The judgment layer's correctness was never in doubt: `related_judgments` JOINs
on articles the pipeline already retrieved, so a case cannot appear unless it
cites the same law. That is relevance to an ARTICLE, guaranteed by code.

This harness measures relevance to the reader's DISPUTE.

What the reader actually sees
─────────────────────────────
`judgments.full_text` holds the header and the 主文 only — no facts, no
reasoning (median ~115 chars, verified). So the rendered block gives a person
four things: the 案由, the court and case number, the sum the court ordered
paid, and the shared article. Of those, the 案由 is the ONLY one that says what
the case was about. Grading 案由 concordance is therefore not a proxy chosen
for convenience: it grades the one field the reader has to judge by.

Both sides are DERIVED, so there are no hand labels to disagree with:
  * the session's family comes from its own `expected_statutes` — 民法 article
    ranges are the code's own 編/章/節 structure, a legal fact, not an opinion;
  * the judgment's family comes from keywords in the court's own 案由.
Anyone can re-derive both from the two tables below.

Honest about what it cannot say. Same family is a NECESSARY condition, not a
sufficient one: two 租賃 cases can still be different situations, so the match
rate is a CEILING on usefulness, the way `real_recall.precision` is a floor.
And 「損害賠償」 — the single commonest 案由 — names no dispute at all; those are
reported as UNLABELLED rather than scored either way: counting them as hits
would flatter the number, as misses would blame the layer for the court's
filing vocabulary.

Run:  python -m legal_agent.evaluation.judgment_relevance [evals/real_sessions.json]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from legal_agent.config import PROJECT_ROOT
from legal_agent.evaluation import corpus_connection
from legal_agent.retrieval.families import (  # noqa: F401  (re-exported for harnesses)
    _CASE_TYPE_FAMILIES,
    _CIVIL_RANGES,
    _CIVIL_SINGLES,
    _CROSS_CUTTING,
    _SPECIAL_STATUTES,
    _UNINFORMATIVE,
    case_type_family,
    is_uninformative,
    statute_family,
)


@dataclass
class CaseJudgment:
    id: str
    label: str
    families: list[str]                 # what the session is about
    shown: str | None = None            # 案由 of the first judgment
    shown_family: str | None = None
    cite: str | None = None
    verdict: str = "none"               # match | mismatch | unlabelled | none
    n_shown: int = 0
    would_show_unfocused: bool = False   # a judgment exists, focus removed it


@dataclass
class RelevanceReport:
    cases: list[CaseJudgment] = field(default_factory=list)
    dense_fallbacks: int = 0

    def _n(self, verdict: str) -> int:
        return sum(1 for c in self.cases if c.verdict == verdict)

    @property
    def covered(self) -> int:
        return sum(1 for c in self.cases if c.n_shown)

    @property
    def scorable(self) -> int:
        return self._n("match") + self._n("mismatch")

    @property
    def rate(self) -> float:
        return self._n("match") / self.scorable if self.scorable else 0.0

    def render(self) -> str:
        lines = ["═══════ 參考判決關聯性(以使用者原話為輸入) ═══════"]
        for c in self.cases:
            mark = {"match": "OK  ", "mismatch": "MISS", "unlabelled": "??  ",
                    "none": "--  "}[c.verdict]
            lines.append(
                f"{mark} {c.id[:34]:34s} {'/'.join(c.families) or '(未歸類)':14s}"
                f" {c.shown or '(無判決)'}"
            )
        hidden = sum(1 for c in self.cases if not c.n_shown and c.would_show_unfocused)
        lines += [
            "",
            f"覆蓋:{self.covered}/{len(self.cases)} 個諮詢附上參考判決"
            f"(其中 {hidden} 個是 focus 收斂後才變成沒有——"
            "答案引用的條文沒有判決引過,寧可不附也不附錯)",
            f"案由同類:{self._n('match')}/{self.scorable}"
            f"({self.rate:.0%})——只算案由講得出糾紛類型的那些",
            f"案由籠統無法判定:{self._n('unlabelled')}/{self.covered}"
            "(如「損害賠償」;判決全文只存標頭與主文,案由是讀者唯一能判斷的欄位)",
            "同類是必要條件不是充分條件:兩件租賃案仍可能不是同一種處境,"
            "故此為關聯性的上限,非關聯性本身。",
        ]
        misses = [c for c in self.cases if c.verdict == "mismatch"]
        if misses:
            lines.append("\n─── 案由與諮詢不同類 ───")
            for c in misses:
                lines.append(f"  {c.id[:34]:34s} {'/'.join(c.families):12s} -> "
                             f"{c.shown}({c.shown_family})")
        if self.dense_fallbacks:
            lines.append(
                f"⚠ {self.dense_fallbacks}/{len(self.cases)} 個查詢的 dense 半邊退回純 BM25,"
                "此數不可與已發布數字相比。"
            )
        return "\n".join(lines)


def run_judgment_relevance(path, conn=None, k: int | None = None) -> RelevanceReport:
    """Retrieve for every session, take the judgment the reader would see first,
    and compare its 案由 family with the session's own.

    `focus` is the set of the session's expected articles that actually reached
    the window — i.e. what stage3 passes when the model cites the right law and
    verification clears it. Measuring under a CORRECT answer isolates this layer
    from model quality, which is the only way its own number means anything.
    """
    from legal_agent.retrieval.judgments import related_judgments
    from legal_agent.retrieval.retriever import (
        DEFAULT_K,
        dense_fallback_count,
        reset_dense_fallbacks,
        retrieve,
    )

    reset_dense_fallbacks()
    with corpus_connection(conn) as conn:
        report = RelevanceReport()
        for case in json.loads(Path(path).read_text(encoding="utf-8")):
            expected = list(case.get("expected_statutes", []))
            families = sorted({f for f in (statute_family(e) for e in expected)
                               if f and f not in _CROSS_CUTTING})
            found = retrieve(case["query"], k=DEFAULT_K if k is None else k, conn=conn)
            focus = {(s.statute_id, s.article_no) for s in found
                     if f"{s.statute_id}{s.article_no}" in set(expected)}
            refs = related_judgments(found, conn=conn, focus=focus or None)
            entry = CaseJudgment(
                id=case.get("id", ""), label=case.get("label", ""), families=families,
                n_shown=len(refs),
            )
            if not refs:
                entry.would_show_unfocused = bool(
                    related_judgments(found, conn=conn, focus=None))
            else:
                first = refs[0]
                entry.shown = first.case_type
                entry.cite = first.cite
                entry.shown_family = case_type_family(first.case_type)
                if (is_uninformative(first.case_type)
                        or entry.shown_family is None
                        or entry.shown_family in _CROSS_CUTTING):
                    entry.verdict = "unlabelled"
                elif not families:
                    entry.verdict = "unlabelled"     # session names no setting
                else:
                    entry.verdict = ("match" if entry.shown_family in families
                                     else "mismatch")
            report.cases.append(entry)
    report.dense_fallbacks = dense_fallback_count()
    return report


if __name__ == "__main__":   # python -m legal_agent.evaluation.judgment_relevance
    import sys as _sys

    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()
    target = _sys.argv[1] if len(_sys.argv) > 1 else PROJECT_ROOT / "evals" / "real_sessions.json"
    print(run_judgment_relevance(target).render())
