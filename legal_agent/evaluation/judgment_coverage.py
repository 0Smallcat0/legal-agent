"""Does the reader's KIND of dispute have a real judgment to point at? (SPEC §1.2)

`judgment_relevance` grades the first judgment a page shows. This harness asks
the question before it: for each kind of dispute people actually bring, how many
judgments of that kind does the corpus hold, and does a consultation about it
get one on the page at all.

Two groupings, both derived, neither hand-labelled:
  * by FAMILY — the session's own `expected_statutes` through
    `judgment_relevance.statute_family` (民法's 編/章/節 structure). This is the
    grouping the target is set on, because it is the one a judgment can be
    matched against.
  * by TRIAGE — `dialogue.triage.classify` on the user's raw words, i.e. the
    route the dialogue layer actually takes. Shown so a gap can be read in the
    product's own vocabulary; 「ambiguous」 is a real row, not an error.

A judgment counts toward a family's STOCK only when it is reachable as that
kind of case: its 案由 names the family (`case_type_family`) AND it cites at
least one article of that family. The second half is what makes it reachable —
`related_judgments` is a JOIN on cited articles, so a 租賃 case citing only
民法§184 can never surface under a 租賃 question.

The target is 3 per family: what the page shows (`related_judgments` limit=3).
A family below it is listed with how many are missing; those are the families
`data/judgment_backfill.py` fills, and its selection uses `serves_family`
below so the two can never disagree on what counts.

Run:  python -m legal_agent.evaluation.judgment_coverage [evals/real_sessions.json]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from legal_agent.config import PROJECT_ROOT
from legal_agent.evaluation import corpus_connection
from legal_agent.evaluation.judgment_relevance import (
    _CASE_TYPE_FAMILIES,
    _CROSS_CUTTING,
    case_type_family,
    statute_family,
)

TARGET = 3          # = related_judgments' default limit: one page's worth


def session_families(expected: list[str]) -> list[str]:
    """The dispute families a session is about; cross-cutting rules excluded,
    exactly as `judgment_relevance` scores them."""
    return sorted({f for f in (statute_family(e) for e in expected)
                   if f and f not in _CROSS_CUTTING})


def nameable(family: str) -> bool:
    """Can any 案由 be read as this family at all? When not, its stock is 0 by
    construction — a limit of the instrument, which no backfill can fill."""
    return any(f == family for _k, f in _CASE_TYPE_FAMILIES)


def serves_family(case_type: str | None, cited: list[dict]) -> str | None:
    """The family a judgment can be shown as, or None.

    Its 案由 names the family AND one of its cited articles belongs to it —
    the JOIN can only bring it to a page through such an article."""
    family = case_type_family(case_type)
    if family is None or family in _CROSS_CUTTING:
        return None
    for c in cited or []:
        ref = f"{c.get('statute_id')}{c.get('article_no')}"
        if statute_family(ref) == family:
            return family
    return None


def stock_by_family(conn) -> dict[str, list[str]]:
    """family -> jids of corpus judgments that serve it."""
    stock: dict[str, list[str]] = {}
    for jid, case_type, cited in conn.execute(
            "SELECT jid, case_type, cited_articles FROM judgments"):
        try:
            cited_list = json.loads(cited or "[]")
        except ValueError:
            continue
        family = serves_family(case_type, cited_list)
        if family:
            stock.setdefault(family, []).append(jid)
    return stock


@dataclass
class Row:
    key: str
    sessions: int = 0
    with_judgment: int = 0      # page shows ≥1 reference judgment
    same_kind: int = 0          # …and ≥1 of them is the session's family
    stock: int | None = None    # family rows only

    @property
    def missing(self) -> int:
        return max(0, TARGET - (self.stock or 0)) if self.stock is not None else 0


@dataclass
class CoverageReport:
    families: dict[str, Row] = field(default_factory=dict)
    triage: dict[str, Row] = field(default_factory=dict)
    sessions: int = 0
    unfamilied: int = 0         # sessions whose expected articles name no family
    total_judgments: int = 0
    dense_fallbacks: int = 0

    @property
    def at_target(self) -> int:
        return sum(1 for r in self.families.values() if r.missing == 0)

    @property
    def missing(self) -> int:
        return sum(r.missing for r in self.families.values())

    def deficits(self) -> dict[str, int]:
        return {k: r.missing for k, r in self.families.items() if r.missing}

    def render(self) -> str:
        lines = ["═══════ 判決涵蓋(每類糾紛有沒有同類判決可引) ═══════",
                 f"語料判決 {self.total_judgments} 筆;諮詢 {self.sessions} 個"
                 f"({self.unfamilied} 個的預期條文不屬任何糾紛類型,不入家族表)",
                 "",
                 f"{'家族':8s} {'諮詢數':>4s} {'附判決':>4s} {'同類':>4s} "
                 f"{'庫存同類':>6s} {'待補':>4s}"]
        ordered = sorted(self.families.values(), key=lambda r: (-r.sessions, r.key))
        for r in ordered:
            lines.append(f"{r.key:8s} {r.sessions:6d} {r.with_judgment:6d} "
                         f"{r.same_kind:6d} {r.stock:8d} {r.missing:6d}")
        lines += ["", f"{'分流':16s} {'諮詢數':>4s} {'附判決':>4s} {'同類':>4s}"]
        for r in sorted(self.triage.values(), key=lambda r: (-r.sessions, r.key)):
            lines.append(f"{r.key:16s} {r.sessions:6d} {r.with_judgment:6d} {r.same_kind:6d}")
        empty = sorted(k for k, r in self.families.items() if not r.stock)
        unnamed = sorted(k for k in self.families if not nameable(k))
        lines += [
            "",
            f"達標(庫存同類 ≥{TARGET}):{self.at_target}/{len(self.families)} 個家族,"
            f"共缺 {self.missing} 筆",
            f"庫存為 0:{'、'.join(empty) or '(無)'}",
            f"其中案由表認不出的家族(量尺限制,補不到):{'、'.join(unnamed) or '(無)'}",
            "同類 = 頁面上至少一筆判決的案由與諮詢同家族;附判決/同類 依 judgment_relevance"
            " 的 focus(答案引對條文)量,是上限不是保證。",
        ]
        if self.dense_fallbacks:
            lines.append(
                f"⚠ {self.dense_fallbacks}/{self.sessions} 個查詢的 dense 半邊退回純 BM25,"
                "附判決/同類兩欄不可與 dense 下的數字相比(庫存欄與檢索無關)。")
        return "\n".join(lines)


def run_judgment_coverage(path, conn=None, k: int | None = None) -> CoverageReport:
    from legal_agent.dialogue.triage import classify
    from legal_agent.retrieval.judgments import related_judgments
    from legal_agent.retrieval.retriever import (
        DEFAULT_K,
        dense_fallback_count,
        reset_dense_fallbacks,
        retrieve,
    )

    reset_dense_fallbacks()
    report = CoverageReport()
    with corpus_connection(conn) as conn:
        stock = stock_by_family(conn)
        report.total_judgments = conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
        for case in json.loads(Path(path).read_text(encoding="utf-8")):
            expected = list(case.get("expected_statutes", []))
            families = session_families(expected)
            found = retrieve(case["query"], k=DEFAULT_K if k is None else k, conn=conn)
            # Same focus as judgment_relevance: the answer cites what it should.
            focus = {(s.statute_id, s.article_no) for s in found
                     if f"{s.statute_id}{s.article_no}" in set(expected)}
            refs = related_judgments(found, conn=conn, focus=focus or None)
            shown = {case_type_family(r.case_type) for r in refs}
            has = bool(refs)

            report.sessions += 1
            if not families:
                report.unfamilied += 1
            for fam in families:
                row = report.families.setdefault(fam, Row(fam, stock=len(stock.get(fam, []))))
                row.sessions += 1
                row.with_judgment += has
                row.same_kind += fam in shown
            route = classify(case["query"]).problem_type or "ambiguous"
            trow = report.triage.setdefault(route, Row(route))
            trow.sessions += 1
            trow.with_judgment += has
            trow.same_kind += bool(shown & set(families))
    report.dense_fallbacks = dense_fallback_count()
    return report


if __name__ == "__main__":   # python -m legal_agent.evaluation.judgment_coverage
    import sys as _sys

    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()
    target = _sys.argv[1] if len(_sys.argv) > 1 else PROJECT_ROOT / "evals" / "real_sessions.json"
    print(run_judgment_coverage(target).render())
