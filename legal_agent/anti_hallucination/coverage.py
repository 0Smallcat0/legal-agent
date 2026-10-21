"""Gate 3 companion — the bodies of law this corpus does NOT carry.

No BM25 threshold separates out-of-scope from in-scope questions (the score
ranges interleave completely; see evals/HISTORY.md and RESULTS.md "Measured,
then NOT shipped"). "Is 票據法 in the corpus" is a set question, so a query that
names a body of law we do not carry is refused however high BM25 ran.

Closed-world caveat: this refuses only the absences someone enumerated. A
question that describes the facts without naming the domain is not caught.

Two invariants, both tested (tests/test_coverage_gate.py):
  1. every statute named here is absent from the corpus, so importing one turns
     the test red and forces its row out;
  2. no trigger fires on an in-scope question — triggers were pruned against
     210 in-scope queries, so 0/210 is a fit, not an estimate (held-out numbers
     in evals/HISTORY.md).
"""
from __future__ import annotations

# statute we do NOT carry -> lay phrases that name it.
# Order is arbitrary; the first match wins and only the name is reported.
ABSENT_DOMAINS: dict[str, tuple[str, ...]] = {
    "商標法": ("商標",),
    "專利法": ("專利",),
    "公司法": ("股權", "股東會", "董事會"),
    "所得稅法": ("綜合所得稅", "列舉扣除額", "報稅", "免稅額", "所得稅"),
    # Not bare 「本票」: a 借款 dispute (民法 消費借貸) often cites one as evidence.
    "票據法": ("本票裁定", "支票", "票據法", "退票"),
    # Not 「卡債」: it also opens 債權讓與 (民法§297) sessions.
    "消費者債務清理條例": ("更生", "前置協商", "債務清理", "清算程序"),
    "勞資爭議處理法": ("勞資爭議", "不當勞動行為", "裁決委員會"),
    "強制執行法": ("強制執行", "查封", "執行名義"),
    "民事訴訟法": ("支付命令", "督促程序", "小額訴訟", "裁判費", "起訴狀"),
    "全民健康保險法": ("補充保費", "全民健康保險"),
    "就業保險法": ("失業給付", "就業保險"),
    "保險法": ("壽險", "人壽保險", "據實告知", "保單"),
    "動物保護法": ("動物保護", "飼主"),
    "醫療法": ("病歷",),
    "遺產及贈與稅法": ("贈與稅", "遺產稅申報"),
    "銀行法": ("匯兌", "外匯"),
    "證券交易法": ("內線交易", "上市公司", "未公開資訊"),
    "農業發展條例": ("農舍", "違章建築"),
    "政府採購法": ("政府採購", "標案", "不良廠商"),
}


def absent_domain(query: str) -> tuple[str, str] | None:
    """Return (statute we lack, the phrase that named it), or None.

    `query` is the assembled fact string — the same text BM25 scores — so the
    check sees exactly what the user and the intake put in front of retrieval.
    """
    if not query:
        return None
    for statute, triggers in ABSENT_DOMAINS.items():
        for trigger in triggers:
            if trigger in query:
                return statute, trigger
    return None
