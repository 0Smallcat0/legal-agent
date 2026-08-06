"""Is the reference judgment about the reader's KIND of problem? (SPEC §1.2)

The judgment layer's correctness was never in doubt: `related_judgments` JOINs
on articles the pipeline already retrieved, so a case cannot appear unless it
cites the same law. That is relevance to an ARTICLE, guaranteed by code.

Relevance to the reader's DISPUTE was never measured. RESULTS.md carried it as
a debt with n=1 evidence. This harness supplies the number.

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
reported as UNLABELLED rather than scored either way, because the field the
reader would have to judge by is empty. Counting them as hits would flatter the
number; counting them as misses would blame the layer for the court's filing
vocabulary.

Run:  python -m legal_agent.evaluation.judgment_relevance [evals/real_sessions.json]
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── side 1: session -> family, from the articles a careful person expects ──
# Ranges are 民法's own structure (編/章/節). A range is written where the whole
# section shares one dispute type; single articles where it does not.
_CIVIL_RANGES: tuple[tuple[int, int, str], ...] = (
    (14, 15, "監護"),          # 監護/輔助宣告 — the person, not the general part
    (125, 147, "時效"),
    (153, 166, "契約成立"),
    (179, 183, "不當得利"),
    (184, 198, "侵權"),
    (199, 344, "債之效力"),    # 遲延、損害賠償範圍、代位撤銷、連帶、抵銷、讓與
    (345, 378, "買賣"),
    (406, 420, "贈與"),
    (421, 463, "租賃"),
    (464, 473, "使用借貸"),
    (474, 481, "消費借貸"),
    (482, 489, "僱傭"),
    (490, 514, "承攬"),
    (528, 552, "委任"),
    (589, 612, "寄託"),
    (739, 756, "保證"),
    (767, 800, "所有權"),
    (818, 831, "共有"),
    (860, 883, "擔保物權"),
    (1052, 1058, "婚姻"),
    (1059, 1090, "親子"),
    (1091, 1113, "監護"),
    (1114, 1121, "扶養"),
    (1138, 1225, "繼承"),
)
# 總則 articles that carry a dispute of their own rather than a topic.
_CIVIL_SINGLES: dict[int, str] = {
    8: "監護", 12: "行為能力", 56: "住戶", 71: "契約效力", 72: "契約效力",
    74: "契約效力", 87: "契約效力", 88: "契約效力", 92: "契約效力",
    98: "契約成立", 110: "委任", 122: "時效", 148: "權利濫用",
}
_SPECIAL_STATUTES: dict[str, str] = {
    "勞動基準法": "勞動",
    "家庭暴力防治法": "家暴",
    "公寓大廈管理條例": "住戶",
    "消費者保護法": "消費",
    "個人資料保護法": "個資",
    "租賃住宅市場發展及管理條例": "租賃",
    "社會秩序維護法": "秩序",
    "道路交通管理處罰條例": "交通",
}

# ── side 2: 案由 -> family, from the court's own filing vocabulary ──
# Ordered: the first keyword found wins, so specific phrases precede loose ones
# (「分割遺產」 is 繼承, not 共有, even though it contains 分割).
_CASE_TYPE_FAMILIES: tuple[tuple[str, str], ...] = (
    ("扶養", "扶養"),
    ("遺產", "繼承"), ("繼承", "繼承"), ("遺囑", "繼承"),
    ("保護令", "家暴"), ("緊急處置", "家暴"), ("暫時處分", "家暴"),
    ("離婚", "婚姻"), ("贍養費", "婚姻"),
    ("親權", "親子"), ("子女", "親子"), ("生父", "親子"), ("會面交往", "親子"),
    ("監護", "監護"), ("輔助宣告", "監護"), ("死亡宣告", "監護"),
    ("受監護宣告人", "監護"),
    ("遷讓房屋", "租賃"), ("租賃", "租賃"), ("租金", "租賃"),
    ("分割共有物", "共有"), ("共有", "共有"),
    ("管理費", "住戶"), ("區分所有權人會議", "住戶"),
    ("僱傭關係", "勞動"), ("資遣費", "勞動"), ("給付工資", "勞動"),
    ("退休金", "勞動"), ("職業災害", "勞動"),
    ("承攬", "承攬"), ("工程款", "承攬"), ("修復漏水", "承攬"),
    ("修繕費", "承攬"),
    ("借款", "消費借貸"), ("清償債務", "消費借貸"), ("本票", "消費借貸"),
    ("消費款", "消費借貸"), ("信用卡", "消費借貸"),
    ("價金", "買賣"), ("貨款", "買賣"), ("分期買賣", "買賣"),
    ("不當得利", "不當得利"),
    ("所有權移轉登記", "所有權"), ("拆屋還地", "所有權"),
    ("拆除地上物", "所有權"), ("返還土地", "所有權"), ("塗銷", "所有權"),
    ("土地所有權", "所有權"), ("通行權", "所有權"), ("排除侵害", "所有權"),
    ("土地使用補償", "所有權"),
    ("抵押物", "擔保物權"), ("抵押權", "擔保物權"),
    # 「損害賠償(交通)」 (23 cases, both paren styles) names the dispute even
    # though bare 「損害賠償」 does not — a reader knows it was a road accident.
    ("侵權行為", "侵權"), ("國家賠償", "侵權"), ("交通", "侵權"),
    ("違約金", "契約效力"), ("履行契約", "契約效力"), ("契約無效", "契約效力"),
    ("撤銷贈與", "贈與"),
    ("服務報酬", "委任"), ("交付帳冊", "委任"), ("投資款", "委任"),
    ("保險金", "保險"),
    ("更生", "債務清理"), ("清算", "債務清理"),
)
# 案由 that name no dispute — the reader learns nothing from them. Matched only
# after every keyword above has failed, so 「侵權行為損害賠償」 is 侵權 and bare
# 「損害賠償」 is not scored at all.
_UNINFORMATIVE = re.compile(r"^(請求)?損害賠償(等)?$")

# Rules that cut ACROSS settings rather than naming one. 民法§273 (連帶債務) is
# not a kind of dispute — it is a rule that applies inside a loan, a sale or a
# repair job alike, so a 清償借款 case shown for a joint-debt question is right
# and grading it against a 「債之效力 family」 would score a hit as a miss. Applied
# to BOTH sides: a session with nothing but cross-cutting articles is not
# scorable, and a 案由 like 「履行契約」 names no setting either.
_CROSS_CUTTING = frozenset({
    "債之效力", "契約效力", "契約成立", "時效", "權利濫用", "行為能力",
})

_ARTICLE = re.compile(r"^(?P<sid>.+?)第(?P<num>\d+)(?:-\d+)?條")


def statute_family(ref: str) -> str | None:
    """Family of one 「民法第432條」-style reference, or None if unmapped."""
    m = _ARTICLE.match(ref)
    if not m:
        return None
    sid, num = m.group("sid"), int(m.group("num"))
    if sid in _SPECIAL_STATUTES:
        return _SPECIAL_STATUTES[sid]
    if sid != "民法":
        return None
    if num in _CIVIL_SINGLES:
        return _CIVIL_SINGLES[num]
    for lo, hi, fam in _CIVIL_RANGES:
        if lo <= num <= hi:
            return fam
    return None


def case_type_family(case_type: str | None) -> str | None:
    """Family of a court's 案由; None when it names no dispute.

    The EARLIEST keyword in the string wins, not the first in the table: a court
    writes the claim it is deciding first and appends the ancillary ones after
    「等(含…)」, so 「離婚等(含未成年子女親權酌定、扶養費等)」 is a 婚姻 case that also
    settled support, not a 扶養 case. Table order is only the tiebreak.
    """
    if not case_type:
        return None
    best: tuple[int, int, str] | None = None
    for rank, (keyword, fam) in enumerate(_CASE_TYPE_FAMILIES):
        at = case_type.find(keyword)
        if at >= 0 and (best is None or (at, rank) < best[:2]):
            best = (at, rank, fam)
    return best[2] if best else None


def is_uninformative(case_type: str | None) -> bool:
    return bool(case_type) and bool(_UNINFORMATIVE.match(case_type.strip()))


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
    own = None
    if conn is None:
        from legal_agent.config import DB_PATH
        from legal_agent.data.database import connect

        own = connect(DB_PATH)
        conn = own
    try:
        report = RelevanceReport()
        for case in json.loads(Path(path).read_text(encoding="utf-8")):
            expected = list(case.get("expected_statutes", []))
            families = sorted({f for f in (statute_family(e) for e in expected)
                               if f and f not in _CROSS_CUTTING})
            found = retrieve(case["query"], k=k or DEFAULT_K, conn=conn)
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
    finally:
        if own is not None:
            own.close()
    report.dense_fallbacks = dense_fallback_count()
    return report


if __name__ == "__main__":   # python -m legal_agent.evaluation.judgment_relevance
    import sys as _sys

    from legal_agent.evaluation import enable_utf8_stdout

    enable_utf8_stdout()
    target = _sys.argv[1] if len(_sys.argv) > 1 else "evals/real_sessions.json"
    print(run_judgment_relevance(target).render())
