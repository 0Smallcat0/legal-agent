"""口語 → 法條語彙 對照表 — query expansion across the vocabulary gap.

The measured problem (evals/RESULTS.md): people describe problems in everyday
words, statutes are written in legal vocabulary, and the two share almost no
tokens. 「精神賠償」 never appears in 民法§195, which says 「非財產上之損害」;
「欠薪」 never appears in 勞基§22, which says 「工資應全額直接給付」. BM25 can
only match what overlaps, and even bge-m3 embeddings rank these targets deep.

This module bridges the gap the cheapest honest way: a HAND-CURATED table of
(everyday triggers -> statutory vocabulary). When a trigger appears in the
query, its statutory terms are appended, so BM25 gets real lexical overlap and
the embedder gets an anchored phrase.

Discipline (why this is not a pile of guesses):
  * Every entry's statutory side is copied from the VERBATIM article text in
    the corpus — never invented, never paraphrased.
  * Expansion only ADDS terms; the user's own words are never replaced, so a
    query that already worked cannot lose its original lexical matches.
  * Every entry is justified by a golden-set measurement (see RESULTS.md).
    An entry that does not move the number does not ship.

This is retrieval-side only. It never touches the answer, the citations, or
the verifier — a wrong expansion can only surface a wrong article, which the
gates then handle exactly as they always do.
"""
from __future__ import annotations

# (everyday triggers, statutory vocabulary). Triggers are substrings matched
# against the raw query; statutory terms are verbatim fragments of the target
# articles. Ordered by domain for review, not by priority.
LEXICON: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    # ── 侵權 / 損害賠償 (民法§184, §195) ──
    # 「受損害」 is the trigger, not just the word 「賠償」: golden cases show
    # people describe the HARM (失眠、就醫) and never name the remedy.
    (("賠償", "求償", "賠錢", "告他", "提告", "損失", "損害",
      "失眠", "就醫", "生病", "受傷", "健康", "身心", "耗弱"),
     ("不法侵害他人之權利", "負損害賠償責任")),
    (("精神", "慰撫金", "困擾", "痛苦", "失眠", "焦慮"),
     ("非財產上之損害", "請求賠償相當之金額", "不法侵害他人之身體、健康")),

    # ── 噪音 / 安寧 (社維法§72, 噪音管制法§6, 公寓大廈條例§16, 民法§793) ──
    # 「聲」 catches 跑跳聲/腳步聲/歌聲 — the way people actually name noise.
    (("吵", "噪音", "很大聲", "喧嘩", "擾人", "聲"),
     ("製造噪音或深夜喧嘩", "妨害公眾安寧", "不聽禁止")),
    (("半夜", "深夜", "凌晨", "睡不著"),
     ("深夜喧嘩", "妨害公眾安寧")),
    (("報警", "警察"),
     ("妨害他人生活安寧之聲音", "由警察機關依有關法規處理")),
    (("管委會", "管理委員會", "住戶", "樓上", "樓下", "鄰居", "公寓"),
     ("住戶不得", "發生喧囂、振動")),
    # 相鄰關係 (民法§793): the everyday complaint is 「傳到我家」; the statute
    # says 「侵入」 and lists 喧囂、振動 among the intrusions it lets you stop.
    (("樓上", "樓下", "隔壁", "鄰居", "傳到", "侵入", "跑跳", "腳步", "裝修", "施工"),
     ("喧囂、振動及其他與此相類者侵入", "土地所有人", "得禁止之")),
    (("震動", "振動", "低頻", "冷氣", "機器"),
     ("發生喧囂、振動及其他與此相類之行為",)),

    # ── 勞資 (勞基法§22, §24, §84-1) ──
    (("加班費", "加班", "超時", "責任制"),
     ("延長工作時間", "延長工作時間之工資", "依下列標準加給")),
    (("欠薪", "薪水", "薪資", "工資", "沒發錢", "積欠"),
     ("工資應全額直接給付勞工", "工資之給付")),

    # ── 消費 (消保法§19) ──
    (("網購", "網路購物", "線上購買", "宅配", "電商"),
     ("通訊交易", "訪問交易之消費者")),
    (("退貨", "退款", "鑑賞期", "七天", "解約"),
     ("收受商品或接受服務後七日內", "解除契約", "無須說明理由")),

    # ── 繼承 (民法§1138, §1141) ──
    (("遺產", "繼承", "過世", "身故", "應繼分"),
     ("遺產繼承人", "同一順序之繼承人", "按人數平均繼承")),

    # ── 租賃 (租賃住宅條例§7) ──
    (("押金", "保證金", "退租", "房東"),
     ("押金之金額", "不得逾二個月之租金總額", "返還租賃住宅")),

    # ── 交通 (民法§191-2) ──
    (("車禍", "擦撞", "撞到", "機車", "汽車", "肇事"),
     ("非依軌道行駛之動力車輛", "在使用中加損害於他人")),
)


def expansions(text: str) -> list[str]:
    """Statutory terms triggered by `text`, de-duplicated, in table order.
    Exposed separately so a caller (or a reviewer) can see exactly what a
    query was widened with."""
    out: list[str] = []
    for triggers, statutory in LEXICON:
        if any(t in text for t in triggers):
            out.extend(term for term in statutory if term not in out)
    return out


def expand(text: str) -> str:
    """`text` plus any triggered statutory vocabulary. The user's own wording
    is always preserved verbatim at the front."""
    extra = expansions(text)
    return f"{text}  {'  '.join(extra)}" if extra else text
