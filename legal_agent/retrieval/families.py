"""Which KIND of dispute an article or a court's 案由 belongs to.

Two derived tables, no hand labels: 民法 article ranges follow the code's own
編/章/節 structure, and 案由 keywords are the court's own filing vocabulary.
`evaluation/judgment_relevance` grades with them; `retrieval/judgments` ranks
with them (a judgment whose 案由 is the same kind as the article it shares
with the answer goes first). Sharing one table means the grader and the ranker
can never disagree on what 「same kind」 is — and also that the relevance grade
is partly what the ranker optimises, which RESULTS §11 says where it reports it.
"""
from __future__ import annotations

import re

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
    # Families sessions ask about that had no 案由 keyword at all, so no
    # judgment could ever count for them (judgment_coverage, RESULTS §10).
    # None of the 386 shipped 案由 contains these; they only name new ones.
    ("返還借用物", "使用借貸"), ("使用借貸", "使用借貸"),
    ("寄託", "寄託"),
    ("保證債務", "保證"), ("連帶保證", "保證"),
    ("社會秩序維護法", "秩序"),
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
