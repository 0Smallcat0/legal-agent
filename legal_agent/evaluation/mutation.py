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
    subject_swap         right article, wrong 行為主體        -> must flag (semantic)
                         (generated ONLY when a semantic_llm is provided — the
                         structural axes provably cannot catch this class)

Run:  python -m legal_agent.evaluation.mutation [--semantic]
      --semantic wires a local Ollama (fmt=json) as the 4th-axis checker and
      plants the subject_swap cases, so the LLM axis is GRADED, not trusted.
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
    article_no and use a different citation grammar — out of scope here).
    One row per article: historical slices are capped, so effective_to IS NULL
    is unique per (statute_id, article_no) — the ingest guard enforces it."""
    return conn.execute(
        "SELECT statute_id, article_no, content FROM statutes "
        "WHERE article_no != '' AND effective_to IS NULL ORDER BY statute_id, article_no"
    ).fetchall()


def _judge(kind: str, ref: str, answer: str, expect_flag: bool,
           conn: sqlite3.Connection, as_of_date: str | None = None,
           semantic_llm=None) -> MutationOutcome:
    results = verify_answer(answer, [], as_of_date=as_of_date, conn=conn,
                            semantic_llm=semantic_llm)
    if not results:   # extraction failure counts as a miss for mutations
        return MutationOutcome(kind, ref, answer, as_of_date,
                               flagged=False, expect_flag=expect_flag,
                               ok=not expect_flag, reason="未抽取到任何引用")
    flagged = any(r.flagged for r in results)
    reason = "；".join(r.reason for r in results if r.reason)
    return MutationOutcome(kind, ref, answer, as_of_date,
                           flagged=flagged, expect_flag=expect_flag,
                           ok=flagged == expect_flag, reason=reason)


# Subject swaps: the cited article is REAL and every structural axis passes —
# only the 行為主體 is wrong. Hand-written against hand-verified corpus rows.
_SUBJECT_SWAPS = [
    ("民法", "第793條",
     "依民法第793條,承租人於他人土地之喧囂侵入時,得禁止之。"),      # 條文主體:土地所有人
    ("公寓大廈管理條例", "第16條",
     "依公寓大廈管理條例第16條,房東不得任意發生喧囂、振動行為。"),   # 條文主體:住戶
    ("噪音管制法", "第6條",
     "依噪音管制法第6條,不具持續性之噪音由環境主管機關依法處理之。"),  # 條文主體:警察機關
]


def run_mutation_test(
    conn: sqlite3.Connection,
    semantic_llm=None,
) -> MutationReport:
    """Run the seeded-error suite. With `semantic_llm` set, the 4th axis is on
    and the subject_swap cases are planted (grading the LLM checker itself)."""
    outcomes: list[MutationOutcome] = []
    # Earliest slice per article: out_of_force must date the citation before
    # the FIRST version ever took effect. The day before the CURRENT slice is
    # not out of force when a capped historical slice covers that date.
    earliest_from = {
        (r[0], r[1]): r[2]
        for r in conn.execute(
            "SELECT statute_id, article_no, MIN(effective_from) FROM statutes "
            "WHERE article_no != '' GROUP BY statute_id, article_no"
        )
    }
    for row in _condition_articles(conn):
        sid, ano, content = row[0], row[1], row[2]
        ref = f"{sid}{ano}"
        num_match = _ARTICLE_NUM_RE.search(ano)
        source_amounts = _amounts(content)

        # control — correct citation; include a REAL amount when the article has one.
        if source_amounts:
            amt = max(source_amounts)
            control = f"依{ref},法定金額為{amt}元。"
        else:
            control = f"依{ref},其規範內容如條文所示。"
        # with the semantic axis on, controls ALSO pass through it — the 0-FP
        # bar applies to the LLM checker too, or it doesn't ship.
        outcomes.append(_judge("control", ref, control, expect_flag=False,
                               conn=conn, semantic_llm=semantic_llm))

        # nonexistent_article — same statute, shifted article number, VERIFIED
        # absent first: in a 1439-article code (民法), 第X+500條 can be a real
        # article — planting it would grade a correct verifier as a miss.
        if num_match:
            base_no = int(num_match.group(1))
            ghost_no = next(
                (
                    f"第{base_no + off}條" for off in (500, 1000, 5000, 9999)
                    if not conn.execute(
                        "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ?",
                        (sid, f"第{base_no + off}條"),
                    ).fetchone()
                ),
                None,
            )
            if ghost_no:
                ghost = f"{sid}{ghost_no}"
                outcomes.append(_judge(
                    "nonexistent_article", ghost,
                    f"依{ghost},住戶應負相關義務。", expect_flag=True, conn=conn,
                ))

        # ghost_suffix — a 「之X」 variant that does NOT exist (民法第793條之99).
        # LLMs love inventing 之X sub-articles; a parser that silently drops the
        # suffix launders the ghost into the REAL parent article. Same
        # verified-absent guard: the canonical form 第X-99條 must not be real.
        if num_match and not conn.execute(
            "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ?",
            (sid, f"第{num_match.group(1)}-99條"),
        ).fetchone():
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
        # out, so an amounts-only content match is blind to this. Only amounts
        # whose direction is UNAMBIGUOUS in the article are planted: in range
        # wording (「六百元以上一千八百元以下…一千八百元以上…」) the same
        # amount legitimately carries BOTH directions, so a flip is consistent
        # and a correct verifier would be graded as a miss.
        amount_dirs: dict[int, set[str]] = {}
        for m in _AMOUNT_DIR_RE.finditer(content):
            value = _parse_number(m.group(1))
            if value is not None and m.group(2):
                amount_dirs.setdefault(value, set()).add(
                    "down" if m.group(2) in _DOWNWARD else "up"
                )
        unique = next((a for a, d in amount_dirs.items() if len(d) == 1), None)
        if unique is not None:
            flipped = "以上" if amount_dirs[unique] == {"down"} else "以下"
            outcomes.append(_judge(
                "direction_flip", ref,
                f"依{ref},違者可處新臺幣{unique}元{flipped}罰鍰。",
                expect_flag=True, conn=conn,
            ))

        # out_of_force — cite the article the day BEFORE its earliest slice.
        day_before = (
            date.fromisoformat(earliest_from[(sid, ano)]) - timedelta(days=1)
        ).isoformat()
        outcomes.append(_judge(
            "out_of_force", f"{ref}@{day_before}", control, expect_flag=True,
            conn=conn, as_of_date=day_before,
        ))

    # fake_statute — one invented statute name (corpus-independent).
    outcomes.append(_judge(
        "fake_statute", "台灣安寧保障法第3條", _FAKE_ANSWER, expect_flag=True, conn=conn,
    ))

    # subject_swap — semantic-axis cases: structurally perfect, wrong 主體.
    if semantic_llm is not None:
        for sid, ano, answer in _SUBJECT_SWAPS:
            present = conn.execute(
                "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ? "
                "AND effective_to IS NULL", (sid, ano),
            ).fetchone()
            if present:
                outcomes.append(_judge(
                    "subject_swap", f"{sid}{ano}", answer,
                    expect_flag=True, conn=conn, semantic_llm=semantic_llm,
                ))
    return MutationReport(outcomes)


if __name__ == "__main__":  # python -m legal_agent.evaluation.mutation [--semantic]
    import argparse

    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    _parser = argparse.ArgumentParser(prog="python -m legal_agent.evaluation.mutation")
    _parser.add_argument(
        "--semantic", action="store_true",
        help="開啟第四軸語意檢查(本地 Ollama, fmt=json, temperature=0)並種入 subject_swap 錯",
    )
    _parser.add_argument(
        "--model", default=None, metavar="OLLAMA_MODEL",
        help="語意軸用的 Ollama 模型(預設 config.OLLAMA_MODEL)— 讓不同模型考同一份考卷",
    )
    _args = _parser.parse_args()

    _semantic_llm = None
    if _args.semantic:
        from legal_agent.dialogue.ollama_llm import ollama_available, ollama_llm

        if not ollama_available():
            raise SystemExit("Ollama 未啟動 — 語意軸需要本地模型(先 `ollama serve`)")
        _semantic_llm = ollama_llm(model=_args.model, fmt="json", temperature=0.0)

    _conn = connect(DB_PATH)
    try:
        print(run_mutation_test(_conn, semantic_llm=_semantic_llm).render())
    finally:
        _conn.close()
