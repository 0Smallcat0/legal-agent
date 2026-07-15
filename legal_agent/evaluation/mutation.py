"""Verifier mutation test — measure the citation verifier's catch rate on
KNOWN-planted errors (SPEC §2.3 / §4.2 Tier 2 hardening).

Rationale: the verifier is the load-bearing gate ("when the system errs, the
user knows"), so its own recall must be MEASURED, not assumed. This module
builds answers from real corpus rows with one planted defect each, runs
`verify_answer`, and reports catch rate per mutation type plus the
false-positive rate on correct controls. Fully deterministic — no LLM, no
network.

Mutation types (one citation per generated answer):
    control              correct citation, correct amount   -> must NOT flag
    nonexistent_article  real statute, article_no shifted    -> must flag (exists)
    fake_statute         invented statute name               -> must flag (exists)
    ghost_suffix         real article + 之99 suffix           -> must flag (exists)
    wrong_amount         real citation, amount x10           -> must flag (content)
    direction_flip       real amount, 以下<->以上 flipped     -> must flag (content)
    out_of_force         real citation, as_of before 生效日   -> must flag (in-force)

Run:  python -m legal_agent.evaluation.mutation
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from legal_agent.anti_hallucination.verifier import _amounts, _parse_number, verify_answer

_ARTICLE_NUM_RE = re.compile(r"第(\d+)條")
_FAKE_ANSWER = "依台灣安寧保障法第3條,住戶應保持安寧。"
# Suffix-form amount + direction word, as statutes write penalty bounds.
_AMOUNT_DIR_RE = re.compile(
    r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩]+)\s*元(以上|以下|以內|未滿)?"
)
_DOWNWARD = {"以下", "以內", "未滿"}


@dataclass(frozen=True)
class MutationOutcome:
    kind: str
    ref: str                # the citation the answer carries
    answer: str
    as_of_date: str | None
    flagged: bool
    expect_flag: bool
    ok: bool                # flagged == expect_flag
    reason: str             # verifier's reason (or extraction failure note)


@dataclass
class MutationReport:
    outcomes: list[MutationOutcome]

    def _bucket(self, kind: str) -> list[MutationOutcome]:
        return [o for o in self.outcomes if o.kind == kind]

    @property
    def kinds(self) -> list[str]:
        seen: list[str] = []
        for o in self.outcomes:
            if o.kind not in seen:
                seen.append(o.kind)
        return seen

    @property
    def mutation_total(self) -> int:
        return sum(1 for o in self.outcomes if o.expect_flag)

    @property
    def mutation_caught(self) -> int:
        return sum(1 for o in self.outcomes if o.expect_flag and o.ok)

    @property
    def catch_rate(self) -> float:
        return (self.mutation_caught / self.mutation_total) if self.mutation_total else 0.0

    @property
    def control_total(self) -> int:
        return sum(1 for o in self.outcomes if not o.expect_flag)

    @property
    def false_positives(self) -> int:
        return sum(1 for o in self.outcomes if not o.expect_flag and not o.ok)

    @property
    def false_positive_rate(self) -> float:
        return (self.false_positives / self.control_total) if self.control_total else 0.0

    def render(self) -> str:
        lines = [
            "═══════ Verifier mutation test(植入已知錯誤,量測抓取率) ═══════",
            f"{'type':<22}{'result':<14}note",
        ]
        for kind in self.kinds:
            bucket = self._bucket(kind)
            ok = sum(1 for o in bucket if o.ok)
            note = "不得誤標(false-positive)" if kind == "control" else "必須標記(catch)"
            lines.append(f"{kind:<22}{ok}/{len(bucket):<12}{note}")
        lines.append("")
        lines.append(
            f"mutation catch rate: {self.mutation_caught}/{self.mutation_total}"
            f"({self.catch_rate:.0%})｜false-positive rate: "
            f"{self.false_positives}/{self.control_total}({self.false_positive_rate:.0%})"
        )
        misses = [o for o in self.outcomes if not o.ok]
        if misses:
            lines.append("")
            lines.append("⚠ 未如預期的案例:")
            lines.extend(f"  - [{o.kind}] {o.ref}: {o.reason or '(無 reason)'}" for o in misses)
        return "\n".join(lines)


def _condition_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """條-style, currently-in-force corpus rows (文號-style entries have no
    article_no and use a different citation grammar — out of scope here)."""
    return conn.execute(
        "SELECT statute_id, article_no, content, effective_from FROM statutes "
        "WHERE article_no != '' AND effective_to IS NULL ORDER BY statute_id, article_no"
    ).fetchall()


def _judge(kind: str, ref: str, answer: str, expect_flag: bool,
           conn: sqlite3.Connection, as_of_date: str | None = None) -> MutationOutcome:
    results = verify_answer(answer, [], as_of_date=as_of_date, conn=conn)
    if not results:   # extraction failure counts as a miss for mutations
        return MutationOutcome(kind, ref, answer, as_of_date,
                               flagged=False, expect_flag=expect_flag,
                               ok=not expect_flag, reason="未抽取到任何引用")
    flagged = any(r.flagged for r in results)
    reason = "；".join(r.reason for r in results if r.reason)
    return MutationOutcome(kind, ref, answer, as_of_date,
                           flagged=flagged, expect_flag=expect_flag,
                           ok=flagged == expect_flag, reason=reason)


def run_mutation_test(conn: sqlite3.Connection) -> MutationReport:
    outcomes: list[MutationOutcome] = []
    for row in _condition_articles(conn):
        sid, ano, content, eff = row[0], row[1], row[2], row[3]
        ref = f"{sid}{ano}"
        num_match = _ARTICLE_NUM_RE.search(ano)
        source_amounts = _amounts(content)

        # control — correct citation; include a REAL amount when the article has one.
        if source_amounts:
            amt = max(source_amounts)
            control = f"依{ref},法定金額為{amt}元。"
        else:
            control = f"依{ref},其規範內容如條文所示。"
        outcomes.append(_judge("control", ref, control, expect_flag=False, conn=conn))

        # nonexistent_article — same statute, shifted article number.
        if num_match:
            ghost = f"{sid}第{int(num_match.group(1)) + 500}條"
            outcomes.append(_judge(
                "nonexistent_article", ghost,
                f"依{ghost},住戶應負相關義務。", expect_flag=True, conn=conn,
            ))

        # ghost_suffix — a 「之X」 variant that does NOT exist (民法第793條之99).
        # LLMs love inventing 之X sub-articles; a parser that silently drops the
        # suffix launders the ghost into the REAL parent article.
        if num_match:
            outcomes.append(_judge(
                "ghost_suffix", f"{ref}之99",
                f"依{ref}之99,住戶得請求排除侵害。", expect_flag=True, conn=conn,
            ))

        # wrong_amount — real citation, unsupported amount in the claim sentence.
        bad_amt = (max(source_amounts) * 10) if source_amounts else 99999
        outcomes.append(_judge(
            "wrong_amount", ref,
            f"依{ref},違者可處新臺幣{bad_amt}元罰鍰。", expect_flag=True, conn=conn,
        ))

        # direction_flip — keep a REAL amount, flip its suffix direction word
        # (「六千元以下罰鍰」 -> claim 「六千元以上」). The amount itself checks
        # out, so an amounts-only content match is blind to this.
        dir_match = _AMOUNT_DIR_RE.search(content)
        if dir_match and dir_match.group(2):
            real_amt = _parse_number(dir_match.group(1))
            flipped = "以上" if dir_match.group(2) in _DOWNWARD else "以下"
            if real_amt is not None:
                outcomes.append(_judge(
                    "direction_flip", ref,
                    f"依{ref},違者可處新臺幣{real_amt}元{flipped}罰鍰。",
                    expect_flag=True, conn=conn,
                ))

        # out_of_force — cite the article at a date BEFORE its effective_from.
        day_before = (date.fromisoformat(eff) - timedelta(days=1)).isoformat()
        outcomes.append(_judge(
            "out_of_force", f"{ref}@{day_before}", control, expect_flag=True,
            conn=conn, as_of_date=day_before,
        ))

    # fake_statute — one invented statute name (corpus-independent).
    outcomes.append(_judge(
        "fake_statute", "台灣安寧保障法第3條", _FAKE_ANSWER, expect_flag=True, conn=conn,
    ))
    return MutationReport(outcomes)


if __name__ == "__main__":  # python -m legal_agent.evaluation.mutation
    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    _conn = connect(DB_PATH)
    try:
        print(run_mutation_test(_conn).render())
    finally:
        _conn.close()
