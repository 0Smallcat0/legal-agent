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
      "失眠", "就醫", "生病", "受傷", "健康", "身心", "耗弱",
      "骨折", "住院", "請假", "沒收入", "醫藥費", "醫療費"),
     ("不法侵害他人之權利", "負損害賠償責任",
      # §193 — the article a hurt person actually needs: lost earning capacity
      # and the extra cost of living with the injury. A session asking exactly
      # that ("請假兩個月沒收入") got §191-2 and §192 (死亡) instead.
      "喪失或減少勞動能力或增加生活上之需要")),
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
    # 「報警」 alone is NOT a noise signal — measured: a broken-leg car-crash
    # session had 噪音管制法§6 promoted into its window off the word 警察.
    (("報警處理噪音", "警察來測音量"),
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

    # ── 買賣標的物瑕疵 (民法§354, §359, §360) ──
    # A BUYER's words (交屋/過戶/中古屋/賣方/現況說明書) reach none of the warranty
    # articles, while 「漏水」 drags in the TENANCY row: 「交屋後才發現主臥滲水,
    # 賣方沒講」 came back with 民法§430 (a landlord's duty to repair), 租賃住宅
    # 條例§8 and §437 — the entire window was about renting.
    (("交屋", "過戶", "中古屋", "預售屋", "賣方", "屋主", "仲介", "現況說明書",
      "履約保證", "買房", "買屋"),
     ("缺少出賣人所保證之品質者", "出賣人故意不告知物之瑕疵者亦同",
      "無滅失或減少其價值之瑕疵", "買受人得解除其契約或請求減少其價金")),

    # ── 約定專用 / 車位 / 共用部分 (公寓大廈條例§33, §7) ──
    # 「我買房子時有含一個車位,管委會要把地下室改成儲藏室出租」 was answered out of
    # 民法§358/§443/§435 — sale-warranty and tenancy — partly because 買房 is a
    # trigger on the warranty row. §33 is the article: a resolution touching a
    # 約定專用 part does not take effect without that owner's consent.
    (("車位", "停車位", "約定專用", "共用部分", "區分所有權", "權狀", "地下室",
      "頂樓平台", "公共設施"),
     ("應經該專有部分區分所有權人同意", "區分所有權人會議之決議，未經依下列各款事項辦理者，不生效力",
      "共用部分不得獨立使用供做專有部分")),

    # ── 名譽 / 公然侮辱 / 誹謗 (刑法§309, §310, 民法§195) ──
    # 「有人在社區臉書社團留言罵我人渣、說我偷東西」 retrieved 民法§793/§791/§790
    # and §190 — 相鄰關係 and animals — because 社區/鄰居 are neighbour words and
    # nothing in the table mapped 罵/毀謗/留言 to 名譽.
    (("辱罵", "罵我", "公然侮辱", "毀謗", "誹謗", "名譽", "造謠", "抹黑",
      "亂講", "留言攻擊", "人身攻擊"),
     ("公然侮辱人者", "指摘或傳述足以毀損他人名譽之事者",
      "散布文字、圖畫犯前項之罪者", "其名譽被侵害者，並得請求回復名譽之適當處分")),

    # ── 消費借貸 / 欠錢不還 (民法§474, §478, §233, §203) ──
    # 「朋友借二十萬說三個月還,一年多都推說沒錢,有借據跟本票」 was REFUSED with
    # 「這個問題我的資料庫沒有涵蓋」 — but the corpus answers both questions he
    # asked: §478 how to demand it back, §233+§203 whether interest runs (5% a
    # year by default). Nothing in 借據/本票/推說沒錢 overlaps 消費借貸/遲延利息.
    (("借錢", "借款", "欠錢", "還錢", "借據", "本票", "欠我", "討債", "催討",
      "借出去", "沒還"),
     ("稱消費借貸者", "借用人應於約定期限內，返還與借用物種類、品質、數量相同之物",
      "貸與人亦得定一個月以上之相當期限，催告返還",
      "債權人得請求依法定利率計算之遲延利息", "週年利率為百分之五")),

    # ── 繼承 (民法§1138, §1141) ──
    # §1144 answers 「媽媽分多少」 and §1151 answers 「大哥可以自己動用嗎」 — the
    # two questions a session actually asked. Both were outside the window while
    # 特留分/扶養/遺囑執行人 articles filled it.
    (("遺產", "繼承", "過世", "身故", "應繼分", "分遺產", "存摺印章", "遺囑"),
     ("遺產繼承人", "同一順序之繼承人", "按人數平均繼承",
      "配偶有相互繼承遺產之權，其應繼分",
      "在分割遺產前，各繼承人對於遺產全部為公同共有")),

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

    # ── 轉租 / 二房東 (民法§443, §444) ──
    # 「跟二房東租的,真正的房東說不知道有轉租」 retrieved 租賃住宅條例§30 — which
    # is about a LICENSED 包租業, not a private sublessor — and the model
    # answered out of it. §443 is what decides whether the head landlord can
    # terminate, §444 whether the head tenancy survives.
    (("轉租", "二房東", "分租", "頂讓", "接手租約"),
     ("承租人非經出租人承諾，不得將租賃物轉租於他人",
      "出租人得終止契約", "其與出租人間之租賃關係，仍為繼續")),

    # ── 職業災害 (勞基法§59) ──
    # 「工作時手指被夾傷,老闆說自己不小心」 retrieved 民法§188/§487-1 and 勞基§63-1
    # (dispatched workers) — everything except the article that answers the two
    # questions asked: who pays the medical bill and the wages during recovery.
    (("職災", "職業災害", "工作時受傷", "上班受傷", "夾傷", "壓傷", "燙傷",
      "工傷", "公傷", "工安"),
     ("勞工因遭遇職業災害而致死亡、失能、傷害或疾病時",
      "雇主應補償其必需之醫療費用", "雇主應按其原領工資數額予以補償")),

    # ── 預付型交易 / 店家倒閉 (消保法§17, 民法§226, §256) ──
    # 「買了三萬元療程套票,店突然關門」 scored under the insufficiency floor and
    # was refused — but the corpus does cover it: 預付型交易之履約擔保 is a named
    # item in 消保法§17, and 給付不能 -> 解除契約 is 民法§226/§256.
    (("套票", "預付", "儲值", "課程包", "點數", "倒閉", "關門", "跑路",
      "停業", "聯絡不上"),
     ("預付型交易之履約擔保", "致給付不能者，債權人得請求賠償損害",
      "債權人於有第二百二十六條之情形時，得解除其契約")),

    # ── 未成年子女權利義務 / 會面交往 (民法§1055, §1055-1) ──
    # 「監護權判給她,約定每兩週看小孩一次,她都不讓我見」 retrieved 家暴法§31/§61
    # and the model concluded 「可能構成違反保護令罪」 — there is no protective
    # order in this case at all.
    (("監護權", "探視", "會面交往", "看小孩", "見小孩", "親權", "未成年子女",
      "離婚協議", "扶養費"),
     ("對於未成年子女權利義務之行使或負擔", "應依子女之最佳利益",
      "妨礙他方對未成年子女權利義務行使負擔之行為")),

    # ── 交通 (民法§191-2) ──
    (("車禍", "擦撞", "撞到", "機車", "汽車", "肇事"),
     ("非依軌道行駛之動力車輛", "在使用中加損害於他人")),

    # ── 定型化契約 / 退費 (消保法§11-1, §12, 民法§247-1) ──
    # Measured on a lived session: 「健身房兩年約,店家說不能退」 retrieved
    # 民法§976 (解除婚約!), §561 and 勞基§11 — everything in the corpus that
    # mentions 終止契約. The articles that decide a membership dispute say
    # 定型化契約 / 顯失公平, words no gym member would ever type.
    (("解約", "退費", "退錢", "違約金", "會員", "定型化", "審閱", "綁約",
      "不能退", "手續費"),
     ("定型化契約中之條款違反誠信原則，對消費者顯失公平者，無效",
      "應有三十日以內之合理期間，供消費者審閱全部條款內容",
      "按其情形顯失公平者，該部分約定無效", "加重他方當事人之責任者")),

    # ── 工作物所有人責任 (民法§191) ──
    # 「樓上水管破裂漏到我家」 got 租賃住宅條例§8 — a LANDLORD's repair duty —
    # for an owner-occupied flat. §191 is the article that puts the loss on the
    # owner of the thing that broke.
    (("漏到", "破裂", "爆管", "淹到", "泡壞", "滲到", "掉落", "外牆"),
     ("土地上之建築物或其他工作物所致他人權利之損害", "由工作物之所有人負賠償責任")),

    # ── 親密關係騷擾 (家暴法§63-1, §14, §2) ──
    # Measured on a lived session: 「前男友一直傳訊息、在我上班的地方等我」 retrieved
    # 家暴法§2/§13 only, and the 8B model asserted 「這是家庭暴力」 for someone who
    # was never a 家庭成員. §63-1 is the article that actually reaches an ex —
    # 「現有或曾有親密關係之未同居伴侶」準用保護令 — and §14 is what a 保護令 can
    # order (禁止騷擾、接觸、跟蹤、通話, 遠離特定場所).
    (("跟蹤", "騷擾", "糾纏", "一直傳訊息", "保護令", "很害怕", "心生畏怖",
      "按我家電鈴", "堵我"),
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
    """Statutory terms triggered by `text`, de-duplicated, MOST SPECIFICALLY
    triggered first.

    Order matters to one caller: the retriever gives the first few phrases
    reserved seats in the top-k window, and table order made that allocation
    arbitrary. Measured on a lived stalking session — 「前男友」 (3 chars) lost
    its seats to entries triggered by 「聲」 (1 char) simply because the noise
    rows sit higher in the table, so 家暴法§63-1 and §14 never surfaced. A long
    trigger matching is far less likely to be incidental than a short one.
    """
    scored: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()
    for row, (triggers, statutory) in enumerate(LEXICON):
        matched = [t for t in triggers if t in text]
        if not matched:
            continue
        specificity = max(len(t) for t in matched)
        for position, term in enumerate(statutory):
            if term in seen:
                continue
            seen.add(term)
            # position keeps a row's own order — tie-breaking on the term text
            # sorted 「持續性監視…」 (§2) above 「現有或曾有親密關係之未同居伴侶」
            # (§63-1) and cost the stalking case its most important article.
            scored.append((-specificity, row, position, term))
    scored.sort()
    return [term for _spec, _row, _pos, term in scored]


def expand(text: str) -> str:
    """`text` plus any triggered statutory vocabulary. The user's own wording
    is always preserved verbatim at the front."""
    extra = expansions(text)
    return f"{text}  {'  '.join(extra)}" if extra else text
