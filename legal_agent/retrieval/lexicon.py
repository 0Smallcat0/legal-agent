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
    # Nobody reporting their upstairs neighbour writes 「噪音」. They describe the
    # BEHAVIOUR — 跑跳、拖椅子、哭鬧 — and measured, that wording missed 社維§72
    # entirely (outside the top 60) because not one token overlapped.
    (("吵", "噪音", "很大聲", "喧嘩", "擾人", "聲",
      "跑跳", "跑來跑去", "拖椅子", "拖桌", "蹦", "砰", "哭鬧", "尖叫",
      "打球", "跳繩", "甩門", "摔門"),
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
    # Part-timers never say 「工資」. They say 時薪/打工/不算錢 — measured: the
    # 「提早半小時不算錢」 session missed §22 entirely (it ranked 31).
    (("欠薪", "薪水", "薪資", "工資", "沒發錢", "積欠",
      "時薪", "日薪", "月薪", "打工", "工讀", "不算錢", "沒算錢", "沒給錢",
      "少給", "扣薪", "準備時間", "提早到"),
     ("工資應全額直接給付勞工", "工資之給付")),

    # ── 消費 (消保法§19) ──
    (("網購", "網路購物", "線上購買", "宅配", "電商"),
     ("通訊交易", "訪問交易之消費者")),
    (("退貨", "退款", "鑑賞期", "七天", "解約"),
     ("收受商品或接受服務後七日內", "解除契約", "無須說明理由")),
    # 買賣瑕疵擔保 (民法§354, §359). 消保法§19 only reaches a 企業經營者's
    # 通訊交易; a C2C 二手 sale lives in 民法. Measured: 「收到三天就當機」
    # surfaced §19 and nothing else — §359 ranked 43, §354 outside the top 60.
    (("瑕疵", "故障", "壞掉", "壞了", "不能用", "當機", "開不了機",
      "二手", "貨不對版", "跟說的不一樣", "維修", "換貨", "退錢"),
     ("無滅失或減少其價值之瑕疵", "減少其通常效用或契約預定效用之瑕疵",
      "買受人得解除其契約或請求減少其價金")),

    # ── 繼承 (民法§1138, §1141) ──
    (("遺產", "繼承", "過世", "身故", "應繼分"),
     ("遺產繼承人", "同一順序之繼承人", "按人數平均繼承")),

    # ── 租賃 (租賃住宅條例§7) ──
    (("押金", "保證金", "退租", "房東"),
     ("押金之金額", "不得逾二個月之租金總額", "返還租賃住宅")),
    # 租賃物修繕 (民法§430, 租賃住宅條例§8, 民法§423). The tenant says 漏水/發霉/
    # 沒來修; the statute says 修繕之必要/催告. Measured: the 兩個月沒修 session
    # left §430 at rank 10 — one slot outside the window that decides the answer.
    (("漏水", "滲水", "壁癌", "發霉", "長霉", "修繕", "修理", "沒修", "不修",
      "熱水器", "馬桶", "水管", "冷氣"),
     ("租賃物如有修繕之必要", "催告出租人修繕",
      "自行修繕而請求出租人償還其費用或於租金中扣除之",
      "保持其合於約定使用、收益之狀態")),
    # 押金扣抵的爭點是「這算不算損壞」(民法§432 第2項但書) — 正常使用造成的
    # 變更或毀損不負賠償責任. Measured: 「釘孔要扣押金」 never surfaced §432 at
    # all (outside the top 60): the everyday words share no token with the article.
    (("釘孔", "掛畫", "牆壁", "刮傷", "磨損", "折舊", "損壞", "弄壞", "恢復原狀",
      "回復原狀", "扣押金", "扣錢"),
     ("以善良管理人之注意，保管租賃物", "致租賃物毀損、滅失者，負損害賠償責任",
      "依約定之方法或依物之性質而定之方法為使用、收益")),

    # ── 交通 (民法§191-2) ──
    (("車禍", "擦撞", "撞到", "機車", "汽車", "肇事"),
     ("非依軌道行駛之動力車輛", "在使用中加損害於他人")),

    # ── 親密關係騷擾 (家暴法§63-1, §14, §2) ──
    # Measured on a lived session: 「前男友一直傳訊息、在我上班的地方等我」 retrieved
    # 家暴法§2/§13 only, and the 8B model asserted 「這是家庭暴力」 for someone who
    # was never a 家庭成員. §63-1 is the article that actually reaches an ex —
    # 「現有或曾有親密關係之未同居伴侶」準用保護令 — and §14 is what a 保護令 can
    # order (禁止騷擾、接觸、跟蹤、通話, 遠離特定場所).
    (("前男友", "前女友", "前夫", "前妻", "分手", "跟蹤", "騷擾", "糾纏",
      "一直傳訊息", "等我", "保護令", "很害怕", "心生畏怖"),
     ("現有或曾有親密關係之未同居伴侶", "親密關係伴侶",
      "為騷擾、接觸、跟蹤、通話、通信或其他非必要之聯絡行為",
      "持續性監視、跟追或掌控他人行蹤及活動之行為", "民事保護令")),

    # ── 擅自進入住宅 (刑法§306) ──
    (("擅自進入", "自己開門", "沒經過我同意", "闖進", "侵入", "備份鑰匙", "偷進"),
     ("無故侵入他人住宅", "受退去之要求而仍留滯者")),

    # ── 資遣 / 預告 (勞基法§16, §17) ──
    (("資遣", "被辭", "叫我走", "不用來了", "非自願離職", "預告", "遣散"),
     ("預告期間", "應給付預告期間之工資", "應依下列規定發給勞工資遣費",
      "相當於一個月平均工資之資遣費")),
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
