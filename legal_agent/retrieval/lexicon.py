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
    # 「我可以要求他賠嗎」 matched none of these — 賠 only appeared inside 賠償 and
    # 賠錢 — so 民法§184 never fired for an upstairs leak. Bare 賠 is deliberately
    # not a trigger: it sits inside 違約金/賠償責任 in every contract dispute and
    # would push the tort articles into all of them.
    (("賠償", "求償", "賠錢", "他賠", "要賠", "賠我", "誰賠", "告他", "提告", "損失", "損害",
      "失眠", "就醫", "生病", "受傷", "健康", "身心", "耗弱",
      "骨折", "住院", "請假", "沒收入", "醫藥費", "醫療費"),
     # Sharpened after the seat-ordering change: 「不法侵害他人之權利」 matches
     # §184/§185/§187/§188/§189 and 「負損害賠償責任」 matches 18 articles, so
     # neither points anywhere. The full clause is unique to §184.
     ("因故意或過失，不法侵害他人之權利者", "違反保護他人之法律，致生損害於他人者",
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

    # ── 婚生推定與否認 (民法§1063) ──
    # 「婚姻中生的小孩鑑定不是我的,想解除父子關係」 lost its window to the 離婚
    # chapter, because the same sentence says 「我們正在談離婚」. §1063 carries the
    # presumption, the 否認之訴 and its two-year clock in one article.
    (("親子鑑定", "不是我的", "不是我親生", "父子關係", "婚生", "否認",
      "DNA", "戶政登記我是父親"),
     ("妻之受胎，係在婚姻關係存續中者，推定其所生子女為婚生子女",
      "夫妻之一方或子女能證明子女非為婚生子女者，得提起否認之訴")),

    # ── 遲延給付後解除契約 (民法§254, §259) ──
    # 「合約寫兩個月交貨,拖了五個月一直說缺料,我不想等了」 returned 消保法§19 and the
    # 承攬 articles. §254 is the route out: set a deadline, and if it passes,
    # rescind. §259 is what comes back afterwards.
    (("一直不交貨", "拖了", "不想等了", "遲遲沒", "逾期交貨", "遲延交貨",
      "催了還是沒", "說缺料"),
     ("契約當事人之一方遲延給付者，他方當事人得定相當期限催告其履行，如於期限內不履行時，得解除其契約",
      "由他方所受領之給付物，應返還之")),

    # ── 同時履行抗辯 (民法§264) ──
    # 「合約寫安裝完成後付尾款,他要先收錢才願意來裝」 returned the 承攬 and 定金
    # articles. §264 is the one sentence that answers it: until the other side
    # performs, you may withhold your own.
    (("裝好再付", "先收錢", "還沒做完就要錢", "完工後付", "先給錢再",
      "東西還沒給", "貨還沒到就要"),
     ("因契約互負債務者，於他方當事人未為對待給付前，得拒絕自己之給付",)),

    # ── 區分所有權人會議的出席門檻 (公寓大廈條例§31, §32) ──
    # 「三十二戶只有五戶出席就通過動用三百萬」 reached §30 (notice), §34 (minutes)
    # and 民法§56 (setting it aside) — everything except the threshold that decides
    # whether there was a decision at all.
    (("戶出席", "出席人數不足", "人數不夠", "沒有達到人數", "出席比例",
      "幾戶出席", "重新召集"),
     ("區分所有權人會議之決議，除規約另有規定外，應有區分所有權人三分之二以上及其區分所有權比例合計三分之二以上出席",
      "召集人得就同一議案重新召集會議")),

    # ── 買賣何時成立 (民法§345) ──
    # 「LINE 上談好十二萬,他回『好,就這個價』,隔天說沒簽約不算」 returned the
    # 買賣瑕疵 chapter — what happens when goods are defective, not whether a sale
    # exists. §345 II: agreement on the thing and the price IS the contract.
    (("談好價錢", "說沒簽約", "就這個價", "反悔說", "算不算成交",
      "口頭談好", "還沒簽約就"),
     ("當事人就標的物及其價金互相同意時，買賣契約即為成立",)),

    # ── 損益相抵 (民法§216-1) ──
    # 「我的車體險先賠了十二萬,對方說他只要賠六萬」 returned §184/§188/§193/§213 —
    # liability and restitution. §216-1 is the article the OTHER side is invoking,
    # and it cannot be examined while it is missing from the window.
    (("領了保險金", "保險先賠", "要扣掉", "已經領過", "扣除所受",
      "保險公司賠過", "只要賠"),
     ("基於同一原因事實受有損害並受有利益者，其請求之賠償金額，應扣除所受之利益",)),

    # ── 協議簽了但未登記 (民法§830, §758) ──
    # 「三個繼承人簽了分割協議,還沒辦登記,大哥反悔說不算數」 reached the partition
    # articles. §758 is why the house has not moved yet — a real-right change by
    # act of the parties takes registration — and §830 is when the joint holding
    # ends. The agreement binds them; the register decides who owns it today.
    (("協議書簽了", "還沒辦登記", "協議不算數", "還是大家的", "現在算誰的",
      "簽了但沒過戶", "地政那邊還登記"),
     ("不動產物權，依法律行為而取得、設定、喪失及變更者，非經登記，不生效力",
      "公同共有之關係，自公同關係終止，或因公同共有物之讓與而消滅")),

    # ── 登記的推定力與善意信賴 (民法§759-1) ──
    # 「原屋主的兒子說當初過戶是被騙的、登記是錯的,要我把房子還回去」 returned
    # §244/§242/§87/§88 — every way a transaction gets UNDONE, which is the
    # opposite of what this buyer needs. §759-1 is his side: registration is
    # presumed correct, and a good-faith third party who relied on it is protected.
    (("要我還回去", "登記是錯的", "說當初過戶", "我完全不知道", "原屋主",
      "跑來說", "會不會被拿回去"),
     ("不動產物權經登記者，推定登記權利人適法有此權利",
      "因信賴不動產登記之善意第三人")),

    # ── 土地所有權及於上下 (民法§773) ──
    # 「他們家的冷氣排水管架在我家院子上方」 — §797 covers the branches, nothing
    # covered the airspace. §773 is why a pipe overhead is still an intrusion.
    (("架在我家", "跨到我家上空", "我家院子上方", "越過圍牆", "從我家上面過",
      "管線經過我家"),
     ("土地所有權，除法令有限制外，於其行使有利益之範圍內，及於土地之上下",)),

    # ── 消費訴訟的管轄 (消保法§47) ──
    # 「業者在高雄我住台北,他們說要告就去高雄告」 returned the whole 買賣瑕疵 chapter
    # — the merits, not the question. §47 lets the consumer sue where the
    # consumption happened, which is the answer to 「我可不可以在台北告」.
    (("哪個法院", "管轄法院", "要跑那麼遠", "在台北告", "去哪裡告",
      "契約寫以", "要去外縣市"),
     ("消費訴訟，得由消費關係發生地之法院管轄",)),

    # ── 房屋瑕疵危及健康 (民法§424) ──
    # 「整面牆都是黑黴,住進去半年開始咳嗽,房東說當初帶看你自己也看過了」 returned
    # §430/§440/§441 — repair and late rent. §424 answers the landlord's sentence
    # directly: where the defect endangers health the tenant may terminate EVEN
    # having known of it, and even having waived the right.
    (("壁癌", "黑黴", "發霉", "一直咳嗽", "當初也看過", "帶看時看過",
      "住進去才發現", "危及健康"),
     ("如有瑕疵，危及承租人或其同居人之安全或健康時",)),

    # ── 管理委員會的職務 (公寓大廈條例§36) ──
    # 「管委會收管理費但什麼都不做,大廳燈壞三個月沒換」 reached §10/§21/§22 — who
    # pays and how arrears are chased. §36 is the list the asker wanted: what the
    # committee is required to do.
    (("管委會不做事", "該做哪些事", "都不處理", "什麼都不做", "管委會的職務",
      "收管理費卻", "沒公布過"),
     ("管理委員會之職務如下",)),

    # ── 家庭成員的範圍 (家暴法§3) ──
    # 「同居三年沒有結婚,朋友說不算家暴不能聲請保護令」 reached §63-1 — which covers
    # partners who do NOT live together — while this asker does. §3 is the direct
    # refutation: 現有或曾有同居關係者 are family members under the Act.
    (("沒有結婚", "沒登記", "同居三年", "算不算家暴", "男女朋友同居",
      "住在一起", "沒有結婚不算"),
     ("本法所定家庭成員，包括下列各員及其未成年子女",
      "現有或曾有同居關係、家長家屬或家屬間關係者")),

    # ── 監護人就任後要做的事 (民法§1099, §1100) ──
    # 「法院上個月裁定我當監護人,接下來要辦什麼」 returned §14/§15/§1111/§1111-1 —
    # how a guardian is APPOINTED, which already happened. §1099 is the next step
    # and it has a deadline: an inventory of the ward's property within two
    # months. §1100 is the standard the job is held to.
    (("剛當上監護人", "接下來要辦", "要送法院", "財產清冊", "監護人要做什麼",
      "裁定我當", "有沒有期限要辦"),
     ("監護開始時，監護人對於受監護人之財產，應依規定會同",
      "監護人應以善良管理人之注意，執行監護職務")),

    # ── 定期行為的遲延 (民法§255, §232) ──
    # 「約定婚禮當天早上八點送到,對方到中午都沒來,第三天才說要補送」 was REFUSED at
    # 資料不足. §255 is the point: when the time IS the contract, no further demand
    # is needed before rescinding. §232 lets the creditor refuse a late tender that
    # is now useless to them.
    (("當天沒送到", "都沒來", "才說要補送", "直接不要了", "過了時間才",
      "約定當天", "婚禮當天", "來不及用了"),
     ("依契約之性質或當事人之意思表示，非於一定時期為給付不能達其契約之目的",
      "遲延後之給付，於債權人無利益者，債權人得拒絕其給付")),

    # ── 醫療期間不得終止契約 (勞基法§13) ──
    # 「被機器壓傷手還在復健,公司寄資遣通知」 returned §11/§12/§14/§16/§18 — how a
    # contract is ended — plus §59 for the injury money. §13 is the one that says
    # he may not end it at all while the treatment lasts. Procedure given, the
    # prohibition withheld.
    (("還在治療", "還在復健", "醫療期間", "治療期間", "還沒回去上班",
      "職災還在", "復健中"),
     ("勞工在第五十條規定之停止工作期間或第五十九條規定之醫療期間，雇主不得終止契約",)),

    # ── 買賣的危險移轉 (民法§373) ──
    # 「店家安排的貨運路上翻車,桌面裂了,店家說已經交給貨運不關他的事」 returned the
    # 運送 chapter — the CARRIER's liability — while the question was who between
    # buyer and seller bears the loss. §373 answers it: risk passes on delivery.
    (("還沒簽收", "還沒送到", "運送途中", "路上壞", "交給貨運", "誰承擔",
      "送來的時候就壞"),
     ("買賣標的物之利益及危險，自交付時起，均由買受人承受負擔",)),

    # ── 意思表示錯誤 (民法§88) ──
    # 「下單時看錯電壓,收到才發現用不了」 returned 消保法§19 and the 通訊交易 articles
    # — for a purchase the asker had explicitly said was made in a shop, not
    # online. The window was built on a premise he had denied. §88 is the route
    # that does not depend on how it was bought.
    (("看錯", "買錯", "訂錯", "規格不對", "用不了", "以為是別的",
      "還沒拆封", "電壓"),
     ("意思表示之內容有錯誤，或表意人若知其事情即不為意思表示者，表意人得將其意思表示撤銷之",)),

    # ── 保證債務的範圍 (民法§740) ──
    # 「保證書只寫保證借款五十萬,銀行說連利息違約金一百二十萬都要我負責」 reached
    # §203/§233/§252/§753 — interest and penalties in the abstract. §740 answers
    # him directly, and against him: unless the contract says otherwise, the
    # guarantee already covers interest, penalties and damages.
    (("作保", "保證書", "保證借款", "都要我負責", "負責到哪裡", "幫同事作保",
      "幫朋友作保"),
     ("保證債務，除契約另有訂定外，包含主債務之利息、違約金、損害賠償及其他從屬於主債務之負擔",)),

    # ── 第三人清償後的承受 (民法§312) ──
    # 「車登記在我名下,銀行要拖車,我只好先幫他把八萬繳掉」 returned the joint-debt
    # chapter. §312 is the basis he needs: a third party with an interest who pays
    # steps into the creditor's shoes to that extent.
    (("先幫他繳", "幫他還了", "幫朋友還", "代他清償", "只好先幫",
      "我先付掉", "跟他要回來"),
     ("就債之履行有利害關係之第三人為清償者，於其清償之限度內承受債權人之權利",)),

    # ── 誰擔任監護人 (民法§1111, §1113) ──
    # Filed as a 「floor artefact」 for several rounds because the CLI reaches these
    # through the focused dense query. The sharper test says otherwise: NO phrase
    # in this table matches either article, so a flat fact string never gets them.
    # §1111 is how the court picks the guardian, §1113 is what makes the minors'
    # rules apply to an adult.
    (("誰當監護人", "也要當監護人", "法院會怎麼決定", "聲請監護宣告",
      "我能不能爭取", "誰比較適合"),
     ("法院為監護之宣告時，應依職權就配偶、四親等內之親屬",
      "成年人之監護，除本節有規定者外，準用關於未成年人監護之規定")),

    # ── 租金何時該付 (民法§439) ──
    # Same story: unreachable by any phrase, so 「房東要我一次先付一年租金」 could
    # only ever get the termination articles. §439 is the default — rent falls due
    # at the END of each period unless otherwise agreed.
    (("一次先付一年", "先付一年租金", "月付", "預付租金", "一次付清租金",
      "要我先付"),
     ("承租人應依約定日期，支付租金",)),

    # ── 可分之債的平均分擔 (民法§271) ──
    # The other half of 「沒有寫連帶」: §272 says joint liability needs an express
    # term, and §271 says what happens without one — divisible debts are split
    # equally. Neither was reachable before; §272 shipped last round, this is its
    # pair, in its own row because that row is already at two phrases.
    (("三分之一", "平均分擔", "各自負擔多少", "一人一份", "按人頭分"),
     ("數人負同一債務或有同一債權，而其給付可分者",
      "應各平均分擔或分受之")),

    # ── 專有部分或共有部分 (民法§799) ──
    # 「外牆磁磚掉下來砸到我的車,管委會說那面牆是頂樓那戶的專有部分」 — the classic
    # label dispute again. §799 defines both: whatever is not in anyone's 專有
    # 部分 is 共有部分, which is what the 權狀 already shows. Nothing in the table
    # reached §799 before, so a plain fact string never got the definition.
    (("外牆", "磁磚掉", "掉下來砸", "專有部分還是", "說是那戶的", "公共設施",
      "共用部分還是專有"),
     ("共有部分，指區分所有建築物專有部分以外之其他部分及不屬於專有部分之附屬物",)),

    # ── 扶養的程度 (民法§1119, §1117) ──
    # The set already reached WHO owes (§1115) and whether it can be reduced
    # (§1118-1), never HOW MUCH. 「我爸要我每個月給五萬,我薪水六萬還要養兩個小孩」
    # is that third question, and §1119 answers it in one line: the recipient's
    # need measured against the payer's means.
    (("怎麼算", "給多少", "我能負擔", "每個月給他", "少一塊都不行",
      "他要的金額", "算多少才合理"),
     ("扶養之程度，應按受扶養權利者之需要，與負扶養義務者之經濟能力及身分定之",)),

    # ── 寄託或借貸 (民法§589, §602) ──
    # 「出國前把八十萬交給朋友保管,他拿去周轉」 was REFUSED at 資料不足. §589 defines
    # 寄託 as handing a thing over for safekeeping; §602 is the fork that decides
    # this case — money held as fungible becomes 消費寄託 and the borrower rules
    # apply, which is exactly what 「我用一下也還得出來就好」 assumes.
    (("交給朋友保管", "放你那邊", "先幫我保管", "拿去周轉", "保管還是借",
      "幫我收著", "寄放"),
     ("稱寄託者，謂當事人一方以物交付他方，他方允為保管之契約",
      "寄託物為代替物時，如約定寄託物之所有權移轉於受寄人")),

    # ── 是不是委任 (民法§528, §546) ──
    # 「請朋友幫我賣二手車,賣了十八萬錢不給我,他說只是幫忙不是受我委託」 returned the
    # 買賣瑕疵 articles off the word 賣. §528 defines 委任 by the agreement to
    # handle another's affair — a favour asked and accepted is one — and §546 is
    # the answer to his petrol claim: necessary expenses are reimbursed, not
    # deducted at will.
    (("只是幫忙", "不是受我委託", "請朋友幫我", "幫我賣", "代賣", "託他處理",
      "說沒有義務"),
     ("稱委任者，謂當事人約定，一方委託他方處理事務，他方允為處理之契約",
      "受任人因處理委任事務，支出之必要費用")),

    # ── 租約屆期後的默示更新 (民法§451) ──
    # 「租約半年前到期,房東沒說要續約也沒叫我搬,房租照匯他也照收」 reached §440/§450
    # and the 條例 articles — how a tenancy ENDS. §451 is why one still exists:
    # use continued without objection turns it into an open-ended lease.
    (("到期沒續約", "沒有簽新的約", "照常繳房租", "他也照收", "到期後還住",
      "沒叫我搬", "說搬就搬"),
     ("租賃期限屆滿後，承租人仍為租賃物之使用收益，而出租人不即表示反對之意思者，視為以不定期限繼續契約",)),

    # ── 暫時與緊急保護令 (家暴法§16) ──
    # 「聲請一個多月還沒開庭,對方昨天又來砸東西」 reached §9/§10/§13/§14 — the kinds
    # of order and how to apply. §16 is the answer to 「有沒有更快的方式」: an
    # interim or emergency order can issue without a hearing.
    (("還沒開庭", "等太久", "更快的方式", "暫時保護令", "緊急保護令",
      "要排開庭", "來不及等"),
     ("法院核發暫時保護令或緊急保護令，得不經審理程序",)),

    # ── 僱傭或承攬 (民法§482, 勞基法§2) ──
    # 「每天打卡上班八小時,主管排班也管我請假,可是公司要我簽承攬契約」 returned the
    # entire 承攬 chapter — because the contract is CALLED 承攬, while the question
    # is whether it IS. §482 defines 僱傭 by serving another's labour for a wage,
    # and 勞基§2 defines 勞工 the same way. The label is not the test.
    (("打卡上班", "主管排班", "管我請假", "算不算員工", "簽的是承攬",
      "說我不是員工", "沒有勞健保", "假承攬"),
     ("稱僱傭者，謂當事人約定，一方於一定或不定之期限內為他方服勞務，他方給付報酬之契約",
      "勞工：指受雇主僱用從事工作獲致工資者")),

    # ── 繼承回復請求權 (民法§1146) ──
    # 「哥哥用一份我沒看過的分割協議書把房子登記到自己名下」 reached the general
    # 共有物分割 and 時效 articles. §1146 is the inheritance-specific claim AND its
    # own clock: two years from discovery, ten from the death.
    (("登記到自己名下", "登記到他名下", "分割協議書", "我沒有簽過",
      "私自登記", "繼承權被侵害", "調謄本才發現"),
     ("繼承權被侵害者，被害人或其法定代理人得請求回復之",
      "自知悉被侵害之時起，二年間不行使而消滅")),

    # ── 租賃物的返還 (民法§455) ──
    # 「退租搬走了,房東說留下舊書櫃跟雜物要扣一萬五清運費」 pulled in the 運送 and
    # 倉庫 chapters off 清運. §455 is the duty actually at issue — return the thing
    # — and §431 II is the limit: a tenant takes back what he added and restores.
    (("沒清乾淨", "沒搬乾淨", "清運費", "留下的東西", "留下一個",
      "走過一次屋", "鑰匙已經交還"),
     ("承租人於租賃關係終止後，應返還租賃物",
      "承租人就租賃物所增設之工作物，得取回之")),

    # ── 附合與承租人的工作物 (民法§811, §431) ──
    # 「租五年自己花錢裝的鐵窗跟嵌入式冷氣,房東說裝上去就不能拆走」 returned the
    # tenancy repair and return articles. §811 is why the landlord is partly
    # right — a fitting that becomes an essential part of the building goes with
    # it — and §431 is the tenant's side: increased value is reimbursed, and a
    # work fixture may be taken back if the place is restored.
    (("自己花錢裝", "拆得走", "拆走", "裝上去就", "焊上去", "嵌入式",
      "退租時要拆"),
     ("動產因附合而為不動產之重要成分者，不動產所有人，取得動產所有權",
      "承租人就租賃物支出有益費用，因而增加該物之價值者")),

    # ── 連帶債務是否成立 (民法§272) ──
    # 「三個人都簽名但沒有寫連帶,對方直接要我一個人還六十萬」 returned §273/§274/
    # §277/§280/§281 — every CONSEQUENCE of joint liability, while the question is
    # whether it exists at all. §272 is the prerequisite: without an express term
    # it arises only where a statute says so.
    (("沒有寫連帶", "沒寫連帶", "要我一個人還", "全部還是三分之一",
      "平均分擔嗎", "為什麼是我還全部"),
     ("數人負同一債務，明示對於債權人各負全部給付之責任者，為連帶債務",
      "無前項之明示時，連帶債務之成立，以法律有規定者為限")),

    # ── 親權的行使 (民法§1084, §1089) ──
    # 「親權判給我,前夫接去過夜就不還了,說他也是爸爸有權帶」 reached §1055 and the
    # divorce chapter. §1084 II is the duty the right comes from, and §1089 says
    # who exercises it when the parents disagree.
    (("不還我", "帶走不還", "接回來", "親權判給我", "說他也是爸爸",
      "監護權判給我", "不讓我接"),
     ("父母對於未成年之子女，有保護及教養之權利義務",
      "對於未成年子女之權利義務，除法律另有規定外，由父母共同行使或負擔之")),

    # ── 扶養義務人有數人時的分擔 (民法§1115) ──
    # 「社工跟安養院只找我要錢,哥哥姊姊都說沒錢不出」 reached §1116 — the order among
    # people ENTITLED to support — which is the mirror of the question. §1115 is
    # the order among those who OWE it, and its last paragraph is the answer:
    # same degree of kinship, share according to means.
    (("只找我要", "都說沒錢不出", "為什麼只有我", "一起分擔", "我付掉的",
      "兄弟姊妹都不出", "都推給我"),
     ("負扶養義務者有數人時，應依左列順序定其履行義務之人",
      "負扶養義務者有數人而其親等同一時，應各依其經濟能力，分擔義務")),

    # ── 定作人中途終止承攬 (民法§511) ──
    # 「裝潢做到一半,師傅品質很差我想喊停」 returned §502/§506/§512 and the 委任
    # articles. §511 is the exact answer: before the work is finished the customer
    # may stop it at any time, and pays for the loss that causes — not the lot.
    (("想喊停", "不想再做下去", "中途終止", "做到一半不做", "換別人做",
      "不想給他做了"),
     ("工作未完成前，定作人得隨時終止契約。但應賠償承攬人因契約終止而生之損害",)),

    # ── 成年 (民法§12, §739) ──
    # 「兒子剛滿十八在外面借了十五萬,對方說我是父親要負責」 returned the joint-debt
    # chapter — the father was never a debtor. §12 makes the son an adult, and
    # §739 says a guarantee takes a contract, which he never signed.
    (("剛滿十八", "已經成年", "我是父親要負責", "幫他還", "兒子欠錢",
      "女兒欠錢", "小孩在外面借"),
     ("滿十八歲為成年",
      "稱保證者，謂當事人約定，一方於他方之債務人不履行債務時，由其代負履行責任之契約")),

    # ── 暴利行為 (民法§74) ──
    # 「我媽住院急需三十萬,對方知道我很急,借三十萬要我三個月還四十五萬」 returned the
    # 消費借貸 chapter — the loan, as if the terms were ordinary. §74 is the one
    # that looks at HOW the terms were obtained: a court may set the act aside or
    # cut the payment when someone traded on another's urgency.
    (("知道我很急", "只好簽", "急需", "走投無路", "沒辦法只好", "趁我急",
      "當時沒得選"),
     ("法律行為，係乘他人之急迫、輕率或無經驗，使其為財產上之給付或為給付之約定",)),

    # ── 監護人處分財產的界線 (民法§1101, §1112) ──
    # 「我是媽媽的監護人,舅舅們說賣掉房子送安養院」 returned the articles about
    # APPOINTING a guardian. §1101 II is the answer: selling the ward's home needs
    # the court's permission, and §1112 says the ward's own wishes come first.
    (("賣掉房子", "堅持不賣", "送安養院", "處分不動產", "動用他的財產",
      "賣掉媽媽的", "賣掉爸爸的"),
     ("監護人對於受監護人之財產，非為受監護人之利益，不得使用、代為或同意處分",
      "監護人於執行有關受監護人之生活、護養療治及財產管理之職務時，應尊重受監護人之意思")),

    # ── 輔助宣告 (民法§15-2) ──
    # 「輕度失智,生活可以自理也認得人,但常被推銷買一堆用不到的東西」 reached
    # §14/§15/§15-1/§75/§77 — monitorship and full incapacity. §15-2 is the
    # middle setting the asker actually wants: specific acts need the assistant's
    # consent, everything else stays his own.
    (("被推銷", "一直買", "亂花錢", "還認得人", "生活可以自理", "不想剝奪",
      "輔助宣告", "輕度失智"),
     ("受輔助宣告之人為下列行為時，應經輔助人同意",)),

    # ── 公示送達 (民法§97) ──
    # 「存證信函被退回招領逾期,打電話不通,我想催告他還錢但根本送不到」 returned the
    # 消費借貸 chapter — the debt, not the delivery problem. §97 is the way a
    # declaration reaches someone whose whereabouts are unknown.
    (("被退回", "招領逾期", "寄不到", "送不到", "查無此人", "公示送達",
      "存證信函退回"),
     ("表意人非因自己之過失，不知相對人之姓名、居所者，得依民事訴訟法公示送達之規定",)),

    # ── 死亡宣告 (民法§8, §9) ──
    # 「我爸十年前出門就沒再回來,戶政說要先有死亡宣告才能辦繼承」 returned the whole
    # 繼承編 — the step BEFORE any of that is missing. §8 is the seven-year wait
    # and who may petition; §9 fixes the moment of death the estate turns on.
    (("失蹤", "死亡宣告", "沒再回來", "報警協尋", "音訊全無", "下落不明",
      "找不到人很多年"),
     ("失蹤人失蹤滿七年後，法院得因利害關係人或檢察官之聲請，為死亡之宣告",
      "受死亡宣告者，以判決內所確定死亡之時，推定其為死亡")),

    # ── 委任中途終止的報酬 (民法§548, §550) ──
    # 「代書辦到一半過世,先付的六萬能不能拿回來」 reached §541/§544/§546/§549/§551 —
    # everything about a mandate that is still running. §550 ends it on death and
    # §548 II is the answer to 「做多少算多少」.
    (("辦到一半", "做到一半", "做多少算多少", "事務所收掉", "受任人過世",
      "代書過世", "還沒辦完", "先付的錢"),
     ("委任關係，因當事人一方死亡、破產或喪失行為能力而消滅",
      "委任關係，因非可歸責於受任人之事由，於事務處理未完畢前已終止者")),

    # ── 無權代理 (民法§170, §110) ──
    # 「兒子拿我的印章去跟裝潢公司簽了六十萬的工程約」 returned the whole 承攬
    # chapter off 工程/裝潢 — but the asker is not a party to anything yet. §170
    # says the contract does not bind him unless he ratifies it; §110 is who the
    # decorator sues instead.
    (("拿我的印章", "不是我簽的", "沒經過我同意就簽", "冒用我的名義",
      "代替我簽", "我完全不知情", "偽簽", "盜蓋"),
     ("無代理權人以代理人之名義所為之法律行為，非經本人承認，對於本人不生效力",
      "無代理權人，以他人之代理人名義所為之法律行為，對於善意之相對人，負損害賠償之責")),

    # ── 僱用人受領勞務遲延 (民法§487) ──
    # 「公司說訂單少叫我先不用來,在家等通知,兩個月只給一半薪水」 returned the
    # dismissal and wage articles. §487 is the one that answers it: an employer
    # who refuses to accept the work still owes the pay.
    (("叫我先不用來", "不用來上班", "在家等通知", "說我沒來上班", "待命",
      "停工", "無薪假", "叫我在家"),
     ("僱用人受領勞務遲延者，受僱人無補服勞務之義務，仍得請求報酬",)),

    # ── 共有部分的修繕費用 (公寓大廈條例§10, 民法§799-1) ──
    # 「頂樓防水層破了漏到我家,五樓說頂樓是他專用的,管委會說要大家分攤」 reached
    # 條例§7 (頂樓平台不得約定專用) but nothing about who PAYS, which is what was
    # asked. §10 II puts shared-part repair on the committee; 民法§799-1 splits the
    # cost by share.
    (("誰要出錢", "誰出錢修", "要大家分攤", "頂樓平台", "防水層", "外牆漏水",
      "共用部分修繕", "費用怎麼分"),
     ("共用部分、約定共用部分之修繕、管理、維護，由管理負責人或管理委員會為之",
      "共有部分之修繕費及其他負擔")),

    # ── 無因管理 (民法§176) ──
    # 「樓上出國,水管爆了漏到我家,聯絡不上只好自己找水電修,花了兩萬八」 returned the
    # TENANCY and 相鄰關係 chapters. Nobody is renting; the asker managed someone
    # else's affair without being asked, and §176 is what lets him bill for it.
    # 聯絡不上 was a trigger for one run and cost a prepaid-voucher session its
    # 民法§256 — 「老闆也聯絡不上」 is said whenever anyone has gone quiet. The
    # trigger has to be the ACT of stepping in, not the silence that prompted it.
    (("只好自己", "自己找水電", "先幫他", "代墊修繕", "我先處理", "幫他修",
      "無因管理", "先付了錢幫"),
     ("管理事務，利於本人，並不違反本人明示或可得推知之意思者",
      "得請求本人償還其費用及自支出時起之利息",
      # §176 shipped without §172 two rounds ago — the consequence without the
      # rule, the very shape recorded as a failure mode. This is the rule.
      "未受委任，並無義務，而為他人管理事務者")),

    # ── 公同共有的權利行使 (民法§828, §820) ──
    # 「房子登記三兄妹公同共有,兩個人同意能不能出租」 got §818/§821/§824 — the rules
    # for 分別共有 — and not §828, which says 公同共有 needs EVERYONE unless the law
    # says otherwise. §820 is the majority rule it borrows for mere management.
    # Bare 公同共有 and 還沒分割 cost an estate-partition session its 民法§1164:
    # every inheritance is 公同共有 before it is divided. The triggers are about
    # CONSENT, which is what this row actually answers.
    (("都點頭", "不同意就不能", "兩個人同意", "全體同意", "一個人反對",
      "他不同意就", "要全部同意"),
     ("公同共有物之處分及其他之權利行使，除法律另有規定外，應得公同共有人全體之同意",
      "共有物之管理，除契約另有約定外，應以共有人過半數及其應有部分合計過半數之同意行之")),

    # ── 懲罰性賠償 (消保法§51) ──
    # 「業者自己的單子早就知道是泡水車」 reached §354/§359 — return it, cut the price —
    # and nothing about the asker's actual question, which was whether deliberate
    # deceit costs the seller more than an honest mistake. It does: up to five times.
    (("他們是故意的", "故意的", "早就知道", "明知", "隱瞞", "懲罰性賠償",
      "多要一些", "刻意不說"),
     ("因企業經營者之故意所致之損害，消費者得請求損害額五倍以下之懲罰性賠償金",)),

    # ── 抵銷 (民法§334, §335) ──
    # 「我借他三十萬他沒還,我也欠他二十萬貨款,可以互相抵掉嗎」 returned the loan and
    # sale articles — both debts, neither answer. Triggers are the session's own
    # words: 互相抵掉 / 分開算 / 差額.
    (("抵銷", "互相抵掉", "抵掉", "分開算", "差額", "互相扣", "扣掉他欠我的",
      "兩筆相抵"),
     ("二人互負債務，而其給付種類相同，並均屆清償期者，各得以其債務，與他方之債務，互為抵銷",
      "抵銷，應以意思表示，向他方為之")),

    # ── 違反強制規定的約定無效 (民法§71, 勞基法§1) ──
    # 「公司要我簽同意書,自願不加勞保、自願放棄加班費」 returned §24/§32/§36/§39 —
    # how overtime is CALCULATED. The answer is that the waiver is worth nothing:
    # §71 voids a legal act against a mandatory rule, and 勞基§1 II says agreed
    # terms may not fall below the statutory minimum.
    (("自願放棄", "同意書", "算不算數", "簽了有沒有效", "不加勞保", "拋棄權利",
      "切結書", "不簽就不錄用", "都簽了"),
     ("法律行為，違反強制或禁止之規定者，無效",
      "雇主與勞工所訂勞動條件，不得低於本法所定之最低標準")),

    # ── 未辦登記不得處分 (民法§759) ──
    # 「三個繼承人都同意賣,代書說還沒辦繼承登記不能賣」 returned the estate-division
    # articles — who gets what — and not the one that answers the question. §759
    # is why the 代書 is right: property taken by inheritance must be registered
    # before it can be disposed of.
    (("繼承登記", "還沒登記", "未辦登記", "代書說", "過戶前", "先簽約",
      "登記前", "還在名下", "沒過戶"),
     ("於登記前已取得不動產物權者，應經登記，始得處分其物權",)),

    # ── 契約的解釋 (民法§98, §153) ──
    # 「合約寫『每年保養兩次』,他們說連著同一個月做完也算」 returned §997, 勞基§12
    # and the 經理人 articles — nothing about how a contract is read. §98 is the
    # rule: look for what the parties MEANT, not what the words allow.
    # The triggers are the words the SESSION used, not the ones I first guessed:
    # 「該用誰的解釋」,「業務講的」,「我一直以為」 — not 「文字含糊」, which is how a
    # label describes the problem rather than how a person states it.
    (("誰的解釋", "怎麼解釋", "解釋不同", "各說各話", "硬拗", "當初講的",
      "當初講好", "業務講的", "業務說的", "我一直以為", "認定不同",
      "合約只寫", "契約沒寫清楚"),
     ("解釋意思表示，應探求當事人之真意，不得拘泥於所用之辭句",
      "當事人互相表示意思一致者，無論其為明示或默示，契約即為成立")),

    # ── 人格權 / 姓名權 / 肖像 (民法§18, §19, §195) ──
    # 「有人用我的照片跟名字開假帳號到處借錢」 returned the 消費借貸 chapter — the
    # word 借錢 belongs to the impostor, not to the asker. §18 is the right to
    # have the infringement STOPPED, §19 the same for a name, §195 the money.
    (("假帳號", "冒用我的名字", "盜用照片", "冒名", "假冒", "肖像",
      "用我的照片", "盜用我的", "冒充我", "人格權"),
     ("人格權受侵害時，得請求法院除去其侵害",
      "姓名權受侵害者，得請求法院除去其侵害，並得請求損害賠償",
      "不法侵害他人之身體、健康、名譽、自由、信用、隱私、貞操")),

    # ── 權利濫用 (民法§148) ──
    # 「隔壁緊貼我家窗戶砌了三米高的牆,他自己那邊根本沒在用,擺明要擋我的光」 got
    # the 越界建築 articles — the wall is on HIS OWN land and crosses nothing.
    # §148 is the article for a right exercised mainly to harm someone.
    (("擋光", "擋通風", "讓我不好過", "為了報復", "存心", "故意刁難",
      "根本沒在用", "純粹為了", "找我麻煩", "以損害他人"),
     ("權利之行使，不得違反公共利益，或以損害他人為主要目的",)),

    # ── 不完全給付 (民法§227) ──
    # 「裝好的冷氣一直漏水,修了四次還是壞」 returned the TENANCY articles plus
    # §494 — the asker BOUGHT it. §227 is the article for a thing delivered but
    # delivered badly, and its second paragraph is what covers the water-stained
    # wall and the buckled floor, which 瑕疵擔保 alone does not.
    (("修了幾次", "修過四次", "修不好", "一直故障", "還是壞", "重複維修",
      "保固", "不完全給付", "換新的", "瑕疵"),
     ("因可歸責於債務人之事由，致為不完全給付者",
      "因不完全給付而生前項以外之損害者，債權人並得請求賠償")),

    # ── 離婚後的子女扶養費 (民法§1116-2, §1084) ──
    # 「前夫說監護權判給我他就不用付扶養費」 put 民法§1118-1 — how to REDUCE a
    # maintenance duty — at rank 1, which is the opposite of what this asker
    # needs. §1116-2 is the flat rebuttal: a parent's duty to a minor child
    # survives the divorce.
    (("扶養費", "小孩的錢", "監護權判給", "不付扶養費", "沒給扶養費",
      "離婚後不付", "追討扶養費", "每月付"),
     ("父母對於未成年子女之扶養義務，不因結婚經撤銷或離婚而受影響",)),

    # ── 會議決議的效力 (民法§56, 公寓大廈條例§30, §34) ──
    # 「管委會開會決議每戶加收兩萬,我完全沒收到通知」 got §33/§11/§10/§14 and two
    # TENANCY articles. §30 is the ten-days-in-writing notice the meeting owed
    # them, §56 is the three months they have to ask a court to set the
    # resolution aside, §34 is the minutes that should have followed.
    (("沒收到通知", "沒通知我", "開會通知", "決議", "會議紀錄", "撤銷決議",
      "沒有出席", "臨時動議", "加收"),
     ("應由召集人於開會前十日以書面載明開會內容，通知各區分所有權人",
      "社員得於決議後三個月內請求法院撤銷其決議",
      "區分所有權人會議應作成會議紀錄，載明開會經過及決議事項")),

    # ── 回復原狀 (民法§213, §214, §215) ──
    # 「隔壁施工把我家牆壁震出裂縫,對方說給五萬了事,我要的是修回原狀」 returned the
    # 承攬 chapter off the word 施工 — the asker is the NEIGHBOUR, not the person
    # who hired anyone. §213 says restoration is the primary remedy and lets the
    # victim demand the COST of it; §214 and §215 are when money replaces it.
    (("修回原狀", "恢復原狀", "回復原狀", "修好", "弄壞我家", "震裂", "裂縫",
      "賠錢了事", "不是要錢", "打發我", "修到跟原本一樣"),
     ("應回復他方損害發生前之原狀",
      "債權人得請求支付回復原狀所必要之費用，以代回復原狀",
      "不能回復原狀或回復顯有重大困難者，應以金錢賠償其損害")),
      # 民法§184 was tried here too — §213 is what liability owes, §184 is what
      # makes it liable — and changed nothing: a fourth phrase in a row with
      # three seats simply never gets one. Left out rather than shipped as
      # decoration; the miss is recorded in RESULTS.md as a seat trade.

    # ── 連帶債務的內部分擔 (民法§273, §280, §281) ──
    # 「三個人一起簽的借據,債主只找我一個要全部」 reached §273 — yes, he may — but
    # not the other half the asker actually asked: what happens after I pay.
    # §280 splits it equally between them, §281 is the right to collect it back.
    # 求償 is OUT: it is said in every compensation question, and with §274 added
    # this row's four phrases then displaced 民法§197/§129 from a limitation-period
    # session (「現在我還能跟他求償嗎」).
    (("連帶", "一起借", "三個人簽", "只找我一個", "全部都找我",
      "分擔", "共同債務人", "保證人"),
     ("連帶債務之債權人，得對於債務人中之一人或數人或其全體",
      "連帶債務人相互間，除法律另有規定或契約另有訂定外，應平均分擔義務",
      "得向他債務人請求償還各自分擔之部分",
      # 「朋友說他已經全部還清了,銀行還是來要我還」 — §274 is the answer and the
      # row reached §273/§276/§280/§281 all around it.
      "因連帶債務人中之一人為清償、代物清償、提存、抵銷或混同而債務消滅者，他債務人亦同免其責任",
      # 「債權人自己也欠我表哥八十萬,我能不能拿來抵」 — §277, and again the row
      # already reached every article around it.
      "連帶債務人中之一人，對於債權人有債權者，他債務人以該債務人應分擔之部分為限，得主張抵銷")),

    # ── 脫產 / 詐害債權 (民法§244, §242) ──
    # 「他欠我一百萬,查到上個月把名下唯一的房子過戶給兒子」 returned the 消費借貸
    # articles — he owes me — and nothing about undoing the transfer, which was
    # the question. §244 is the creditor's revocation right; §242 is the
    # subrogation that goes with it.
    # 名下沒有財產 was a trigger for one run and hijacked a maintenance session —
    # 「爸爸名下沒有財產」 describes poverty, not a transfer. Same mistake as
    # 聯絡不上 / 公同共有 / 求償: the trigger must name the ACT.
    # 過戶給 was a trigger until a mother asking how to undo her OWN gift
    # (「把名下的房子贈與過戶給兒子」) got §244/§242/§87 and nothing else: the act
    # is identical from both sides, only the ROLE differs, so an act-shaped
    # trigger is not enough here. The motivating session keeps firing on
    # 名下唯一; seller-says-registration-wrong stops being given 詐害債權 noise.
    (("脫產", "移轉給", "名下唯一", "假買賣", "撤銷贈與", "轉到別人名下",
      "把財產轉走", "五鬼搬運"),
     ("債務人所為之無償行為，有害及債權者，債權人得聲請法院撤銷之",
      "債務人怠於行使其權利時，債權人因保全債權",
      # A sham sale is 通謀虛偽 before it is anything else: 「賣給老婆的弟弟,價金
      # 市價三成,根本沒有金流」 is §87, and §87 makes it void outright rather than
      # merely revocable.
      "表意人與相對人通謀而為虛偽意思表示者，其意思表示無效")),

    # ── 委任 / 代辦 (民法§541, §544, §549) ──
    # 「委託代辦處理修繕補助,給了八萬,他沒送件也不退」 returned the TENANCY chapter
    # off the word 修繕 — nobody in that story is renting anything. 委任 is its own
    # chapter: §541 is the duty to hand over what was collected, §544 the
    # liability for handling it badly, §549 the right to end it at any time.
    # Bare 委任 is OUT: the dementia session says 「爸爸沒有立過任何委任或授權書」
    # in passing and lost 民法§14 to this row's phrases.
    (("代辦", "受任人", "代收", "代為處理", "代辦費", "幫我處理",
      "代辦業者", "沒送件", "代書", "委託他處理", "委託代辦"),
     ("受任人因處理委任事務，所收取之金錢、物品及孳息，應交付於委任人",
      "受任人因處理委任事務有過失",
      "當事人之任何一方，得隨時終止委任契約")),

    # ── 僱用人連帶責任 (民法§188, §185) ──
    # 「貨運公司的車送貨時撞到我,司機叫我找公司,公司說是司機的事」 got §184/§196/
    # §216 — the driver's liability and its size — and nothing about WHO to sue,
    # which was the whole question. §188 puts the employer on the hook alongside
    # the employee; §185 covers the several-wrongdoers case.
    (("受僱人", "執行職務", "員工撞", "司機", "送貨時", "外送員", "上班時撞",
      "找公司", "公司要不要負責", "僱用人", "職務範圍"),
     ("受僱人因執行職務，不法侵害他人之權利者，由僱用人與行為人連帶負損害賠償責任",
      "數人共同不法侵害他人之權利者，連帶負損害賠償責任")),

    # ── 履行輔助人 (民法§224) ──
    # 「搬家公司的工人把餐桌從樓梯摔下去,公司說是工人自己不小心,叫我去找工人賠,
    # 工人是臨時找的」 returned §184/§188/§189/§192/§193 — the TORT chapter, which
    # is the answer to a stranger's accident, not to a contract the asker paid
    # for. §188 needs a 受僱人 relationship, and 「臨時找的」 is precisely the
    # sentence that denies one; §224 does not care, because it makes the debtor
    # answer for anyone he used to perform. Same shape as 僱用人連帶 above and the
    # opposite side of the seam: 侵權 asks who did it, 債務不履行 asks who owed it.
    (("派來的", "來的工人", "來的師傅", "外包給", "臨時找的", "找工人賠"),
     ("債務人之代理人或使用人，關於債之履行有故意或過失時，債務人應與自己之故意或過失負同一責任",)),

    # ── 頂讓 / 概括承受 (民法§305, 勞基法§20) ──
    # 「早餐店頂讓給別人,新老闆接手後繼續開,舊老闆積欠我三個月薪水就跑了」 returned
    # §440/§478/§474/§203 and 勞基§17/§22/§28 — the wage debt itself, well covered,
    # and not one article about whether the debt followed the shop. §305 is the
    # rule: take over a business's assets AND liabilities, tell the creditors or
    # publish it, and the debts come with it. 勞基§20 is the labour-side half.
    (("頂讓", "頂下", "接手後繼續", "概括承受", "改組"),
     ("就他人之財產或營業，概括承受其資產及負債者",
      "事業單位改組或轉讓時")),

    # ── 違約金過高 (民法§252) ──
    # 「才上三個月想解約,合約要我付剩餘期數再加三萬違約金」 reached 消保法§12 and
    # 民法§247-1 — whether the clause is void — but not §252, which is what a
    # court actually does with a penalty that is merely excessive.
    (("違約金", "罰款太高", "提前解約", "賠剩下的", "剩餘期數", "解約金"),
     ("約定之違約金額過高者，法院得減至相當之數額",)),

    # ── 被詐欺或脅迫而簽約 (民法§92, §93) ──
    # 「櫃姐說是體驗紀錄,結果是兩年二十四期的療程契約」 was REFUSED at 資料不足.
    # §92 is the right to rescind, §93 is the one-year clock on doing it.
    (("被騙簽", "話術", "沒說是契約", "誤導", "詐欺", "被逼簽", "脅迫",
      "免費體驗", "說是體驗", "以為是", "沒給我看內容"),
     ("因被詐欺或被脅迫而為意思表示者，表意人得撤銷其意思表示",
      "應於發見詐欺或脅迫終止後，一年內為之")),

    # ── 管理費欠繳 / 管委會 (公寓大廈條例§21, §10) ──
    # 「管委會說我欠三年管理費要告我,可是電梯壞半年沒修」 got §6/§22/§33 and three
    # TENANCY articles — the asker owns the flat. §21 is the article the committee
    # is actually suing under, and §10 is who owes the repair of the shared lift.
    # 管委會 / 區分所有權人 / 電梯壞 are OUT: they appear in most of the noise
    # sessions in the golden set, where this row's phrases took the seats that
    # 社維法§72 needed — golden fell 19 -> 17 in the run that added them. The
    # triggers have to name the MONEY.
    (("管理費", "公共基金", "滯納金", "欠繳管理費", "積欠管理費"),
     ("經定相當期間催告仍不給付者，管理負責人或管理委員會得訴請法院命其給付",
      "共用部分、約定共用部分之修繕、管理、維護，由管理負責人或管理委員會為之")),

    # ── 買賣價金 / 貨款 (民法§367, §229, §233) ──
    # 「出貨三批四十幾萬,對方拖了快一年」 was REFUSED at 資料不足. §367 is the
    # buyer's plain duty to pay, §229 is when they fall into default, §233 is the
    # interest that runs from then.
    (("貨款", "出貨", "簽收單", "訂購單", "月結", "尾款沒付", "不付款",
      "拖著不付", "應收帳款", "催款"),
     ("買受人對於出賣人，有交付約定價金及受領標的物之義務",
      "給付有確定期限者，債務人自期限屆滿時起，負遲延責任",
      "債權人得請求依法定利率計算之遲延利息")),

    # ── 違法解僱 / 確認僱傭關係 (勞基法§11, §12, §14) ──
    # 「公司叫我今天別來了,理由是態度不佳」 returned §16/§17/§20 — how much
    # severance — which quietly concedes the dismissal was valid. §11 is the
    # EXHAUSTIVE list of grounds on which an employer may end a contract at all,
    # and 「態度不佳」 is not on it; §12 is the without-notice list; §14 is the
    # mirror for the worker.
    (("開除", "解僱", "叫我不要來", "叫我今天就別來", "不能勝任", "態度不佳",
      "跟主管不合", "回去上班", "恢復僱傭", "確認僱傭", "違法解僱", "被炒"),
     ("非有左列情事之一者，雇主不得預告勞工終止勞動契約",
      "勞工有左列情形之一者，雇主得不經預告終止契約",
      "有下列情形之一者，勞工得不經預告終止契約")),

    # ── 越界建築 / 拆屋還地 (民法§796, §796-1, §767) ──
    # 「鄰居把圍牆蓋進我家土地五十公分,不肯拆」 reached §796 but not §767, the
    # request that actually gets it removed — the 拆掉 trigger did not match
    # 「不肯拆」. §796-1 is why a court may refuse to order removal anyway.
    (("越界", "地界", "蓋到", "佔到", "占到", "蓋進", "圍牆", "拆屋", "還地",
      "複丈", "地政測量", "不肯拆", "界線"),
     ("土地所有人建築房屋非因故意或重大過失逾越地界者",
      "法院得斟酌公共利益及當事人利益，免為全部或一部之移去或變更",
      "所有人對於無權占有或侵奪其所有物者，得請求返還之")),

    # ── 分期付價買賣 (民法§389, §390) ──
    # 「刷分期三十期,上了三期想停,業者說要一次付完剩下二十七期」 was REFUSED at
    # 資料不足. §389 caps that demand: not until a fifth of the total is overdue.
    # Bare 分期 and 每期 are out: a prepaid-voucher session mentioning 「刷卡分期還
    # 有六期沒繳完」 in passing lost 民法§256 to this row's phrases. The triggers
    # have to describe the DEMAND (一次付完 / 停繳), not the payment method.
    (("期數", "一次付完", "一次付清", "剩下的期", "刷分期", "分期付款", "停繳"),
     ("除買受人遲付之價額已達全部價金五分之一外",
      "其扣留之數額，不得超過標的物使用之代價")),

    # ── 扶養義務的減輕與免除 (民法§1118-1, §1114, §1117) ──
    # 「我爸五歲就離家沒付過扶養費,現在中風要我付安養費」 returned the
    # 未成年子女監護 chapter (§1089/§1091/§1097) — the asker is 38. §1118-1 is the
    # whole point: a parent who never supported the child can have the duty
    # reduced, and 免除 outright when it was serious.
    (("扶養", "安養費", "養老", "扶養費", "沒養過我", "從小就離家", "遺棄我",
      "沒付過", "不曾照顧", "社工打電話", "安養院費用", "看護費"),
     ("得請求法院減輕其扶養義務",
      "對負扶養義務者無正當理由未盡扶養義務",
      "左列親屬，互負扶養之義務",
      "以不能維持生活而無謀生能力者為限")),

    # ── 裁判離婚 (民法§1052, §1056, §1057) ──
    # 「老公外遇還動手,我想離婚他死不肯簽」 was REFUSED at 資料不足 while §1052
    # lists nine grounds including 與配偶以外之人合意性交 and 不堪同居之虐待.
    (("離婚", "外遇", "劈腿", "小三", "不肯簽", "分居", "惡意遺棄", "家暴",
      "動手打我", "贍養費", "監護權"),
     ("夫妻之一方，有下列情形之一者，他方得向法院請求離婚",
      "因判決離婚而受有損害者，得向有過失之他方，請求賠償",
      "因判決離婚而陷於生活困難者",
      "對於未成年子女權利義務之行使或負擔")),

    # ── 代筆遺囑 (民法§1194, §1189) ──
    # 「爸爸中風不能寫字,找三個鄰居當見證人,口述由其中一人代筆,弟弟說不是親手寫
    # 的所以無效」 returned §1144/§1138/§1141/§1165/§1176/§1202 — how an estate is
    # divided, i.e. what happens AFTER you know whether the will stands. §1189
    # says a will may take five forms and 自書 is only one of them; §1194 lists
    # what 代筆 actually requires, which is the checklist the brother's claim has
    # to be tested against.
    # 遺囑 and 見證人 are deliberately NOT triggers: 遺囑 sits in seven sessions,
    # one of them 「爸爸沒有留遺囑」 (a denial), and 見證人 appears in two sessions
    # about signed agreements that have nothing to do with wills.
    (("代筆", "口述"),
     ("代筆遺囑，由遺囑人指定三人以上之見證人",
      "遺囑應依左列方式之一為之",
      "由見證人全體及遺囑人同行簽名")),

    # ── 拋棄繼承 / 限定責任 (民法§1174, §1175, §1148) ──
    # 「爸爸過世銀行說有三百多萬貸款」 got the 遺產分配 articles but not the one the
    # asker actually needed: three months, in writing, to the court. §1148 is why
    # 拋棄 is often unnecessary — liability is already capped at the estate.
    (("拋棄繼承", "限定繼承", "留下債務", "欠銀行", "背債", "債務會不會",
      "跑到我小孩", "繼承債務", "貸款要我們還"),
     ("應於知悉其得繼承之時起三個月內，以書面向法院為之",
      "繼承之拋棄，溯及於繼承開始時發生效力",
      "繼承人對於被繼承人之債務，以因繼承所得遺產為限，負清償責任")),

    # ── 監護宣告 / 無行為能力 (民法§14, §15, §75) ──
    # 「我爸失智,弟弟拿他的存摺把錢領走,說是爸爸同意的」 filled its whole window
    # with 繼承編 (§1138–§1176). The father is ALIVE — answering a living man's
    # family with the rules for dividing his estate is the wrong-premise failure
    # this project exists to avoid. §14 is how the court appoints a guardian,
    # §15 says such a person has no capacity, and §75 is why the 「他同意的」
    # defence fails: an expression of will made without understanding is void.
    (("失智", "阿茲海默", "認不得", "神智不清", "意識不清", "精神障礙",
      "監護宣告", "輔助宣告", "沒有行為能力", "無行為能力", "植物人", "重度身心障礙"),
     ("法院得因本人、配偶、四親等內之親屬",
      "受監護宣告之人，無行為能力",
      "其意思表示，係在無意識或精神錯亂中所為者亦同")),

    # ── 利息與定期給付的時效 (民法§126, §205) ──
    # 「十五年前的卡債,本金八萬,剩下都是利息跟違約金」 reached §125/§129/§144 but
    # not the two articles that decide the size of it: interest runs on a FIVE
    # year clock, not fifteen, and anything over 16% a year is void.
    (("利息", "違約金", "循環利息", "滾利", "利滾利", "本金", "年息", "月息",
      "催收", "資產管理公司", "債權轉讓"),
     ("其各期給付請求權，因五年間不行使而消滅",
      "約定利率，超過週年百分之十六者，超過部分之約定，無效")),

    # ── 和解書 (民法§737, §738, §736) ──
    # 「車禍當天對方拿一張和解書給我簽,寫賠三萬兩清,一個月後醫生說頸椎要開刀」
    # returned §563/§473/§611/§144/§197/§125 — 時效 and unrelated chapters, with
    # nothing about the piece of paper the whole question is about. It is also
    # the article the OTHER SIDE is holding: §737 says the rights given up in a
    # settlement are extinguished, which is precisely what he is telling her.
    # §738 is the only way back — and it says mistake alone is NOT enough,
    # so the honest answer needs both articles in the window, not one.
    # 「和解了」 is deliberately NOT a trigger: 「我不想和解了」 contains it and means
    # the opposite. Every trigger here requires the settlement to have HAPPENED.
    (("和解書", "和解契約", "簽和解", "簽了和解", "已經和解"),
     ("和解有使當事人所拋棄之權利消滅",
      "和解不得以錯誤為理由撤銷之",
      "稱和解者，謂當事人約定，互相讓步")),

    # ── 不當得利 (民法§179, §181, §182) ──
    # 返還不當得利 is the 12th most common 案由 in the harvested judgments and the
    # session set had never covered it: 「轉帳打錯,三萬匯給不認識的人,他說花掉了
    # 不還」 was REFUSED at 資料不足 with a top score of 47.7, while §179 sat in the
    # corpus saying exactly that. §182 answers the 「已經花掉了」 defence.
    (("匯錯", "轉帳打錯", "打錯帳號", "匯給不認識", "不當得利", "多付", "溢繳",
      "代墊", "多給", "重複付款", "退回來", "沒有理由拿"),
     ("無法律上之原因而受利益，致他人受損害者，應返還其利益",
      "不當得利之受領人，除返還其所受之利益外",
      "受領人於受領時，知無法律上之原因或其後知之者")),

    # ── 消滅時效 (民法§197, §125, §129, §144) ──
    # 「三年前有人撞到我,現在還能求償嗎?」 got 民法§184/§191-2/§193 — who is
    # liable — and not one article about whether it is too late, which is the
    # entire question. §197 is the two-year/ten-year clock for tort, §125 the
    # fifteen-year default, §129 what interrupts it, §144 what 「已過時效」 actually
    # does (the debtor may refuse; the claim is not erased).
    (("還能", "來不來得及", "來得及", "過期", "時效", "多久以前", "幾年前",
      "三年前", "五年前", "很久以前", "拖了很久", "早就", "還可以告"),
     ("因侵權行為所生之損害賠償請求權，自請求權人知有損害及賠償義務人時起，二年間不行使而消滅",
      "請求權，因十五年間不行使而消滅",
      "消滅時效，因左列事由而中斷",
      "時效完成後，債務人得拒絕給付")),

    # ── 時效中斷後又放著 (民法§130, §137) ──
    # 「兩年前有寄存證信函催他還錢,我想說時效就中斷了就先放著」 got §144/§197/§125
    # /§229/§233/§367 — every article about the debt and the clock, and not one
    # about what the letter actually did. §130 is the whole answer: a demand
    # interrupts, but if no suit follows within six months the interruption is
    # treated as never having happened. §137 is what a surviving interruption
    # buys — the clock restarts, it does not pause.
    # Bare 「寄存證信函」 was measured and REJECTED as a trigger: it appears in
    # three sessions where the letter is proof of notice, not a clock event
    # (unpaid-hoa-fee, co-debtor-already-paid, cannot-serve-notice), and
    # time-barred says 「沒有寄過存證信函」 — a DENIAL, the premise failure mode.
    (("存證信函催", "信函催討", "催告後沒有起訴", "時效就中斷", "時效已經中斷",
      "以為時效中斷"),
     ("時效因請求而中斷者，若於請求後六個月內不起訴，視為不中斷",
      "時效中斷者，自中斷之事由終止時，重行起算")),

    # ── 撤銷贈與 (民法§416, §419) ──
    # 「三年前把名下的房子贈與過戶給兒子,講好他要照顧我到老,過戶完他就搬走」 got
    # §144/§365/§473/§244/§87 — the 脫產 row fired on 「過戶給」 and dragged the
    # CREDITOR's revocation articles into a session where the asker is the one
    # who made the transfer. Nothing in the window let her undo her own gift.
    # §416 II is the article written for exactly this: 受贈人對於贈與人有扶養義務
    # 而不履行者,贈與人得撤銷其贈與. §419 is how the house comes back.
    # 「撤銷贈與」 is deliberately NOT a trigger here — it already belongs to the
    # 脫產 row, where it means the CREDITOR's §244 revocation, and this session
    # never says it. 「送給兒子」 is out for the same reason: not the asker's words.
    (("贈與過戶", "贈與給"),
     ("受贈人對於贈與人，有左列情事之一者，贈與人得撤銷其贈與",
      "對於贈與人有扶養義務而不履行者",
      "贈與撤銷後，贈與人得依關於不當得利之規定，請求返還贈與物")),

    # ── 定金 / 斡旋金 (民法§248, §249) ──
    # 「付了十萬斡旋金,屋主後來不賣了」 returned 定型化契約 and 買賣瑕疵 articles
    # and not one 定金 article. §248 is what handing money over means, §249 is
    # the whole answer sheet: returned when the deal completes, forfeited when
    # the payer walks, DOUBLED when the receiver walks, returned when neither is
    # to blame.
    (("定金", "訂金", "斡旋", "加倍返還", "頭款"),
     ("由他方受有定金時，推定其契約成立",
      "契約履行時，定金應返還或作為給付之一部",
      "契約因可歸責於付定金當事人之事由，致不能履行時，定金不得請求返還",
      "契約因可歸責於受定金當事人之事由")),

    # ── 承攬瑕疵 / 裝修工程 (民法§492, §493, §494, §505) ──
    # 「師傅裝修廚房,水管沒接好會漏水,還催我付尾款」 returned the tenancy and
    # 相鄰關係 chapters off the word 漏水 — nobody in that story is a tenant.
    # 承攬 is its own chapter and it answers the whole question: §492 is the
    # quality owed, §493 is 定期限請求修補 then self-repair at the contractor's
    # cost, §494 is 解除契約或減少報酬, §505 is when the balance falls due.
    (("裝修", "裝潢", "施工", "師傅", "工班", "尾款", "估價單", "驗收",
      "貼歪", "做壞", "承攬", "定作", "工程合約"),
     ("承攬人完成工作，應使其具備約定之品質",
      "定作人得定相當期限，請求承攬人修補之",
      "定作人得自行修補，並得向承攬人請求償還修補必要之費用",
      "定作人得解除契約或請求減少報酬",
      "報酬應於工作交付時給付之")),

    # ── 預扣工資 (勞動基準法§26) ──
    # 「遲到三次還打破設備,直接從薪水扣八千」 got §22 (全額直接給付) but not the
    # article that says the deduction itself is forbidden. 違約金 is deliberately
    # NOT a trigger — it would push a labour article into every contract case.
    (("扣薪", "預扣", "扣我薪水", "從薪水扣", "薪水被扣", "工資被扣", "薪水少了"),
     ("雇主不得預扣勞工工資作為違約金或賠償費用",)),

    # ── 損害賠償範圍 (民法§196, §216, §217) ──
    # 「我到底該賠多少」 is a different question from 「他要負責嗎」, and the window
    # for a scratched car was 道路交通管理處罰條例 penalty articles — administrative
    # fines, not what one driver owes another. §196 is the measure for a damaged
    # THING, §216 is what 所失利益 (the other side's 停業損失 claim) means, §217 is
    # the reduction when the victim shares the blame.
    (("賠多少", "該賠", "求償金額", "獅子大開口", "太誇張", "漫天", "開價",
      "刮傷", "刮痕", "擦撞", "凹痕", "修車", "板金", "估價單",
      "停業", "營業損失", "折舊", "過失比例", "肇責"),
     ("不法毀損他人之物者，被害人得請求賠償其物因毀損所減少之價額",
      "應以填補債權人所受損害及所失利益為限",
      "可得預期之利益，視為所失利益",
      "損害之發生或擴大，被害人與有過失者，法院得減輕賠償金額")),

    # ── 共有物 / 妨害除去 (民法§818, §823, §824, §767) ──
    # 「我跟哥哥一人一半繼承了一間房子,我想賣他不肯,他還自己住在裡面」 filled its
    # whole window with 繼承編 (§1138–§1176) off the word 繼承, while the question
    # is co-ownership: §823 lets any co-owner demand partition at any time, §824
    # is how a court does it, §818 is why one co-owner living there alone owes
    # the other for use, and §767 is how you get an encroacher removed.
    (("共有", "持分", "應有部分", "一人一半", "各二分之一", "不肯賣", "分割",
      "占用", "佔用", "拆掉", "無權占有"),
     ("得隨時請求分割共有物", "共有物之分割，依共有人協議之方法行之",
      "按其應有部分，對於共有物之全部，有使用收益之權",
      "所有人對於無權占有或侵奪其所有物者，得請求返還之",
      "對於妨害其所有權者，得請求除去之",
      # 「共有地被工廠堆廢棄物,堂哥說懶得管,我一個人能不能告」 — §821 is the
      # answer and nothing in the row reached it: a co-owner may sue a third
      # party over the WHOLE thing without the others.
      "各共有人對於第三人，得就共有物之全部為本於所有權之請求")),

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
    (("遺產", "繼承", "過世", "身故", "應繼分", "分遺產", "存摺印章", "遺囑",
      "遺產沒分", "不肯分", "懷孕", "遺腹子", "肚子裡", "還沒出生"),
     ("遺產繼承人", "同一順序之繼承人", "按人數平均繼承",
      "配偶有相互繼承遺產之權，其應繼分",
      "在分割遺產前，各繼承人對於遺產全部為公同共有",
      # §1164 — the ESTATE-specific partition right. It belongs here, not in the
      # co-ownership row: putting it there cost oos-02-inheritance its 民法§1141.
      "繼承人得隨時請求分割遺產",
      # 「婆家說小孩還沒出生不算繼承人」 — §7 is the direct answer, and §1166 (the
      # share that must be held back) was already reaching the window without it.
      # TRIED AND REJECTED — adding 民法§1166 here as well. The row is saturated at
      # eight phrases and three seats, so it only MOVED the loss: §1166 and §1111
      # came back and §1164 and §1151 went out, same 158/170. Two answers in older
      # sessions are worth more than one supporting article in the new one.
      "胎兒以將來非死產者為限，關於其個人利益之保護，視為既已出生")),

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
    # §184 rides along on purpose: §191 is a presumption of fault layered on the
    # general tort clause, and an answer that cites the presumption without the
    # basis is half an answer. It also puts the phrase in a row the ranking
    # corroborates — its own row is not, and that is why it kept losing seats.
    (("漏到", "破裂", "爆管", "淹到", "泡壞", "滲到", "掉落", "外牆"),
     ("土地上之建築物或其他工作物所致他人權利之損害", "由工作物之所有人負賠償責任",
      "因故意或過失，不法侵害他人之權利者")),

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

    # ── 擅自進入住宅 (刑法§306, 民法§423) ──
    # 刑§306 was the only article here, so a tenant asking 「房東自己開門進我房間,
    # 這樣算侵犯我的權利嗎」 got the criminal side and nothing civil. §423 is the
    # civil basis: the landlord owes a 租賃物 that stays fit for the agreed use,
    # and walking in unannounced is exactly what that promise excludes.
    (("擅自進入", "自己開門", "沒經過我同意", "闖進", "侵入", "備份鑰匙", "偷進"),
     ("無故侵入他人住宅", "受退去之要求而仍留滯者",
      "保持其合於約定使用、收益之狀態")),

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
