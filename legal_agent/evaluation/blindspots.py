"""Blind-spot suite — hand-written cases with shapes the seeded-error
mutation test cannot express, so the verifier's blind spots on them are
measured instead of assumed.

evals/blindspots_v1.json: 16 "miss" cases (the verifier should flag them) +
9 "control" cases (must never be flagged). The denominator is frozen at 25;
a newly found gap becomes its own test in tests/test_verifier.py, not a case
here. The 4 still-missed cases are xfail(strict=True) there.

evals/blindspots_positive_control_v1.json: 6 CORRECT texts that must never
be flagged — prose prefixes (前開/上開/揆諸) and verbatim articles (消保法§50,
家暴法§58-2, whose 「包括」/「被害人因具」 prefixes are why the qualifier gate
is a deny-list, not an allow-list). Labels: "must_not_regress" and
"must_stop_being_flagged" (家暴法§61 verbatim, a former false positive).

`BlindspotReport` prints two readings:
  * `baseline_headline` (該標未標/總數) — miss cases still blind on this
    commit. Diagnostic; it goes DOWN as the verifier improves.
  * `target_headline` (正確數/總數) — miss cases flagged + controls clean.
    Higher is better; this is the published figure (RESULTS.md §4).

Exit code: non-zero if the case files are empty or the 16+9 composition is
wrong (fix the case file, never this script), or on any `gate_problems`: a
control or positive-control case flagged, a miss case outside STILL_BLIND
uncaught, a STILL_BLIND case caught (update the published 21/25), or a
positive-control file that is not 6 cases.

Run:  python -m legal_agent.evaluation.blindspots
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from legal_agent.anti_hallucination.verifier import verify_answer
from legal_agent.evaluation import assert_nonzero_scan

_EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"
BLINDSPOTS_PATH = _EVALS_DIR / "blindspots_v1.json"
POSITIVE_CONTROL_PATH = _EVALS_DIR / "blindspots_positive_control_v1.json"

# Frozen composition. A run that does not match fails loudly rather than
# printing a plausible-looking number.
EXPECTED_MISS_TOTAL = 16
EXPECTED_CONTROL_TOTAL = 9
FROZEN_DENOMINATOR = EXPECTED_MISS_TOTAL + EXPECTED_CONTROL_TOTAL
EXPECTED_POSITIVE_CONTROL_TOTAL = 6

# The four miss cases the structural axes still cannot see. Three are a modal
# or proviso changed inside a real, correctly-cited article (得→應, 得禁止→不得禁止,
# an inverted 但書); the fourth is a 同法 reference whose inherited citation is
# never compared against its article. Catching them needs a semantic axis, and
# the one this repo has misfires on 43% of correct citations. They are the 4 in
# the published 21/25; tests/test_verifier.py marks them xfail(strict=True).
STILL_BLIND = frozenset({
    "modal_de_to_ying",
    "modal_full_negation",
    "proviso_reversal",
    "anaphora_tong_fa_20",
})


@dataclass(frozen=True)
class BlindspotCase:
    id: str
    category: str              # "miss" | "control"
    answer: str
    expect_flag: bool          # target state: True for miss, False for control
    anchor_statute_id: str
    anchor_article_no: str
    mechanism: str = ""
    guards: str = ""
    description: str = ""
    note: str = ""


@dataclass(frozen=True)
class PositiveControlCase:
    id: str
    label: str                 # "must_not_regress" | "must_stop_being_flagged"
    answer: str
    expect_flag: bool          # always False — the eventual target state
    anchor_statute_id: str
    anchor_article_no: str
    description: str = ""
    note: str = ""


@dataclass(frozen=True)
class BlindspotOutcome:
    case: BlindspotCase
    flagged: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PositiveControlOutcome:
    case: PositiveControlCase
    flagged: bool
    reasons: tuple[str, ...]


def _known_fields(cls, row: dict) -> dict:
    """Keep only the keys `cls` declares, so the JSON may carry extra
    documentation fields."""
    names = set(cls.__dataclass_fields__)
    return {k: v for k, v in row.items() if k in names}


def load_blindspot_cases(path: Path = BLINDSPOTS_PATH) -> list[BlindspotCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [BlindspotCase(**_known_fields(BlindspotCase, c)) for c in payload["cases"]]


def load_positive_control_cases(
    path: Path = POSITIVE_CONTROL_PATH,
) -> list[PositiveControlCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        PositiveControlCase(**_known_fields(PositiveControlCase, c))
        for c in payload["cases"]
    ]


def _run_one(answer: str, conn: sqlite3.Connection) -> tuple[bool, tuple[str, ...]]:
    """Same calling convention `mutation.py._judge` uses for its non
    --retrieval-first path: full-corpus `conn`, empty `retrieved_context`."""
    results = verify_answer(answer, [], conn=conn)
    flagged = any(r.flagged for r in results)
    reasons = tuple(r.reason for r in results if r.reason)
    return flagged, reasons


@dataclass
class BlindspotReport:
    outcomes: list[BlindspotOutcome]

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def miss_outcomes(self) -> list[BlindspotOutcome]:
        return [o for o in self.outcomes if o.case.category == "miss"]

    @property
    def control_outcomes(self) -> list[BlindspotOutcome]:
        return [o for o in self.outcomes if o.case.category == "control"]

    @property
    def miss_total(self) -> int:
        return len(self.miss_outcomes)

    @property
    def control_total(self) -> int:
        return len(self.control_outcomes)

    # ── baseline metric: "該標未標" — a miss case still unflagged ──────────
    # Goes DOWN as the verifier improves; a reading of one commit.
    @property
    def miss_confirmed_blind(self) -> int:
        return sum(1 for o in self.miss_outcomes if not o.flagged)

    @property
    def control_confirmed_clean(self) -> int:
        return sum(1 for o in self.control_outcomes if not o.flagged)

    @property
    def control_false_positives(self) -> int:
        return sum(1 for o in self.control_outcomes if o.flagged)

    @property
    def baseline_headline(self) -> str:
        return f"{self.miss_confirmed_blind}/{self.total}"

    # ── target metric: miss cases caught + controls clean ────────────────
    # Higher is better; this is the published figure.
    @property
    def miss_caught(self) -> int:
        return sum(1 for o in self.miss_outcomes if o.flagged)

    @property
    def target_correct(self) -> int:
        return self.miss_caught + self.control_confirmed_clean

    @property
    def target_headline(self) -> str:
        return f"{self.target_correct}/{self.total}"

    def composition_ok(self) -> bool:
        return (
            self.miss_total == EXPECTED_MISS_TOTAL
            and self.control_total == EXPECTED_CONTROL_TOTAL
            and self.total == FROZEN_DENOMINATOR
        )

    def render(self) -> str:
        id_width = max([len("id")] + [len(o.case.id) for o in self.outcomes]) + 2
        lines = [
            "═══════ Blind-spot baseline(結構軸種子測試看不見的錯誤類型) ═══════",
            f"{'id':<{id_width}}{'category':<10}{'flagged':<9}expect_flag",
        ]
        for o in self.outcomes:
            lines.append(
                f"{o.case.id:<{id_width}}{o.case.category:<10}{o.flagged!s:<9}"
                f"{o.case.expect_flag}"
            )
        lines.append("")
        lines.append(
            f"baseline(該標未標/總案例數): {self.baseline_headline}"
            f"({self.miss_confirmed_blind} 個該標未標、"
            f"{self.control_confirmed_clean} 個對照不誤標)"
        )
        lines.append(
            f"target(修復後應達成的正確率上限): {self.target_headline}"
            f"(miss 已抓 {self.miss_caught}/{self.miss_total}、"
            f"control 誤報 {self.control_false_positives}/{self.control_total})"
        )
        if not self.composition_ok():
            lines.append(
                f"⚠ 案例組成不符規格:miss={self.miss_total}(應{EXPECTED_MISS_TOTAL})、"
                f"control={self.control_total}(應{EXPECTED_CONTROL_TOTAL})、"
                f"total={self.total}(應{FROZEN_DENOMINATOR})"
            )
        if self.control_false_positives:
            lines.append("")
            lines.append("⚠ 對照組出現誤報(不應發生 — 案例文字或 verifier 其中一邊有問題):")
            for o in self.control_outcomes:
                if o.flagged:
                    lines.append(f"  - [{o.case.id}] {'；'.join(o.reasons) or '(無 reason)'}")
        unexpected_catches = [o for o in self.miss_outcomes if o.flagged]
        if unexpected_catches:
            lines.append("")
            lines.append("已修復(miss 案例目前已被抓到,不再是漏洞):")
            for o in unexpected_catches:
                lines.append(f"  - [{o.case.id}] {'；'.join(o.reasons) or '(無 reason)'}")
        return "\n".join(lines)


@dataclass
class PositiveControlReport:
    outcomes: list[PositiveControlOutcome]

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def clean(self) -> int:
        return sum(1 for o in self.outcomes if not o.flagged)

    @property
    def must_not_regress(self) -> list[PositiveControlOutcome]:
        return [o for o in self.outcomes if o.case.label == "must_not_regress"]

    @property
    def must_stop_being_flagged(self) -> list[PositiveControlOutcome]:
        return [o for o in self.outcomes if o.case.label == "must_stop_being_flagged"]

    def render(self) -> str:
        id_width = max([len("id")] + [len(o.case.id) for o in self.outcomes]) + 2
        lines = [
            "═══════ 正控制組(今天不該被誤標 / 今天已知的誤報) ═══════",
            f"{'id':<{id_width}}{'label':<24}{'flagged':<9}expect_flag",
        ]
        for o in self.outcomes:
            lines.append(
                f"{o.case.id:<{id_width}}{o.case.label:<24}{o.flagged!s:<9}"
                f"{o.case.expect_flag}"
            )
        lines.append("")
        for o in self.must_not_regress:
            state = "OK(仍乾淨)" if not o.flagged else "⚠ 迴歸:今天被誤標了"
            lines.append(f"must_not_regress   [{o.case.id}] {state}")
        for o in self.must_stop_being_flagged:
            state = "⚠ 今天仍是已知誤報(尚未修復)" if o.flagged else "OK(已修復)"
            lines.append(f"must_stop_flagged  [{o.case.id}] {state}")
        lines.append("")
        lines.append(f"positive control 總計: {self.clean}/{self.total} 目前乾淨")
        return "\n".join(lines)


def score_blindspots(
    conn: sqlite3.Connection, cases: list[BlindspotCase] | None = None
) -> BlindspotReport:
    """In-process entry point (used by tests/test_published_numbers.py)."""
    cases = load_blindspot_cases() if cases is None else cases
    outcomes = []
    for case in cases:
        flagged, reasons = _run_one(case.answer, conn)
        outcomes.append(BlindspotOutcome(case, flagged, reasons))
    return BlindspotReport(outcomes)


def score_positive_control(
    conn: sqlite3.Connection, cases: list[PositiveControlCase] | None = None
) -> PositiveControlReport:
    cases = load_positive_control_cases() if cases is None else cases
    outcomes = []
    for case in cases:
        flagged, reasons = _run_one(case.answer, conn)
        outcomes.append(PositiveControlOutcome(case, flagged, reasons))
    return PositiveControlReport(outcomes)


def _fail_if_composition_wrong(report: BlindspotReport) -> None:
    if not report.composition_ok():
        raise SystemExit(
            "evals/blindspots_v1.json 組成不是 "
            f"{EXPECTED_MISS_TOTAL} miss + {EXPECTED_CONTROL_TOTAL} control — "
            f"實際 miss={report.miss_total} control={report.control_total}。"
            f"分母凍結為 {FROZEN_DENOMINATOR},請修正案例檔內容,不要調整這支腳本去湊數字。"
        )


def gate_problems(report: BlindspotReport, pc_report: PositiveControlReport) -> list[str]:
    """Everything that makes the published 21/25 and 6/6 untrue; empty = pass."""
    problems = []
    flagged_controls = [o.case.id for o in report.control_outcomes if o.flagged]
    if flagged_controls:
        problems.append(f"control 被誤標:{flagged_controls}")
    uncaught = [o.case.id for o in report.miss_outcomes
                if not o.flagged and o.case.id not in STILL_BLIND]
    if uncaught:
        problems.append(f"miss 未抓到:{uncaught}")
    newly_caught = [o.case.id for o in report.miss_outcomes
                    if o.flagged and o.case.id in STILL_BLIND]
    if newly_caught:
        problems.append(f"STILL_BLIND 已被抓到,請更新 21/25 與 STILL_BLIND:{newly_caught}")
    flagged_pc = [o.case.id for o in pc_report.outcomes if o.flagged]
    if flagged_pc:
        problems.append(f"positive control 被誤標:{flagged_pc}")
    if pc_report.total != EXPECTED_POSITIVE_CONTROL_TOTAL:
        problems.append(
            f"positive control 案例數 {pc_report.total}(應 {EXPECTED_POSITIVE_CONTROL_TOTAL})"
        )
    return problems


if __name__ == "__main__":  # python -m legal_agent.evaluation.blindspots
    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()

    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    _conn = connect(DB_PATH)
    try:
        _report = score_blindspots(_conn)
        assert_nonzero_scan(_report.total, "blindspots_v1.json cases")
        _fail_if_composition_wrong(_report)
        print(_report.render())
        print()

        _pc_report = score_positive_control(_conn)
        assert_nonzero_scan(
            _pc_report.total, "blindspots_positive_control_v1.json cases"
        )
        print(_pc_report.render())
        _problems = gate_problems(_report, _pc_report)
    finally:
        _conn.close()
    for _p in _problems:
        print(f"FAIL: {_p}")
    if _problems:
        raise SystemExit(1)
