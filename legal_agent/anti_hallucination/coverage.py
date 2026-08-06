"""Gate 3 companion — the bodies of law this corpus does NOT carry.

The honesty tier decided "is the corpus covering this?" from an absolute BM25
score, and a score cannot know that 消費者債務清理條例 is missing. Measured on a
35-case probe (`evals/honesty_probe_v1.json`, 20 out-of-scope + 15 in-scope but
lexically thin), the absolute floor fails in BOTH directions at once:

    out-of-scope refused        5/20   (15 answered anyway)
    in-scope falsely refused    2/15   (勞基法§11 資遣 at 39.19, 個資法§29 at 44.65)

and the ranges interleave completely — out-of-scope 35.7-503.5 against in-scope
39.2-417.4. The single highest score in the whole probe is an out-of-scope one
(oos-09 本票裁定, 503.5, answered from 民法§473 消費借貸). No constant separates
those, which is why four score-shaped signals have already been measured and
rejected (absolute BM25, BM25 on raw words, dense cosine, out-of-vocabulary term
share — evals/RESULTS.md, "Measured, then NOT shipped").

So this table does not score anything. "Is 票據法 in the corpus" is a SET
QUESTION, and the answer is a fact about the statute_ids we shipped. When a
question names a body of law we do not carry, the tier is insufficient no matter
how high BM25 ran.

WHAT THIS IS NOT. It refuses the absences someone enumerated — a closed list,
not a general out-of-scope detector. Three of the 20 probe cases miss precisely
because the user never names the domain (a starved dog, an informal remittance,
a house on farmland are described in facts, not in legal vocabulary). Adding a
row is cheap; pretending the list is complete would be the same over-confidence
this file exists to remove.

TWO INVARIANTS, both tested (tests/test_coverage_gate.py):
  1. every statute named here is absent from the corpus — so importing 消債條例
     turns the test red and forces the row out. That is the property the
     absolute floor lacked: it went stale in silence when the corpus grew from
     11 articles to 2,922 and nothing said so for a week.
  2. no trigger fires on an in-scope question. Triggers were PRUNED against 210
     in-scope queries (168 real sessions + 27 golden + 15 probe), so 0/210 is a
     fit, not an estimate; 「本票」「卡債」「健保」「非自願離職」「遺產稅」「農地」
     「停權」 were all dropped for firing on real in-scope sessions where the term
     was mentioned in passing. The held-out check is 386 harvested judgments:
     11 fire (2.8%), and all 11 are genuinely disputes of the named absent law
     (裁判費核定 6, 商業事件 2, 執行異議 2, 消債更生 1) — correct refusals rather
     than false alarms, verified case by case.
"""
from __future__ import annotations

# statute we do NOT carry -> lay phrases that name it.
# Order is arbitrary; the first match wins and only the name is reported.
ABSENT_DOMAINS: dict[str, tuple[str, ...]] = {
    "商標法": ("商標",),
    "專利法": ("專利",),
    "公司法": ("股權", "股東會", "董事會"),
    "所得稅法": ("綜合所得稅", "列舉扣除額", "報稅", "免稅額", "所得稅"),
    # 「本票」 alone fires on a 借款 session that merely used one as evidence —
    # that dispute IS 民法 消費借貸 and must not be refused. 「本票裁定」 is the
    # non-contentious ruling itself, which is 非訟事件法 + 票據法.
    "票據法": ("本票裁定", "支票", "票據法", "退票"),
    # 「卡債」 dropped for the same reason: a real session about 債權讓與 (民法§297)
    # opened with it.
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
