# Measurement history — how each number was arrived at

The chronological log behind [`RESULTS.md`](RESULTS.md), kept because the
mistakes are the useful part: three defect classes that started at 0%, a data
bug the exam found before a human did, an honesty gate that was dead for a week,
and every change that was measured and then NOT shipped. Current numbers live in
RESULTS.md; this file is the story of getting them.

Three parts: the 社區治理 vocabulary round (2026-08-14); the
honest-limits changelog moved out of RESULTS.md (entries through 2026-08-15);
and Archive A, the original 2026-07 results file, whose sections are numbered
§A0–§A7 so they cannot be confused with RESULTS.md's §1–§9.

---

## 社區治理語彙 (2026-08-14) — 7/27 → 19/27 on labels nobody here wrote

`evaluation/realworld.py` had just reported its first number: on 16 臺中市
公寓大廈爭議調處案, labelled by the article the committee itself printed in its
法令依據 column, the governing article reached the window **7/27**, and **9 of 16**
cases were answered with none of them and no refusal. The split in the misses was
the whole diagnosis: every physical dispute hit (漏水 §10/§12, 外牆 §10, 拒絕受檢
§6) and every governance dispute missed (規約, 決議效力, 委員選任, 管理費計算,
共用部分特別約定). The 口語→法條 table had been grown from noise, rental, labour
and consumer sessions and contained no 區分所有權人會議 vocabulary at all.

Eight new rows, statutory side copied verbatim from the articles. Result:
**19/27 (70%), silent misses 9/16 → 1/16.**

**The four narrowings are the part worth keeping.** The first draft moved the
external number to 19/27 immediately and quietly cost three hits on
`real_recall`. Each cause was a trigger naming the *counterparty* instead of the
dispute — the same mistake the table's own comment about bare 賠 warns against:

| trigger | what it did | fix |
|---|---|---|
| `管委會` / `管理委員` | fired in **9 of the 168 lived sessions**, in all 9 as the counterparty of a leak/noise complaint; cost 公寓大廈§10 a stairwell-leak case | dropped; an election dispute names the election (遴選/連任/留任/改選) |
| bare `決議` / `表決` | pulled §31 into a 社團總會 session, pushing out 民法§56 | dropped — and the row was also **incomplete**, so 民法§56's own wording now rides in it beside §31: challenging a meeting needs the quorum rule *and* the article that voids the decision |
| `佔用` | displaced 民法§821 in a co-owned-land session | dropped; 共有物 ≠ 共用部分 |
| bare `不配合` | displaced 民法§821 (「對方不配合」) | narrowed to 不願意配合 / 拒絕配合 / 拒絕進入 / 不讓進 / 不給檢查 / 不讓修 |

After the narrowings every published figure is untouched: `real_recall`
**348/356** with a per-case diff against the pre-change table showing **zero lost,
zero gained** (3× in-process, once from a clean process); BM25-only **320/356**
before and after, twice each; golden_v2 **pass 19 / partial 7 / miss 0, 73%
strict, tier 29/32, premise 32/32**. 480 tests.

**Measurement trap logged.** An intermediate reading of 345/356 was nearly
attributed to run-to-run dense noise. It was not noise — it was the broad
`管委會` trigger, and a six-session diff found it in seconds once the comparison
was restricted to the sessions the new rows could actually touch. Cheap
attribution first; blame variance last.

**Second pass, same day — 19/27 → 25/27, silent misses 1/16 → 0/16.** Ranking the
eight stragglers first decided the method: dense ranks were 10–48, none inside the
top-3 the reserved seats can promote (N=3, swept 2026-07-21, N≥4 costs a golden
case), so vocabulary was the only lever left. Four targeted additions:

- §23's 「非經載明於規約者，不生效力」 and §10's 管理 clause into the 共用部分 row —
  apt-13 said 停車格/永久使用 and never said 規約; apt-01's committee was exercising
  the 管理 power, not repairing anything, so the fee row's cost clause never reached it.
- 分擔一半 / 各分擔 / 要我分擔 as triggers, plus §36's 「共有及共用部分之清潔、維護、
  修繕及一般改良」, into the fee row (apt-05, billed half a shared-part repair).
- A new 樓地板 / 共同壁 / 龜裂 / 滲水 / 壁癌 row carrying §12 verbatim (apt-16).
  漏水 deliberately excluded — the most common word in these sessions, and it
  already reaches §10/§12 on its own lexical merit.

**A fix that broke a neighbour, and a wrong theory recorded as wrong.** Widening
the 共用部分 row knocked §57 out of the handover case (apt-06): a hit became the
run's only silent miss. First hypothesis — expansion order, since both rows matched
a 4-character trigger and ties break by table position — was tested by moving the
handover row first. **It changed nothing.** The real cause was the trigger itself:
`公共設施` is also how a committee describes what the DEVELOPER still owes it, so a
handover complaint was being handed shared-space clauses. Removing `公共設施` from
that row (apt-13 still fires on 停車格/永久使用) restored §57: **25/27, 0 silent
misses**, and the reordering was reverted rather than left in place with a comment
claiming a fix it never made.

Regression check after the second pass: `real_recall` **348/356**, golden_v2 **pass
19 / partial 7 / miss 0, 73% strict, tier 29/32, premise 32/32**, 480 tests, ruff
clean — all identical.

**Still missed, 2 of 27, and one of them on purpose.** §48 (apt-03) is the penalty
schedule; a lay description of a dispute never resembles a list of fines and no
honest trigger points at it. §10 (apt-12) is a window-budget problem, not a
vocabulary one — that case carries three governing articles and `DEFAULT_K` is 8
seats shared with everything else the query pulls; two of three surface. Widening k
would buy it and is refused, for the reason `real_recall` prints every run: the
window already delivers 5.9 unexpected articles per session and the reader pays
that cost.

---

## Honest-limits changelog, through 2026-08-15

Moved verbatim from the "Honest limits" section of [`RESULTS.md`](RESULTS.md)
on 2026-10-16, when that file was restructured for a first-time reader. RESULTS
keeps the standing limits and a short provenance note for every published row
(its §6.1); the entries themselves, with every measurement in them, are here.
Four things to know while reading them:

- **"This file", "above" and "below" mean RESULTS.md as it stood when the entry
  was written.** "§7" and "§8" mean the RESULTS.md sections that still carry
  those numbers (disputes that already ended; the seat the user is sitting in),
  not this file's archive sections, which are numbered §A0–§A7. A § followed by
  an article number (租賃住宅條例§7) is a statute, as everywhere else.
- **"2,922 articles" was a row count.** It excluded the police routing note and
  included the one historical version (違反社會秩序維護法案件處理辦法§11's
  repealed slice). Articles in force: 2,921. Only one figure below was corrected
  in place — the corpus-import entry's statute count, which had counted the
  routing note as a statute.
- **Numbers are as measured at the time.** Several were later superseded inside
  this same list (81% strict, k=12, 10,437/10,437, 「10–30%」); the current
  figure for anything is RESULTS.md §1.
- **Order is the order they stood in RESULTS.md.** The earliest entries are
  undated.

- **Administrative-fine articles are the next precision leak, unshipped.**
  「令其限期改正…屆期不改正者,處新臺幣三萬元以上三十萬元以下罰鍰」 articles
  (條例§38-1, 消保法§56-1, and the whole of 道路交通管理處罰條例) are long, full
  of common words and money amounts, and answer a question nobody asked. A
  filter is easy to write and impossible to justify: the same shape shipped one
  round earlier moved no published number either. Measuring precision comes
  first — 社維法§72 is also a 罰鍰 article and is the flagship noise answer, so
  the filter cannot be 「drop 罰鍰」.
- **100% on real-session recall means「no known defect left」, not「solved」.**
  Every case was added the round its own defect was found, so the set is a record
  of what has already been fixed. It hit 100% once from cases I invented, and the
  very next batch — 案由 sampled from the judgments table instead — broke it
  three times in a row (賠多少, 不當得利, 離婚). Scenarios now come from the
  docket for exactly that reason, and the next wrong answer is still in a session
  nobody has run yet.
- **Three reserved seats is now the binding constraint, and the misses are all
  the same shape.** 民法§478 loses to §244/§242 (a session about a TRANSFER),
  §184 loses to the §213 restitution phrases (a wall to be repaired), and
  §354/§359 lose to 消保法§12/§247-1 (a defective air conditioner, where BM25 put
  消保法§11-1 second and made the 定型化契約 row corroborated). Each ordering is
  defensible for its own question; what they share is that four good pointers
  cannot fit in three seats. Widening was measured twice — once on 22 sessions,
  again on 47 — and lost both times: 4 seats identical (111/113, 19/7/0), 5 seats
  worse (107/113, 18/8/0). The expectations were written before each run and
  relabelling them afterwards would be grading my own work, so the number carries
  the misses.
- **A reserved seat could evict a right answer, and did.** An injury-dismissal
  session already held 勞基§13 at rank 8 and §59 at rank 7 when three promotions —
  one of them 公寓大廈§16 — pushed both out: with k fixed, every promotion forces
  an eviction, and once every window item is phrase-matched the trim takes the
  tail regardless. Promotions are now capped at the number of UNPROTECTED places,
  with a floor of one when that seat opens a topic the window lacks. Measured
  +3 (213/231 → 216/231) with golden unchanged; the floor itself costs nothing
  and keeps the reserved-first-seat property from two rounds ago.
- **One seat is now reserved for a topic the window LACKS.** Corroboration was
  handing all three to topics the ranking had already confirmed, so 民法§254 and
  §264 fired first and still lost. A corroborated row is by definition already
  represented; an uncorroborated one is a whole answer that is missing. Shipping
  it is a reshuffle, not a free win: §148, §264 and one §354 came back, §248 and
  one §505 went out, net +1 with golden unchanged at 19/7/0. It is the fourth
  alternative tried and the first that did not lose.
- **Corroboration cuts both ways, three times measured.** Giving a reserved seat
  to a row the ranking already confirms recovered 民法§248 and 刑§309; it also
  hands the seats to a topic that is confirmed but WRONG. 繼承編 for a living
  father (fixed by knowing he is alive), 租賃 for a bought air conditioner (fixed
  by knowing he bought it), and now 越界建築 for a spite wall that crosses no
  boundary — 民法§148 fires and never gets a seat. Three alternatives were
  measured and all lost: no corroboration at all, a saturation cap, and ranking
  by the strength of the evidence.
- **A crowded lexicon row is zero-sum.** The inheritance row now carries eight
  phrases for three seats, so adding 民法§1166 beside §7 did not add it — it moved
  the loss: §1166 and §1111 came back while §1164 and §1151 went out, and the
  total stayed at 158/170. Reverted, because two answers in older sessions are
  worth more than one supporting article in the new one. Rows are past the point
  where an addition is free — the next round used that: 民法§548/§550 went into a
  row of their own with their own triggers instead of into the 委任 row, and the
  still-running mandate session kept §541/§544/§549 intact.
- **One expectation was written wrong and corrected in the same round.** The
  protective-order-expiry case listed 家暴法§61 (violating an order) although its
  window had already been printed and did not contain it — §61 answers the OTHER
  protective-order session, not 「能不能延長」. Corrected with the reason recorded
  in the case itself. The standing rule against relabelling expectations exists
  to stop post-hoc inflation; an expectation that was wrong when written is a
  different thing, and saying which is which is the whole point.
- **Some answers need arithmetic, not vocabulary.** 「借三十萬,三個月後返還四十五
  萬」 never says 利息 or 利率, so nothing in a keyword table reaches 民法§205 —
  the rate is implied by the amounts. Forcing triggers for it would only misfire
  on other sessions, so it stays a miss with the reason recorded in the case.
- **Two rounds of it now, six cases, no regressions.** The definition seam keeps
  producing the same shape: a session about a favour (「只是幫忙不是受我委託」) got
  the 買賣瑕疵 articles, and a session about a contract labelled 承攬 got the
  承攬 chapter. In both the window carried the consequences of a classification
  nobody had tested.
- **Naming the failure mode found the next three cases.** Once 「the consequences
  arrive and the rule does not」 was written down, the blind-spot list turned out
  to be topped by DEFINITION articles — 民法§482 (僱傭), §528 (委任), §602
  (消費寄託), §799 (區分所有). The 僱傭 one was the sharpest: a session about a
  contract LABELLED 承攬 returned the entire 承攬 chapter, because nothing in the
  window tests whether the label is true.
- **The 準用 article can arrive instead of the article itself.** A woman living
  with her partner for three years got 家暴法§63-1 — the provision that extends
  the Act BY ANALOGY to partners who do not live together — while §3, which makes
  a cohabitant a family member outright, was absent. Her friend's claim (「沒結婚
  不算家暴」) is refuted by §3 and only awkwardly by §63-1. A neighbouring rule
  that reaches the same result is not the same as the rule that applies.
- **And it can fail the other way: the borrowed rules arrive without the article
  that lends them.** A man who swapped his camera for a phone that turned out to
  be water-damaged asked 「這種交換有沒有保障」 and got 民法§354/§359/§360/§365/§367
  — the sale-of-goods warranty chapter, which is exactly right, because §398 makes
  it apply to a trade with no price. §398 itself was unreachable. The window was
  therefore sale law offered to a man who knows he did not buy anything, with
  nothing in it explaining why sale law governs. The 準用 article substituting for
  the applicable one and the applicable rules arriving without their 準用 bridge
  are the same defect seen from opposite ends.
- **Which chapter applies decides everything, and nothing in the window asks.**
  Five instances now, and it is the most productive shape in the list. A contract
  labelled 承攬 returned the 承攬 chapter. A customer whose movers broke his table
  got the tort chapter, because 侵權 is what you reach for when a stranger damages
  something. A carer hired privately by a family got 勞基§11/§16/§17/§20 — every
  article assuming 勞動基準法 applies, when 民法§488 II governs and says either side
  may walk. A brother living rent-free in his late mother's flat got the whole
  繼承編 — who owns it, the question BEFORE 「can we make him leave」 — when free
  occupation is 使用借貸 and §470 II answers it. Money sent to a boyfriend got
  §474/§478 and the interest articles, all presupposing 消費借貸, when the entire
  dispute is whether it was 贈與 (§406) instead. The pattern: the window answers
  the question the FACTS look like, and the classification that decides the case
  is never in it. Definition articles are the cheapest fix — §464, §482, §406 are
  one row each. Two more the next round: a car park inside a building pulled in
  公寓大廈條例§4/§7/§10/§23/§26/§33 when the fight is whether a monthly space is
  場地租賃 or 寄託 (§589, and §590's 善良管理人之注意 for a PAID bailee — the duty
  「概不負責」 is trying to escape); and 「我拿一百五十萬給他當本錢,每月分我兩成」
  got §562/§707/§822/§881-3/§991 with nothing that names the relationship, when
  §667 is the definition and §681 makes partners jointly liable for what the
  partnership cannot pay. Seven instances, and the shape keeps paying: the window
  is built from the surface facts (a building, a shop, a transfer) while the case
  turns on a category nobody in the transcript names.
  Tenth instance: 「銀行說要有人一起簽,我以為只是當見證人就簽了,現在說我是共同借款
  人不是保證人,連催告朋友都沒有就來找我」 returned §273/§274/§277/§280/§281/§282 —
  the internal relations of joint debtors, every one of which presupposes the thing
  in dispute. §272 decides it (連帶債務 needs an express undertaking or a statute)
  and §745 is the right he is actually asking about: 先訴抗辯權, refuse to pay until
  the creditor has executed against the main debtor without result. §745 and §746
  were both structurally unreachable before this row.
  Eleventh: 「把二手名牌包交給二手店寄賣,抽三成,店家用他自己的名義賣掉六萬,只肯給
  我三萬」 returned §354/§359/§363, §390, §476 and even §807-1 (遺失物) — nothing
  that names the relationship. 行紀 is its own contract: §576 is 以自己之名義、為他
  人之計算、為動產之買賣, which is exactly what a consignment shop does, and §577
  routes the remainder to 委任 so the duty to hand over what was collected follows.
  §576/§577/§579/§587 were all structurally unreachable.
  Checked the same round and NOT a fix: the 旅遊 seam. 「出發前十天把溫泉飯店改成商
  務旅館、砍掉一個景點」 already surfaces §514-5 and §514-7 through plain lexical
  overlap — 旅遊/團費/行程 appear in the articles themselves. Stored as a regression
  lock, labelled as one.
  Twelfth and thirteenth: 「把車借給同事,他停紅線被拖吊還吃罰單,車借出去沒收他一毛
  錢」 returned §528/§542/§546 (委任) and §409 (贈與) — lending for nothing is
  使用借貸, and §468 (borrower owes 善良管理人之注意 and pays for damage) plus §469
  (通常保管費用由借用人負擔, which is what a tow fee is) were both unreachable. And
  「當店長三年,老闆說我是經理人不是勞工」 filled all eight seats with 勞基法 — the
  asker's own position — while 民法§553, the definition his employer is standing on,
  was unreachable. That one is the cleanest instance yet of 「the article the other
  side relies on is missing」: 「打卡上下班、薪水固定、大小事要問老闆」 are facts
  offered to be measured against §553, and the window could not show the yardstick.
  Fourteenth: 「估價一萬二,修好算我三萬八,我不同意就說錢沒付清車子不能牽走,已經扣在
  廠裡三個星期」 returned §493/§495/§505/§509 (承攬), §601, §217, §196 — the work and
  its price — while the FIRST thing he asks is whether they may hold the car at all.
  §928 is 留置權 and §929 is why a garage has one without agreeing anything (商人間
  因營業關係而占有之動產,視為有牽連關係). §928/§929/§936 were all unreachable.
  Fifteenth, and the first time an entire 編 had never been reachable at all:
  「相機拿去當鋪借兩萬,第四個月拿錢去贖,他們說早就賣掉了只肯退我五千」 returned
  eight seats of 消滅時效 (§125/§126/§129/§144/§197) plus §473/§365/§205 — not one
  article about the pledge the transaction IS. §884 is 動產質權 (possession
  transferred as security, priority in the proceeds) and §893 is what the shop may
  actually do, its second paragraph subjecting a 流質 clause to §873-1 — which is
  why 「只肯退我五千」 is not the end of the matter.
  Sixteenth, and the one that shows the seam is not always a coverage problem:
  「外送平台系統派單不能挑,拒單太多會被降權,平台說我們是承攬不是僱傭」 returned
  勞基§24/§32/§32-1/§33 mixed with 承攬§493/§502/§505 — every article presupposing a
  classification already made, which is exactly what he is asking about. Unlike the
  pawnshop, 勞基§2, 民法§482 and §490 were all REACHABLE; no row that reaches them
  fires on a platform worker's words, so this was cause (c). Putting the three
  definitions side by side lets the facts he offered — cannot decline jobs, gets
  down-ranked, buys the uniform himself — be measured against all of them.
  Seventeenth: 「一歲女兒送去保母家,一個月兩萬四,保母說小孩自己跌倒縫了三針,但監視器
  是她在滑手機」 returned §184/§191-2/§193 and — for a child who needed three stitches
  — 民法§192, the article about compensating a DEATH, plus §611 (運送人). A PAID carer
  is measured by §535 (其受有報酬者,應以善良管理人之注意為之), which is exactly what
  「她在滑手機」 is offered against; §227 is the contractual route beside the tort one.
  §535 was structurally unreachable.
  Eighteenth: 「六萬八請婚攝…後來說硬碟壞掉原始檔全沒了,只肯退我兩萬」 returned
  §354/§359/§361/§363/§365 — the SALE-of-goods warranty chapter — plus §254/§259, with
  only §502 touching 承攬. The point is not that the work is defective but that it is
  GONE and cannot be redone: §226 給付不能, §256 the rescission that follows it, and
  §495 for 「只退兩萬合理嗎」 — damages are not capped at the fee. Like the rider case
  this was cause (c): all four articles were reachable and no row fires on a
  photographer's words.
- **The most expensive over-wide trigger measured so far was 「加收」.** A logo-design
  dispute — 「設計師說超出修改次數要加收一次五千」 — came back with 公寓大廈條例
  §14/§25/§28/§30/§32/§34 and 民法§56: eight seats of apartment-management law,
  with all THREE reserved seats taken by the 會議決議 row. 加收 is what any service
  dispute says; it is not the language of an owners' meeting. Removing it returns
  that window to 承攬 (§493/§509) and the row's own session still fires on
  開會通知/決議/會議紀錄/沒有出席. No case gained or lost across the stored set — the
  measurement is the eight seats.
  Nine instances now, and the ninth paid a dividend the others had not: adding the
  承攬 DEFINITION (§490) for 「訂做的東西」 also recovered 民法§505 in
  pay-only-after-delivery, a miss that had survived every round since it was
  written. The standing misses are not all independent problems — some are the
  same missing classification seen from a different session, which is an argument
  for fixing seams rather than chasing individual misses.
- **A standing miss can be an article that was reachable all along and simply
  outranked.** Three of the long-lived misses turned out to share one cause, and
  it was not coverage. 民法§191 (工作物所有人負賠償責任) had a row, and that row
  FIRED in both the falling-tile and the burst-pipe sessions — but every trigger on
  it was two characters (外牆, 漏到), and `expansions()` sorts by trigger LENGTH
  first, so 「管委會」 (three) took the reserved seats and §191 never reached the
  window. Those windows carried 民法§184 instead, which makes the asker prove the
  fault §191 presumes. Same story for §354/§359 on the sale-defect row: 瑕疵, 故障,
  維修, 退錢, 二手 are all two characters, and an air-conditioner session lost them
  to 「換新的」. The fix was not a new row or a new article — it was words long
  enough to win (掉下來, 砸凹, 水管爆, 漏到我家, 來修了, 修不好, 泡水車). A row
  built entirely from short triggers is volunteering to lose every tie it enters.
  Reshuffle, both sides: repaired-four-times went from missing §354+§359 to missing
  §227 — two recovered, one evicted, and both 瑕疵擔保 and 不完全給付 are real
  routes for a unit repaired four times.
- **A row's fourth and fifth phrases can never be delivered.** Seats are 3 and the
  promoter takes ONE article per phrase, so position 4 onward is unreachable by
  arithmetic, not by ranking. 民法§505 was the 承攬 row's fifth phrase: in
  「材料另外算要再加十二萬」 that row won expansion positions 0,1,2,3,4 — it beat
  everything — and still could not produce §505. Moving the phrase to the front
  recovered the case and cost nothing across all 146 sessions (292 -> 293, no new
  miss). Worth checking every row with more than three phrases against the
  sessions it fires in; the ones that matter are where the fourth-or-later phrase
  is the article the asker actually needs.
  In the same pass 民法§248 came back for earnest-money, cause (b): 「斡旋」 is two
  characters and lost every seat to 「手續費」 (three), so 斡旋金/斡旋金收據/全額退還
  went in — the words only that session's kind of asker uses.
  Not shipped, recorded: stop-the-renovation §494 and debtor-moved-assets §478 are
  both blocked by the same three-seat ceiling with no reordering available. §494
  loses to 民法§511 (定作人得隨時終止契約), which is *also* right for that session,
  and §478 loses to the 脫產 row's own three phrases. N=4 reserved seats was
  measured and rejected long ago (13/11/2 golden), so these stay missing.
- **Two wrong diagnoses in a row, both caught by re-measuring.** Worth recording
  because the corrections are the useful part. §494 was first written down as
  「loses to §511」, then, after the phrase-position rule was found, as 「sits at
  phrase index 4 and is therefore undeliverable」. Acting on the second reading —
  splitting the 承攬 row by question (有沒有瑕疵 / 報酬何時到期), so every phrase
  falls inside some row's first three — did gain a case, but not that one: it
  recovered 民法§359 for seller-lied-on-purpose instead. §494's real cause was a
  third thing: 「做到一半」 is a trigger on the 委任-TERMINATION row, so in a session
  about a builder abandoning a renovation, §548 and §550 (a mandate ending) took
  two of the three reserved seats and pushed §494 to expansion position 5. The
  mandate row's own session says 「辦到一半」 — paperwork at a 代書 — and keeps
  firing on that plus 做多少算多少. Dropping 做到一半 recovered §494 at no cost
  (294 -> 295). The lesson is procedural: a diagnosis that explains the symptom is
  not the same as the cause, and the only test is to apply it and see which case
  actually moves.
  A test written in the same round asserted §494 must land in the first three
  expansion positions. It does not — it wins a seat from position 3, because the
  promoter skips phrases whose article the ranking already put in the window. The
  assertion was measuring an incidental index rather than the contract.
- **Cause (c) is usually one sentence the row never imagined.** Three of the five
  (c)-class misses closed in a single pass, each because the row that reaches the
  article described a different kind of asker:
  民法§184 — the session REFUSES money (「我要的是修回原狀不是拿五萬」) while every
  trigger on the tort row names a claim for cash; 「是他們造成的」 is the causation
  the claim rests on and appears in no other stored session.
  消保§12 — the asker never says 定型化 or 審閱, he says 「業者堅持契約寫以高雄地院
  為管轄法院」, which is the textbook unfair term that article exists for.
  民法§153 — joined §345's row rather than getting its own: same answer at a higher
  level of generality, and that row had ONE phrase, so both sit inside the three
  deliverable slots. The 意思表示解釋 row also reaches §153 but fires on
  各說各話/怎麼解釋 — a fight about what words MEANT, not whether a contract exists.
  Predicted three, fixed exactly those three, no new miss (295 -> 298).
  Diagnosed and NOT shipped in the same pass: 民法§354 for damaged-in-transit. The
  new 裂了/裂掉 triggers do fire, but §354 lands at expansion position 4 because the
  broad 侵權 row takes seats 1-3 off the single word 「損失」 (「這個損失該誰承擔」) —
  the same seat-theft shape as 做到一半 last round, one layer up. Dead triggers were
  removed rather than left in to look busy; the cause is written down instead.
- **The obviously-wrong trigger was holding the right chapter up.** 「七天」 and
  「解約」 on the distance-selling row pull 消保法§19 — a seven-day cooling-off right
  for online purchases — into a package-tour complaint (「跟團去日本七天」, a DURATION)
  and into a gym contract. Two sessions tripping it made it worth an A/B. Removing
  just those two triggers: recall 333 down to 331, and the entire loss is the tour
  session falling from 2/2 to **0/2** — §514-5 and §514-7 gone, replaced by three
  articles of 道路交通管理處罰條例. The terms the row expands into were part of what
  kept the 旅遊 chapter ranked; the 消保法§19 that looked like the defect came with
  them. Second time this shape has been measured (the first was the 「修了幾次」 row),
  and it is now the standing rule: a trigger earns its seat through the QUERY it
  expands, not the articles it names, so nothing is narrowed without an A/B.
- **Read end to end, the page contradicted itself.** The first full read of a finished
  page — answer, ladder, deadline rung, letter, skipped-articles block, judgments,
  2,694 characters — found 買到贓車 saying 「對方的說法…站不住腳,因為你已經將行照過戶,
  且買賣雙方均有善意」 and then printing 民法§949 three lines below: 原占有人自喪失占有
  之時起二年以內,得向善意受讓之現占有人請求回復其物. Good faith does not defeat §949;
  the analysis was backwards and the page's own ladder said so. The model cannot be
  argued out of this (two measured attempts), but §949 was reaching the reader ONCE,
  inside the deadline rung, and was missing from the skipped-articles list because it
  sat sixth in retrieval order and the list showed five. Articles that state a period
  now lead that list — they are the ones a reader can be caught by. §949 now appears
  in both places, and expected articles visible on the page went **17 → 18 of 21**,
  with 買到贓車 reaching 3/3.
- **What the model skipped is now printed for the reader.** Two attempts to widen the
  8B model's citations failed (below), so the ceiling was routed around instead of
  argued with: everything retrieval found and the answer never mentioned is listed
  under the ladder, verbatim, labelled as not-yet-discussed and left for the reader to
  judge. Measured across the saved sessions: expected articles VISIBLE on the page
  went **8 → 17 of 21**. 業務簽的約 went from **0 to 2** — that page previously showed
  nothing the case turns on. Pure Stage 4 code, no prompt and no gate touched.
- **Tried and not shipped: ordering the model to walk the list.** If the answer cites
  only 20 of 56 retrieved articles, the obvious move is to make the coverage clause
  explicit — number every article in the model input (`[3/8]`, with the count stated
  up front) and tell it to review each one and say what it does for this case. Result:
  **16/56 cited, down from 20**, and expected articles reaching the answer went
  **9/24 → 8/24**. A checklist did not widen the 8B model; if anything it narrowed it.
  Reverted. Two caveats kept in the open: the run was on a degraded machine (the local
  model was generating at 1.24 tokens/sec and one session needed a retry after a
  three-minute timeout), so the exact figures are noisy; and golden could not finish at
  all under those timeouts, which by the project's own rule is on its own sufficient
  reason not to ship a SYSTEM_PROMPT change.
- **The model, not retrieval, is what keeps articles off the page.** Across eight
  sessions the answer cites **20 of the 56** articles retrieved, and in five of them
  only nought to two. Retrieval had already found what the case turns on: for six of
  the eight, **3 of 3** expected articles were in the window, while the answer cited
  at most one of them. So the letter and the deadline are mostly filled from articles
  the model ignored, and that is a ceiling no amount of retrieval work moves.
- **Tried and not shipped: ranking the un-cited remainder by the reader's own words.**
  If the tail must supply most of the letter, order it by how many character bigrams
  each article shares with the session text. Measured: expected articles reaching the
  letter's three 依據 lines went **9 → 7** across seven sessions — 買到贓車 and
  借名登記 each lost one. Lexical overlap with a lay description does not indicate
  which article governs, and plain retrieval order was already better. Reverted, with
  the helper deleted rather than left behind a flag.
- **The ladder now follows the answer's citations instead of the retrieval order.**
  Retrieval rank cannot tell whose right an article states, which is why 買到贓車's
  letter quoted §950/§805/§807 — 遺失物拾得 — and its deadline rung led with §805's
  finder's-reward six months. Stage 3 already knows which articles the ANSWER cited;
  the ladder simply was not given them. It is now, through the one call site in
  flow.py. Measured on eight saved sessions: letter 依據 lines that the answer also
  cited went **8/22 → 13/22**.
  What it does NOT fix, and the trade recorded plainly: the ladder now inherits the
  model's choices. In the saved 買到贓車 answer the model cited only §948, never §949
  — so §948 moved to the front of the letter exactly as intended, and §949, the
  article that decides whether he keeps the bike, still never reaches it. Retrieval
  order was blind to the case; answer order is only as good as the answer.
- **The 存證信函 rung pointed at a template the page never printed.** 住宅噪音's rung
  said 「見 letter_template」, app.py relabelled that string to 「見 存證信函範本」, and
  nothing rendered it: `render()` left the field out and neither run.py nor app.py
  picked it up. Every other kind of case had no template at all — the reader was told
  「寄出書面請求」 and left to work out how a 存證信函 is written. It renders now, and
  a generic one is built for every session from the retrieved articles: **168/168**
  sessions get a template, **0** of their 依據 lines are anything but corpus text.
  Only the request and the facts are blanks; the tool does not draft assertions of
  fact on anyone's behalf.
  Measured defect kept in the open: the letter cites the top three of the retrieval
  window, and for 買到贓車 those are §950/§805/§807 — 遺失物拾得 — while §949 and §948,
  the articles the case actually turns on, sit sixth and eighth. The template says
  「與你情況不符者請自行刪去」 rather than pretending the selection is right. Same root
  as the deadline rung's known limit: neither can tell whose right an article states.
- **The first thing every reader was told to do was the same sentence.** The ladder
  opened with 「把事實與證據整理成一頁時間軸」 whether the person had lost a moving box,
  a wedding video or a motorbike to the police. It now names the documents THEY said
  they have — 婚攝 gets 合約, 贓車 gets 行照, 倒會 gets 匯款紀錄、會單, 送洗 gets 送洗單
  — and falls back to the generic line when the session names nothing. **83 of 168**
  stored sessions get a case-specific first step. Nothing is suggested: a word appears
  only if the user typed it, so the rung never invents evidence they do not hold.
- **Model reasoning was printing under the heading that promises statute text.**
  Eight sessions read end to end: 4 of 30 bullets under 法律明文 were the model's own
  inference, not law. In the 業務簽的約 session they were also backwards — 民法§169
  makes the COMPANY answer for holding a salesman out, and the bullet told the reader
  that HE had been treated as the agent. Under that heading a lay reader takes it as
  the statute. Such lines are now moved into 分析研判 by code, with a marker saying
  where they came from; nothing is deleted, because they are the model's to say, just
  not there. Measured on the same eight: **4 → 0**. When the move empties the section
  entirely — as it did for 業務簽的約, where both bullets were prose — it is rebuilt
  from the retrieved articles verbatim rather than left as 「(無)」, which would hide
  law that was actually found behind the model's silence. Honesty tier 27/32 and
  wrong-premise 32/32 unchanged.
  Limit, recorded rather than papered over: runs shorter than 14 characters are not
  judged, so a brief assertion could still pass. Every paraphrase measured was a full
  sentence, and the floor is what keeps list markers and 「(無)」 from being treated as
  prose.
  Also a correction to this round's own first measurement: it reported 12 of 30 by
  comparing a punctuation-stripped line against unstripped corpus text, which called
  民法§226 and §541 paraphrases when they were quoted word for word. Strip both sides
  and it is 4.
- **The number the reader came for was on the page, three lines below where they
  stop.** 「我能拿回多少」 has an answer: the corpus carries 1,367 judgments and the
  reference block prints the sum from each 主文 verbatim. Of 60 sampled sessions,
  50 had at least one judgment stating an amount — and the first one listed carried
  a figure in **0** of them, because the block was ordered by article overlap alone.
  For the 婚攝 session that put 判賠 260,000 元 third, under two citations with no
  number at all. Parsing is now widened past the three shown and award-carrying
  judgments sort first, stably, so overlap order survives inside each group:
  first-listed carries an amount in **55 of 60**, and sessions with any amount rose
  50 → 55 because the widened window reaches judgments the old top-three slice cut
  off. Nothing is computed — the sums are verbatim slices of the 主文.
  Correction to the previous round's defect list: 「沒有金額區間」 was wrong. The
  feature existed; the end-to-end harness printed only `.answer` and skipped the
  block that `run.py` and `app.py` both render.
- **The section the reader actually needs was boilerplate, and more facts made it
  worse.** Sampled end to end as a user: 婚攝, 贓車 and 共同牆 all returned a correct
  「法律明文」 block and then 「現有資料不足,建議諮詢律師」 under 分析研判. Re-running
  the 婚攝 session with a FULL intake (金額/契約/時間/對方說法/證據/想要的結果) listed
  **thirteen** articles and produced the same sentence. The cause was in the prompt:
  it offered 「若資料不足…必須明說」 as an escape and said nothing about what the
  section must contain. Now the escape is allowed only when 法律明文 is 「(無)」, and
  the section must name who to claim against, under which article, whether the other
  side's stated excuse holds, and what to keep.
- **Then the model invented a deadline, so deadlines were taken off it.** With the
  new instruction the 婚攝 answer asserted 「時效:半年內買方應該催告賣方履行」 citing
  民法§254, which contains no period at all. Asking an 8B model to spot time limits
  turns a useless answer into a confidently wrong one. The prompt now forbids it from
  stating any period, and the ladder grows a rule-based rung that quotes the periods
  the RETRIEVED ARTICLES themselves state — verbatim, no arithmetic, no inference.
  It fires on **69 of 168** stored sessions. Two things it does not solve, recorded
  rather than hidden: it cannot tell whose right a period belongs to (民法§805's
  finder's-reward six months still lists above §949's two years for the stolen-bike
  session), and it says so in the rung text instead of picking for the reader.
  Within an article the selection did improve — 冷氣修四次 now surfaces §365's actual
  limitation sentence instead of its 前項 exception clause, and 消保法§11-1's 審閱期
  (a period the SELLER owes) no longer appears as a deadline at all.
- **Promotion can only move an article that is already in the candidate pool.**
  A session about a co-inherited field one brother had let out on his own
  (「大哥私下把整塊地租給人家種果樹,契約只有他一個人簽,租金全進他口袋」) returned
  eight articles about PARTITION. A new row put 民法§828 III, §821 and §179 at
  positions 0, 1 and 2 of the expansion list — the top three, ahead of every other
  firing row — and only §828 reached the window. Splitting the row into three, one
  phrase each, changed neither that window nor the neighbouring session's. So the
  reserved seats do not conjure articles: they REORDER the pool that BM25 and the
  dense retriever already produced, and §821/§179 never enter it for this query.
  The case is stored at 1/3 with the reason written down rather than with its
  expectations trimmed to whatever retrieval happens to deliver — which is why the
  published recall reads 98% this round and not 99%.
- **The row-relevance scan was measuring something narrower than it claimed.**
  Thirteen rounds of「no row is dead」, then it flagged one: the row triggered by
  「修了幾次」/「修過四次」 fires on three sessions and had never supplied an expected
  article. Removing it cost recall — 326 down to 325, because repaired-four-times
  loses 民法§359. The row carries §227's phrases, and §227 is a known miss in that
  very session, so the scan scored it 0; what the row actually does is feed 不完全
  給付/瑕疵/換新的 into the BM25 query, and §359 rides in on that. Window quality
  moved the same way: without the row, renovation-defect picks up §430 (the
  TENANCY repair article) and which-court-to-sue keeps §227 instead of 消保法§17.
  A row can earn its seat through the query it expands rather than the articles it
  names, and a scan that only credits the latter will keep proposing to delete it.
  Kept, with the reason recorded here instead of in a commit that looked like work.
- **The seat-theft scan only works with the miss filter on.** Written to hunt the
  shape caught twice by hand (委任's 做到一半, 侵權's 損失), the raw version flags
  12 rows that take a top-3 seat in a session whose expected articles they cannot
  supply — and most are false alarms, because a row can be genuinely on topic
  without being the answer (侵權§184 is relevant nearly everywhere and expected
  almost nowhere). Filtered to sessions that ACTUALLY lost something, it returns
  two, and both thieves are the same row: 侵權 taking seats 1 and 2.
  The new one is 「住院」. It fires in five stored sessions and in FOUR the person in
  hospital is not the claimant — a father with a stroke (maintenance), 「我媽住院急
  需三十萬」 (why he took the loan), 「我生病住院他也不聞不問」 (a donor revoking a
  gift), 「我住院那三個禮拜請鄰居顧店」 (a mandate). That also corrects the record
  on signed-in-desperation: its §205 miss had been written down as purely 「the rate
  is implied by arithmetic」, and the tort row holding two of its three seats is a
  second, independent cause. Measured: 3 tort seats across those four windows, 3 ->
  0, recall unchanged either way (298/303) — injury-claim keeps firing on 骨折/醫藥費.
  The scan's next hit was left alone on purpose. signed-in-desperation also loses
  seats to the WAGE row, off 「我一個月薪水三萬多」 — his capacity to repay, not an
  employment dispute. But 薪水 appears in 7 stored sessions and 月薪 in 6, nearly all
  genuine labour cases, and 薪水 simply IS the everyday word for wages: any narrowing
  trades six real cases for one. Diagnosed, not shipped.
- **A context filter cannot tell an article ABOUT a topic from one that mentions
  it in a list.** Diagnosing the remaining misses by cause produced three buckets
  — unreachable (1), reachable but outranked (7), reachable but the row does not
  fire on that session (5) — and one case refused to fit any of them. 民法§15-2
  sat at expansion position ZERO, the top reserved seat, and still never reached
  the window, because it was never in the CANDIDATE POOL: `_drop_inheritance_
  while_alive` matched 繼承 words against the whole article, and §15-2's list of
  acts a 受輔助宣告之人 needs consent for includes 「為遺產分割、遺贈、拋棄繼承
  權」. The filter written to protect a living parent's session was deleting the
  one article that session needed. Matching the article's FIRST line — the
  sentence that sets its subject — fixes it: §1138 opens 「遺產繼承人，除配偶外」
  and still goes; §15-2 opens 「受輔助宣告之人為下列行為時」 and stays.
  Both sides: the looser rule let 民法§1145 (喪失繼承權) into a living-father
  window, which is exactly what the filter exists to prevent, so 繼承權 was added
  to the subject words — §1145 is dropped again while §15-2 survives, and the
  brother-hid-the-will session (where the father HAS died, so the filter never
  runs) still carries §1145 at rank 1.
  Auditing the other two filters the same way found the same bug once more, and
  cleared the third. The TENANCY filter runs on 7 of the stored sessions and in
  every one of them was deleting 公寓大廈條例§3 (definitions) and §27 (區分所有權人
  voting) — not tenancy rules, and exactly what an owner in a building may need —
  because those articles mention 承租人 below their first line. Fixed the same
  way, with 「租賃」 added to the subject words so the real tenancy articles still
  go (§421 「稱租賃者」, §450 「租賃定有期限者」, §462 「耕作地之租賃」 name no
  承租人 in their opening line either). Recall did not move: no case expects those
  two articles, so the measurement here is the deletion itself — 7 sessions × 2
  articles that should never have left the pool. The INDUSTRY filter was checked
  and left alone: the five articles it drops on a whole-text match are all
  租賃住宅條例 trade-administration provisions, which is precisely what it targets.
  The general lesson is worth more than the two fixes: **a filter that reads the
  whole article cannot tell what an article is ABOUT.** Silent deletions are the
  hardest defect class in this system — nothing downstream can recover from them,
  and they are invisible until a case happens to need the article.
- **The window can hold every consequence of a rule and never state the rule.**
  A session asking whether joint liability existed at all got §273/§274/§277/§280
  and §281 — how joint debtors are pursued, released and reimbursed — with §272,
  the article that says it only arises when expressly agreed, nowhere in sight.
  The same shape hit 民法§274, §277 and §1115 in earlier rounds: the answer's
  neighbours arrive and the answer does not.
- **The article the OTHER SIDE relies on has to be in the window too.** A driver
  told 「你已經領過保險金了,我只賠六萬」 got §184/§188/§193/§213 — his own claim,
  well covered — and never 民法§216-1, which is the entire basis of the sentence
  said to him. An answer cannot test an opponent's argument while the statute it
  rests on is absent, and the asker is left with 「他說的對不對?」 unanswered.
- **A window can face the wrong way.** A buyer defending the house he paid for
  got 民法§244, §242, §87 and §88 — every route by which a transfer is undone —
  while §759-1, the presumption that protects a good-faith registered owner, was
  absent. The articles were on-topic and pointed at the opposite outcome. Related
  to the denied-premise case below, and distinct: nothing here contradicts a
  stated fact, the window just answers the other party's question.
- **A window can be built on a premise the asker already denied.** 「我在實體店面
  訂了一台縫紉機…是實體店面下訂不是網購」 returned 消保法§19, §19-2, §18 and §20 —
  the distance-selling right to cancel — because 訂/退 look like online shopping.
  Nothing in the pipeline notices that the sentence rules that chapter out. The
  answer that does not depend on how it was bought (民法§88, mistake) was absent
  entirely. Distinct from the noise cases: this is not an irrelevant article
  taking a seat, it is the window agreeing with a fact the user corrected.
- **The citation can be real, verbatim, in-window — and still be the wrong
  article for a conclusion that happens to be right.** Asked whether a new owner
  owed the wages the old one skipped, the model reached for 民法§425 (買賣不破
  租賃) and wrote 「新老闆繼承了舊老闆的所有權利和義務,包括支付欠薪的責任」. The
  citation passes every gate — it exists, it is quoted correctly, it was in the
  window — and the outcome is roughly what §305 would give. Nothing in the
  pipeline can catch this: the verifier checks that a citation is real, not that
  it is *apt*. It is the strongest argument for fixing retrieval rather than
  prompting harder — 民法§305 and 勞基§20 were simply not there to be used.
- **Whether there is a CONTRACT decides the chapter, and the window does not
  ask.** 「搬家公司來的工人把餐桌摔壞,公司說工人是臨時找的,叫我去找工人賠」
  returned §184/§188/§189/§192/§193 — the tort chapter, which is the answer for a
  stranger hit in the street, not for a customer who paid. Worse, 「臨時找的」 is
  exactly the sentence that breaks §188's 受僱人 link, so the window's best
  article was the one the opponent had already defended against. 民法§224 makes
  the debtor answer for whoever he used to perform, and the CLI refused the whole
  question at 資料涵蓋不足 rather than surface it.
- **A trigger can name the act and still get the role wrong.** 「我三年前把名下
  的房子贈與過戶給兒子,講好他要照顧我到老,過戶完他就搬走」 returned 民法§244,
  §242 and §87 — the creditor's routes for undoing a DEBTOR's transfer — because
  「過戶給」 was a 脫產 trigger. The act is identical whichever side you stand on;
  only the role differs, and a substring cannot see a role. The rule 「a trigger
  must name the ACT, not the situation and not the remedy」 was written after six
  hijacks and is still not enough: 過戶給 is an act, and it was still wrong.
  Narrowed to the words only a creditor uses (名下唯一、脫產、假買賣); the session
  that motivated the row keeps firing on 名下唯一, and a buyer defending his own
  registration stops being handed 詐害債權 noise.
  It happened again the next round with 「欠銀行」 on the 拋棄繼承 row: a card-debt
  session (「我的卡債本來是欠銀行的,資產管理公司說債權買過去了」) came back with
  §1159/§1162-1/§1174/§1175 — four articles about a dead person's family — for a
  living debtor. Two instances now, both from words that describe a situation two
  different people are standing in. The scan that catches them is cheap and is
  now part of the routine: before a trigger ships, grep it across every stored
  session and reject anything that lands in a case from another domain or inside
  a denial.
  A third one turned up the round after, and it was the oldest trigger in the
  table: bare 「吵」 on the flagship noise row. 「對方一直來我家吵」 (a debt dispute)
  put 社會秩序維護法§72 into that window, and 「昨天吵架他推我」 fired it inside a
  beating. 吵架 is a quarrel; only the compounds (很吵/吵到/吵死/吵得/吵鬧/吵雜)
  are complaints about sound. The golden 深夜喧嘩爭吵 cases keep firing on
  深夜/喧嘩, and the noise sessions on 跑跳/拖椅子/半夜. Worth naming the pattern:
  the trigger that has been in the table longest is not the safest — it is the
  one written before the rule existed.
  So the next round stopped guessing and swept all 347 triggers of one or two
  characters against the stored sessions, asking of each firing whether the case
  belongs to the row's domain. Four more fell out, all measured, none of them
  costing a single legitimate firing:
  **「聲」** is inside 聲請 — every one of its five firings is a court application
  (聲請保護令/監護宣告/拍賣), and two windows paid for it: a protective-order
  session lost two of eight seats to 公寓大廈§16 and 民法§793, an emergency-order
  session one to 社維法§72.
  **「過戶」** on the 買賣瑕疵 row fired in nine sessions of which two were
  purchases; 脫產, 假買賣, 遺腹子繼承, 受任人過世 and 藏遺囑 were all being handed
  民法§360.
  **「樓下」** appears once in the whole set — 「前男友每天來我家樓下按門鈴」.
  **「怎麼算」** on the 扶養 row was the most expensive, because specificity
  ordering sorts by trigger LENGTH: at three characters it outranked every
  two-character trigger, so 「遇假日怎麼算」 put 民法§1119 in reserved seat #1 of a
  payment-deadline window and pushed §122 out entirely. A long generic trigger is
  worse than a short one — it wins the seats as well as taking them.
  Removing 過戶 then cost 民法§244 in debtor-moved-assets, which is the useful part
  of the story: that case had been passing **because of** an expansion from the
  wrong chapter — the 買賣瑕疵 phrases were adding enough lexical mass to the
  expanded query to keep §244 inside the eight. Restoring the trigger would have
  hidden the real culprit, another long generic trigger: 「算不算數」 on the
  waiver row, four characters, taking reserved seat #0 ahead of 名下唯一. It fires
  in four sessions and only one is about a signed waiver — the others ask it of a
  transfer, a settlement and a loan-shark contract. Dropping it put §244 back at
  rank 1 and left the 過戶 fix in place. A passing number can rest on a defect;
  the only way to find out is to remove the defect and watch what falls.
  The three-character pass found one more: **「三年前」/「五年前」** on the
  limitation row. They fire in seven sessions and only one is asking about the
  clock — the rest merely date a fact (「三年前買的房子」、「三年前幫朋友做保證
  人」). Seats paid: seller-says-registration-wrong 4 of 8, co-debtor-already-paid
  3, guarantor-after-main-debtor-released 2. Dropping them moved recall by exactly
  nothing (260/277 before and after, no case gained, none lost), so the seat
  counts ARE the measurement — this is the precision blind spot in its purest
  form, and the change ships on the standing sweep rule rather than on a number.
  Measured and NOT shipped in the same pass: earnest-money's long-standing
  民法§248 miss looked like 屋主/買房 on the 買賣瑕疵 row crowding the 定金 row out.
  Dropping either changed nothing; dropping both made it **worse** — §249 fell out
  too. That case is partly held up by an expansion from the neighbouring chapter,
  the same way debtor-moved-assets was, except here removing it does not reveal a
  better fix. It stays a miss with the reason recorded.
  The fourth pass — triggers of four characters or more that are plain everyday
  speech — found three: **「聯絡不上」** on the prepaid-trader row (it describes a
  hit-and-run driver and an upstairs neighbour just as well as a shop that shut,
  and it put 消保§17 into a window about a leak between two flats),
  **「我完全不知道」** and **「跑來說」** on the 登記推定力 row (six and three
  characters of pure conversation, putting 民法§759-1 into a guardianship-duties
  window and a sublet dispute). Every motivating session keeps firing on its
  domain-specific triggers. The lesson across four passes is one sentence: a
  trigger earns its place by naming something only this domain's sessions say,
  and length is no evidence of that — the longest offenders were 我完全不知道,
  算不算數 and 怎麼算.
  The fifth pass inverted the search: instead of judging triggers by shape, score
  every ROW by how often it fires in a session whose expected articles it could
  never supply. One row came back at 6 firings and 0 relevant — 冷氣/機器 on the
  公寓大廈§16 row — and it was the worst contaminator measured anywhere: one seat
  in FIVE unrelated windows (a factory hand crushed by a 機器, a tenant's two
  分離式冷氣, a 機器 bought to the wrong spec, a dismissal during medical
  treatment, a branches-over-the-yard case). Those two words name OBJECTS; the
  noise signal is the disturbance word beside them (低頻/震動/很吵), which is what
  the golden 冷氣機半夜低頻震動 case fires on. Every freed seat went to an
  on-domain article — 勞基§26, 民法§425, 消保§19-2, 勞基§13, 民法§835 — and no
  case lost anything. Ranking rows by irrelevant-firings is now the cheapest
  sweep available; the metric is noisy for broad rows like 侵權 (§184 is relevant
  everywhere and expected almost nowhere), so only the zero-relevant rows are
  acted on. Run again the next round it came back empty at both thresholds — no
  row firing twice or more had zero relevant cases — which is the honest end of a
  sweep: five passes found twelve bad triggers, and the sixth found none. Recorded
  rather than padded out, because a scan that reports nothing is the only evidence
  that the previous ones were worth running.
- **Precision has no harness.** 租賃住宅市場發展及管理條例 also regulates the
  leasing trade, and its 營業保證金 / 罰鍰 articles are the longest in it, so BM25
  gave them 2-3 of 8 seats in EVERY landlord-tenant session (10/176 seats over
  the real set, now 0/176). Dropping them moved no published number — the freed
  seats went to on-topic articles that were not the expected ones — which is
  precisely the blind spot: the harnesses ask whether the right article is in
  the window, never what else the visitor has to read.
- **The model-free intake under-labels on purpose.** Without a local model (the
  HF Spaces configuration) filing is keyword-driven, and a line matching no hint
  word is kept as narrative instead of taking the pending field's label. It was
  the other way round and every field came out one place off — a visitor's
  「我想拿回押金」 was displayed as 已採取行動. The trade is real: 「口頭要求被拒」
  was a true 已採取行動 answer that no hint word recognised, so the hint lists
  have to grow with what people actually type.
- **Three reserved seats, more than three good pointers** — mostly solved. Seats
  go to the phrases that identify ONE article, and among those, to a row the
  ranking has already corroborated (one of its articles is in the window):
  finishing a confirmed topic beats opening a new one. That recovered 民法§248
  and 刑§309, the two the old table-position tie-break lost. Widening was
  measured and rejected instead: a 4th seat is identical to three and a 5th
  costs both harnesses (45/49, 18/8/0) by trimming the ranked window.
- **A trigger must name the ACT, not the situation and not the remedy.** Four
  separate rows over-fired on a word that is true of many stories at once:
  聯絡不上 (said whenever anyone goes quiet), 公同共有 (true of every estate before
  it is divided), 求償 (said in every compensation question) and 名下沒有財產
  (which describes poverty, and hijacked a maintenance session into the
  asset-transfer articles). Each cost another
  session an article, and each was caught in the run that introduced it.
- **A trigger has to be the word the ASKER used, not the word for the problem.**
  Three times a correct row failed to fire because the trigger was how I would
  label the situation rather than how a person states it: 拆掉 against 「不肯拆」,
  賠償 against 「要求他賠」, 文字含糊 against 「該用誰的解釋」. Each was invisible
  until the session was run and the phrase list printed.
- **Each lexicon row is also a new way to be wrong.** Nine times now, a row
  added to fix one session hijacked another off a word said in passing (買房 →
  warranty, 前妻 → DV route, 繼承 → 繼承編, 仲介 → the rental trade, 分期 → the
  instalment articles, 管委會 → the arrears articles over a noise complaint) or
  by sitting in the wrong row (民法§1164 in the co-ownership row cost an
  inheritance case its §1141). Two of the seven were caught in the same run that
  introduced them, which is what the growing session set buys; every added row
  ships with the counter-example as a test.
- **Shipping the judgments cost four sessions their headline number, and the
  number moved in the published direction.** A fresh clone used to get 2,560
  statutes and ZERO judgments — `db/*.db` is gitignored and the 司法院 API serves
  only 00:00-06:00, one day at a time, seven days late — so the README's own
  screenshot was the one thing nobody but me could reproduce. 386 of the 1,367
  now ship, redacted to the header and the 主文, which is measured LOSSLESS for
  what the page renders (`citation()` and `awards()` identical on all 386) and
  takes 5.9 MB down to 0.27 MB.
  The cost is real and is the reason this entry exists. 31 of the 386 name a
  party inside a 主文 sentence and ship with their header alone, so `awards()`
  goes silent on them. Re-measured over 60 stored sessions with a fresh harness:
  first-listed judgment carries a sum **54/60 on the full local corpus, 50/60 on
  the shipped one**. The published row moves to 50/60 — what a cloner actually
  gets — rather than keeping the number only I can reproduce. (The previously
  published 55/60 came from a hand count; this harness scores the full corpus at
  54/60, so one case of the drop is harness difference, not redaction.)
  Two alternatives were rejected on measurement, not taste. Masking the names
  (陳○○) keeps all 386 and all 239 articles, and makes the 主文 no longer
  verbatim — the rule the entire corpus rests on. Dropping the whole judgment
  costs **19 of the 239 covered articles**, 勞基§24 and 民法§226/§194/§482 among
  them, to remove names that withholding the 主文 removes anyway.
  Worth recording separately: the detector reads the judgment's OWN party block
  rather than surname shapes. A surname heuristic flagged **96** of 386, because
  「連帶給付」 and 「平方公尺」 are surname-shaped; ground truth flags **31**. The
  same discipline as everywhere else here — the data says who the parties are,
  so do not guess.
- **The live demo caught the verifier laundering an invented statute into a real
  one — the fourth 0%→100% blind spot, and the first one a USER-FACING page
  found rather than a mutation.** 2026-08-04, checking the deployed Space's
  引用查核 tab against its own copy: the tab promises two flags on its sample
  (an inflated amount, a typo'd statute name) and delivered one. 公寀大廈管理條例
  第16條 — 公寀 is not a word — came back `exists ✓ 內容 ✓ 時效 ✓`.
  Root cause was a comment that asserted safety instead of measuring it. The
  alias table maps everyday short names onto corpus ids, and the guard was "an
  alias may only point at an id that EXISTS in the corpus, so this can never
  launder an invented statute into a real one." That is true only if the alias
  is an *abbreviation*. Two of them are **suffixes of their own canonical name**
  — 大廈管理條例 ⊂ 公寓大廈管理條例, 道路交通處罰條例 ⊂ 道路交通管理處罰條例 —
  and the lookup was `name_run.endswith(short)`. Anything ending in the alias
  resolved, so misspelling the part the alias omits was invisible: 公寀, 公宇,
  公任 all became 公寓大廈管理條例 and passed all three axes.
  Fix: alias lookup is whole-name equality after the sentence particle, never a
  suffix test. Matching a *full* corpus id as a suffix is kept — to end with the
  whole canonical name you have to spell every character of it, so a typo inside
  cannot survive that test. Aliases still resolve (公寓大廈條例, 大廈管理條例,
  刑法, 勞基法, 社維法, and the 違反/依/及 particles all re-verified).
  New `alias_typo` mutation, one case per suffix-shaped alias, corrupting the
  omitted prefix: **0 → 2/2**, whole corpus **10,437/10,437, 0/2,560 FP**.
  Worth naming: three previous blind spots were found by inventing a harder
  mutation; this one was found by reading the product page and checking whether
  it did what it said. The mutation suite had no case for it because I wrote
  both the guard and the exam from the same wrong assumption.
- **The corpus grew to close a hole the product had just admitted to, and my
  first measurement of it was worthless.** 2026-08-05. The action ladder had
  started telling a hurt rider to claim 強制汽車責任保險 before anything else —
  correct advice, and the statute saying they may claim *regardless of fault*
  (強制汽車責任保險法§7) was not in the corpus at all, so that rung shipped with
  an empty `legal_basis`. Triage was classifying traffic and labor cases the
  corpus could not answer.
  Imported from the official bulk XML: 強制汽車責任保險法 56, 勞工保險條例 104,
  就業服務法 85, 性別平等工作法 50, 個人資料保護法 66 — **361 articles,
  2,561 → 2,922, 11 → 16 statutes** (12 → 17 `statute_id`s counting the police
  routing note). §7 and §25 (payment within ten working days
  of complete documents) now back the insurance rung.
  **The first re-measurement said recall fell 349/356 → 320/356, and it was a lie
  of my own making.** Moving `DB_PATH` to a per-user directory in the packaging
  commit had orphaned the dense index, which lives beside the database: the old
  2,561-key index stayed in the repo's `db/`, the new location had none, and
  `DENSE_RETRIEVAL="auto"` degraded to pure BM25 without a word. A hybrid number
  was being compared against a BM25-only run. Rebuilt at the new location
  (2,922 slices) and re-measured: **348/356 (98%)**. The corpus expansion cost
  exactly ONE case; the other 28 were the missing index.
  The silent degradation is a real regression for anyone who upgrades, not only a
  measurement artefact — the index must be rebuilt after the move, and nothing
  says so at runtime.
  Second self-inflicted error, recorded because the first draft shipped it: the
  labor rung was briefly given 「就業服務法第5條」 as its basis. That article
  prohibits employment discrimination; it is not authority for 勞資爭議調解, and
  勞資爭議處理法 is not in the corpus. Reverted to an empty basis with the reason
  in a comment. A rung naming no article is honest; a rung naming the wrong one
  is the exact failure this project exists to catch.
  **RETRACTED 2026-08-05 — the golden-set half of this entry was noise.** It
  originally read 「strict coverage 73% → 81%, the batch bought 2 cases of strict
  coverage for 1 case of recall」. That 81% was a SINGLE run of a grader sampling
  at temperature 0.2; five runs of identical code span 73.1–80.8%. The corpus
  import cannot be credited with a coverage change at this noise level. What
  survives from the measurement is the recall figure (348/356, deterministic
  retrieval) and tier 27/32 / premise 32/32, which held on every run.
  The five tier misses all lean one way — three said `normal` where `marginal`
  was right, two claimed more confidence than the retrieval had earned. That is
  the BM25-inflation limit named at the top of this file, and more corpus did not
  touch it. Worst single reading is oos-10 (卡債更生): 消費者債務清理條例 is not
  in the corpus, the honesty gate should have refused, and instead top BM25
  105.13 read as `marginal` and the 8B model answered a credit-card debt question
  out of 勞基法§28 積欠工資墊償基金. More articles raise every BM25 score, so an
  ABSOLUTE floor detects out-of-scope worse as the corpus grows — the argument
  for a relative or semantic signal, recorded again with a fresh example.
- **A ten-minute evaluation finished and then threw its own result away.** Same
  day. `python -m legal_agent.evaluation.golden_set` — the command both README
  and CONTRIBUTING tell people to run — completed every case and died in the
  final `print` with `UnicodeEncodeError: 'cp950' codec can't encode character
  '⚠'`. The scorecard carries 「⚠」 and a Windows console is cp950.
  `cli.py` and `run.py` have guarded stdout since the first CLI; none of the five
  eval entry points did. One shared `enable_utf8_stdout()` in
  `evaluation/__init__.py`, wired into all five. Worth naming as its own class of
  incompleteness: the feature worked, the measurement ran, and the user still got
  nothing — a harness that cannot report is not a harness.

- **The ablation was re-run instead of deleted, and the gap turned out WIDER at
  v2 scale.** 2026-08-05. The row had been marked STALE since the corpus grew
  from 11 articles to 2,560; the audit question was whether 278 lines earn their
  place. They do — this is the only measurement that answers 「what does the
  pipeline buy over just asking the model?」. Mutation grades the verifier
  against planted errors; ablation grades the gates against a real model's real
  behaviour.
  llama3.1 over the 32-case golden set, corpus v2 (2,922 articles):
  **bare 34/51 citations flagged (67%), gated 9/190 (5%).** The prediction going
  in was that the gap would NARROW — a bigger corpus should make more of the
  model's memory-cited articles traceable. It widened instead. Retrieval-first
  hands the model verbatim text, so it cites nearly four times as much
  (51 → 190) while the untraceable count barely moves (34 → 9 flagged). The
  honesty tier over the same run: insufficient 3, marginal 2, normal 27.
- **Reading that table exposed a defect in the table itself.** The 「corpus查無」
  column claimed one meaning and carried two. `_run_bare` verifies with `conn=`
  and an empty window, so its baseline is the whole corpus. `gated` inherits
  `run_stage3`'s call — `verify_answer(answer, retrieved, as_of_date,
  corpus_conn=conn)`, no `conn=` — so its baseline is the RETRIEVED WINDOW. That
  is why gated shows 39 「missing」 against only 9 flagged: thirty of them are
  articles that exist in the corpus and simply were not retrieved, which is
  correctly not a hallucination. The two numbers were never comparable and the
  header said they were. Renamed to 「未回溯*」 with the asterisk spelling out the
  differing baselines; `flagged` is the one column measured identically on both
  rows, so it is the one the published figure quotes.

- **The audit's deletion half, and what it did NOT buy.** 2026-08-05, recorded
  here because a file about measurement should say when there is nothing to
  measure. `noise_seed.py` (177 lines) went to `tests/fixtures/noise_corpus.json`
  — its only remaining callers were test fixtures, the shipped corpus having come
  from bulk XML since v2 — and `insert_statute` moved from `cli.py` into
  `data/database.py`, which ended `data/source_ingest.py` importing from the
  interactive CLI: the data layer depending on the presentation layer, and any
  importer of the ingest path dragging argparse and a prompt loop with it.
  Line count: **9,701 → 9,524 → 9,542.** The move ADDED eighteen lines, all of
  them the comment explaining why the function belongs where it now is. Neither
  change moves a published number and neither buys a user a better answer; they
  buy the next reader not having to work out which of two corpus loaders is live,
  and not having to explain why the data layer imports a CLI.

- **The 1,843-line hand-written lexicon is not redundant with the embeddings —
  it is carrying the system, and I had it backwards.** 2026-08-05, the last item
  of the audit. I had called `retrieval/lexicon.py` the most suspicious thing in
  the codebase: 19% of production code doing a job (bridging the everyday →
  statutory vocabulary gap) that dense retrieval with bge-m3 exists to do. The
  instruction was to measure rather than cut, so: four runs over the 168 lived
  sessions, expansion × dense.

  | 口語→法條 expansion | dense (bge-m3) | hit@k |
  |---|---|---|
  | on | on | **348/356 (98%)** |
  | on | off | 320/356 (90%) |
  | off | on | **110/356 (31%)** |
  | off | off | 55/356 (15%) |

  Removing the lexicon costs **238 cases**. Dense alone reaches 110; the lexicon
  alone reaches 320; dense adds 28 on top of it. They are not two implementations
  of one job — the table does the heavy lifting and the embeddings supply a
  margin, and the intuition that they overlap was wrong by a factor of three.
  Two reasons it beats the embedder here, both visible in the code: the table is
  not only a ranking signal, it opens an exact-phrase channel and holds reserved
  seats (`LEXICON_RESERVED_SEATS`), so a matched everyday phrase can pull its
  article into the window outright rather than nudging a score. And Taiwanese
  legal register is far from the everyday phrasing people type — 「加班費」 vs
  「延長工作時間之工資」 — which is exactly the distance a general-purpose
  embedder does not close reliably.
  Kept in full. The line count is the price of the single largest measured
  contribution in the retrieval stack, and this entry exists because the audit
  that was supposed to delete it produced the number that saved it.

- **Expanding the lexicon: two rows shipped, seven measured and reverted.**
  2026-08-05, after the A/B above showed the table is the dominant retrieval
  component. Growing it is the obvious next move, and the obvious next move is
  where this project has repeatedly been wrong, so every row was written against
  a measured miss.
  **The real gap was structural**: the corpus had gained 361 articles
  (強制險 / 勞保 / 就服 / 性平 / 個資) and the table had gained nothing, so five
  statutes had no everyday-phrase route into them at all. Probed first —
  「面試被問結婚生小孩的打算,還說女生不方便」 returned eight 民法 rows and no
  性平法; 「仲介收我服務費還扣護照」 returned 民法 and 消保法, because 扣護照,
  the entire complaint for a migrant worker, matched nothing and 服務費 alone
  reads as an ordinary consumer charge. Two rows fixed both. Recall held at
  **348/356** and the already-working 「懷孕被公司調職減薪」 kept its hit.
  **The other seven rows moved nothing and were reverted.** Written against the
  seven remaining real_recall misses (民法§227 不完全給付, §1166 胎兒繼承,
  §205 利率上限, §514-7 旅遊, §821+§179 共有物, §354 瑕疵擔保, §478 借貸返還),
  they left recall at exactly 348/356. Two were worse than useless: they pulled
  the targeted article in and pushed a DIFFERENT expected article out of the same
  eight-seat window — `unborn-child-inheritance` traded a miss on §1166 for a
  miss on §7, `tour-hotel-downgraded` traded §514-7 for §514-5. Seat
  displacement, net zero, more table to maintain. Not shipped.
  Two process notes, both mine, both caught by the project's own guards. The
  script written to revert those seven rows matched an earlier occurrence of its
  anchor string and deleted **97 rows, 1,150 lines**; recall fell 348 → 177 and
  `git checkout` restored it. And the first draft of the two surviving rows
  paraphrased the statutory side — 「不得以性別或性傾向為由」 for the article's
  「不得因性別或性傾向而有差別待遇」 — which
  `test_every_statutory_term_appears_verbatim_in_the_corpus` rejected. That rule
  is enforced by a test precisely because the person adding a row is the person
  most tempted to approximate.

- **The recall harness could report a BM25-only number and call it hybrid.**
  2026-08-05. Chasing the seven remaining misses, the same command produced
  **348, then 334, then 320** on one machine inside an hour — and 320 is exactly
  the pure-BM25 figure from the lexicon A/B. Ollama was up, the index loaded, a
  test embedding succeeded. The cause is one line: `retriever._dense_fuse` wraps
  the whole dense path in `except Exception: return None`. Graceful degradation
  is CORRECT for the product — a demo with no Ollama must still answer — and
  wrong for a measurement, because it fires PER QUERY when Ollama unloads bge-m3
  under memory pressure, and the harness then publishes a number without saying
  which retriever produced it.
  Fixed by counting, not by changing behaviour: `dense_fallback_count()` /
  `reset_dense_fallbacks()`, and `RecallReport` carries `dense_fallbacks` and
  either says 「dense 全程參與(0 次退回),此數可與已發布數字相比」 or refuses the
  comparison outright. The first run after the fix printed **recall 320/356,
  dense_fallbacks 168/168** — every query had been degrading, invisibly, for the
  whole session.
  What this does and does not invalidate: the published **348/356** was measured
  with dense working, and the four-way A/B separates cleanly (348 hybrid vs 320
  BM25-only, a 28-case delta that matches the fallback story exactly), so those
  figures stand. What was missing is the DISCLOSURE that reproducing them needs a
  live bge-m3 — a reader running the command without one gets 320 and no warning.
  Third instance in this file of bad-ruler-before-wrong-conclusion, and the first
  where the ruler was lying about which system it measured.
  Left undone on purpose: the k-sweep that prompted this (k=8/10/12/16) ran
  through the broken ruler and is discarded, not published. Whether a wider
  window beats k=8 in HYBRID mode remains unmeasured.

- **k=12 beats k=8 by three cases, and is not shipped.** 2026-08-05, re-run
  after `ollama pull bge-m3` (the model had vanished in an Ollama 0.31.1 restart,
  which is what the fallback counter above caught). All four runs verified
  `dense_fallbacks 0/168`, and **k=8 reproduced 348/356 exactly** — the published
  figure holds under the fixed ruler.

  | window | recall | misses |
  |---|---|---|
  | k=8 | 348/356 | 7 |
  | k=10 | 349/356 | 6 |
  | k=12 | **351/356** | **5** |
  | k=16 | 350/356 | 6 |

  Not shipped, for two reasons that are about the measurement, not the result.
  **It trades a measured axis for an unmeasured one.** Precision still has no
  harness here — every number in this file asks whether the right article reached
  the window, never what the reader had to wade through — and k=8→12 puts 50%
  more articles in front of them and into the model's prompt. Buying +3 recall
  with an unpriced precision cost is optimising the metric that exists.
  **And the other published numbers cannot be re-measured right now.** `DEFAULT_K`
  feeds the honesty tier (which reads retrieval scores) and statute coverage;
  re-running the golden set needs llama3.1, which is also gone from this machine.
  A golden-set score from a different model is not comparable to the published
  one, so shipping would mean changing a retrieval parameter while three of the
  five headline numbers go unchecked.
  The finding stands and is reproducible: `k=12` is worth revisiting once
  llama3.1 is back and precision has any harness at all.
  Worth noting for the record: the earlier k-sweep run through the broken ruler
  produced the same SHAPE (320→349→351→350, k=12 best) with a wrong baseline.
  The ordering happened to survive; that is luck, not method, and it is why the
  discarded run stayed discarded.

- **The Tier-1 grader was rolling dice, and I published one roll as a result.**
  2026-08-05. Chasing whether `k=12` should ship, the golden-set baseline would
  not reproduce: identical code, dense verified live (`dense_fallbacks 0/12` on a
  probe before every run), llama3.1 restored — and strict coverage came back 73%
  where 81% was published. Five runs, all listed, none dropped:

  | grader temperature | strict coverage | tier | premise |
  |---|---|---|---|
  | 0.2 | 76.9% (pass 20 / partial 6) | 27/32 | 32/32 |
  | 0.2 | 76.9% (pass 20 / partial 6) | 27/32 | 32/32 |
  | 0.2 | 73.1% (pass 19 / partial 7) | 27/32 | 32/32 |
  | **0.0** | **73.1% (pass 19 / partial 7)** | 27/32 | 32/32 |
  | **0.0** | **73.1% (pass 19 / partial 7)** | 27/32 | 32/32 |

  With the earlier run of the day (73.1%) and the published figure (80.8%), the
  observed spread at temperature 0.2 is **73.1–80.8%, 7.7 points** — larger than
  any effect being chased. At 0.0 the runs are identical.
  The cause is one default. `run_golden_set` takes an injected llm, and the entry
  point built it with `build_runtime_llm()`, whose ollama path defaults to
  temperature 0.2. Coverage is scored as 「expected refs ∈ retrieved ∪ the model's
  own citations」, so the model's sampling lands directly in the score. Meanwhile
  `ollama_llm`'s docstring has read 「graders/checkers pass 0.0 so repeated runs
  measure the model, not the dice」 since the parameter was added. The project
  knew, and applied it everywhere except its Tier-1 grader. Fixed: that entry
  point now builds the grader at 0.0.
  **Two published numbers were wrong and are corrected here and in the README.**
  Strict coverage is **73%**, not 81%. And the corpus-import entry above claimed
  「strict coverage 73% → 81%, the batch bought 2 cases of coverage for 1 case of
  recall」 — retracted, because both endpoints were single samples from a
  7.7-point distribution. That entry's recall figure survives: retrieval is
  deterministic and 348/356 reproduced exactly under the verified ruler.
  What this does NOT touch: tier 27/32 and premise 32/32 were identical on all
  five runs, so those two axes were never sampling-dependent.
  Fourth bad ruler in this file in one day — orphaned dense index, the ablation's
  double-meaning column, dense degrading in silence, and now a grader at
  temperature 0.2. This is the only one that reached the README, and the lesson
  is narrower than 「measure twice」: **before publishing a delta, measure the
  instrument's own spread.** A single run is a sample; I reported one as an
  effect.
  `k=12` remains unresolved and unshipped. It needs a rerun against the now
  deterministic grader — cheap to do, and deliberately not folded into this entry,
  whose subject is the instrument rather than the window.

- **k=12 shipped, decided against a deterministic grader.** 2026-08-05, the
  question the previous three entries were clearing the ground for. With the
  grader pinned at temperature 0 the comparison finally means something, and
  every run was preceded by a probe confirming `dense_fallbacks 0`:

  | | k=8 | k=12 |
  |---|---|---|
  | strict coverage | 73.1% (pass 19 / partial 5+2) | **80.8% (pass 21 / partial 5)** |
  | miss | 0 | 0 |
  | honesty tier | 27/32 | 27/32 |
  | wrong premise | 32/32 | 32/32 |
  | retrieval recall | 348/356 | **351/356** |

  Two golden cases move partial → pass and three recall cases are recovered;
  the two axes that could have gone the wrong way did not move at all. The rule
  set before the run was: coverage up or flat AND tier not down, or it does not
  ship. It cleared both. `DEFAULT_K = 12`.
  **A coincidence worth stating so it does not read as a reversal.** 80.8% is
  the same figure retracted earlier the same day. That one was k=8 winning a
  temperature-0.2 dice roll; this one is k=12 measured deterministically and
  reproducible. Same number, unrelated provenance.
  **The cost that is still unmeasured, and is being accepted knowingly.** The
  window is 50% wider, so the reader — and the model's prompt — receive 50% more
  articles. Precision has no harness in this project; every figure above asks
  whether the right article arrived, never what had to be waded through to reach
  it. Three measured axes improved or held and one unmeasured axis got worse by
  construction. That is the trade, stated rather than hidden, and it is the
  strongest argument in this file for building a precision harness before the
  next window change.

- **The precision harness I said should come first was built second, and it
  reversed the decision it was built to price.** 2026-08-05, last measurement of
  the day. `k=12` shipped earlier on two axes — recall 348→351, strict coverage
  73.1→80.8% — with the cost 「stated rather than hidden」 because nothing in this
  project measured it. `real_recall` now reports the window cost too.

  | | k=8 | k=12 |
  |---|---|---|
  | recall | 348/356 | 351/356 |
  | articles delivered per session | 8.0 | 12.0 |
  | **outside the expectation, per session** | **5.9** | **9.9** |
  | precision floor | 25.9% | 17.4% |

  Expected articles delivered per session barely moves: **2.07 → 2.09**. Across
  168 sessions the wider window recovered **3** expected articles and added
  **672** unexpected ones — about 1:224. Whatever fraction of those are secretly
  relevant (the expectation list is not exhaustive, so this is a floor), k=12 is
  buying bulk, not substance, and a layperson reading verbatim statutes pays for
  every extra row.
  **Reverted to k=8.** README and the tables go back to 348/356 and 73% strict.
  The uncomfortable part is the ordering: I wrote 「a precision harness should come
  before the next window change」 into this file, then made the window change, then
  built the harness, and the harness said no. The rule was right and I applied it
  in the wrong order. It exists now, so the next seat or window change can be
  judged on all three axes instead of the two that flatter it.

- **The honesty tier was wrong in BOTH directions at once, and a 5-case sample
  had been hiding half of it.** 2026-08-06. The known defect was over-confidence:
  five tier misses on the golden set, all leaning the same way, worst of them
  oos-10 (卡債更生) answered out of 勞基法§28. The fix was supposed to be a better
  out-of-scope signal. The first thing measured was the ruler, and the ruler
  changed the diagnosis.

  **Step 0 — build the ruler, because five cases cannot carry a decision.**
  The golden set has 5 out-of-scope cases. Anything tuned to separate 5 cases is
  fitted, and this file retracted a number the day before for exactly that. New
  probe, `evals/honesty_probe_v1.json`, 35 cases in two groups: 20 out-of-scope
  (each governed by a statute verified absent from the corpus's 17 `statute_id`s)
  and 15 in-scope but lexically thin (each expecting an article verified verbatim
  in the corpus). Retrieval-only, no LLM — the tier is decided from scores, so the
  probe is deterministic and reproduces exactly.

  | | before | after |
  |---|---|---|
  | out-of-scope refused (n=20) | **5/20** | **18/20** |
  | in-scope falsely refused (n=15) | 2/15 | 2/15 |
  | honesty tier, golden set | 27/32 | **29/32** |
  | wrong-premise, golden set | 32/32 | 32/32 |
  | strict statute coverage | 73.1% (pass 19 / partial 7 / miss 0) | 73.1% (pass 19 / partial 7 / miss 0) |
  | retrieval recall | 348/356, 5.9 unexpected/session | 348/356, 5.9 unexpected/session |

  All three remaining tier misses are mg-01/02/03 — the marginal-vs-normal axis
  this file already records as not separable by BM25. Nothing was attempted there
  and nothing moved there.

  **What the wider ruler showed that the narrow one could not.** The floor at 70
  was failing to refuse 15 of 20 out-of-scope questions *and* refusing two
  questions the corpus answers — 勞基法§11 資遣 at 39.19 and 個資法§29 at 44.65. A
  false refusal is the worse half: the article was there and the reader was turned
  away. Nobody had measured that direction, because no harness contained a case
  for it. The score ranges are not merely overlapping, they are interchangeable —
  out-of-scope 35.7–503.5 against in-scope 39.2–417.4 — and the single highest
  score in the whole probe is an out-of-scope one (oos-09 本票裁定 at 503.5,
  answered from 民法§473 消費借貸). No constant sits between those.

  **Measured and NOT shipped: the shape of the window instead of its height.**
  Four signals had already lost, and all four read the same thing — how HIGH the
  scores are. The untried idea was the distribution: in-scope retrieval should
  concentrate, out-of-scope should be flat lexical noise. Swept top/mean,
  top/median, top/2nd, top/last, normalised entropy, coefficient of variation,
  score sum, and the k-th score. Best split **25/35**, and that is an in-sample
  optimum against a 20/35 majority baseline. Every range overlaps. Shape is no
  better than height; recorded so the next person does not spend the afternoon.

  **Shipped: a coverage veto, which is not a score at all.**
  `anti_hallucination/coverage.py`. 「Is 票據法 in the corpus」 is a set question,
  and 19 rows answer it: a question naming a body of law we do not carry is
  insufficient no matter what BM25 ran. It only ever refuses — it cannot raise a
  tier, so the change is auditable in one direction. The refusal now names the
  missing statute (「這個問題屬於消費者債務清理條例…」), which golden's own
  expected_action for oos-10 had been asking for.
  Two invariants are tested. Every statute named must be ABSENT from the corpus,
  so importing 消債條例 turns the test red and forces the row out — that is the
  property the absolute floor lacked when it went stale in silence for a week.
  And no trigger may fire on an in-scope question.

  **What it does not do, stated before anyone finds out the hard way.** It refuses
  the absences someone enumerated. It is a closed list, not an out-of-scope
  detector. The 2 probe cases it misses are the ones where the user never names
  the domain — a starved dog, an informal remittance — and describing facts
  without legal vocabulary is exactly how laypeople write. The list will be
  incomplete forever; the honest claim is 「refuses 18 of 20 named absences」, not
  「detects out-of-scope」.

  **How much of the 0-false-fire number is real.** Triggers were PRUNED against
  210 in-scope queries (168 real sessions + 27 golden + 15 probe), so 0/210 is a
  fit, not an estimate. 「本票」「卡債」「健保」「非自願離職」「遺產稅」「農地」
  「停權」 each fired on a genuine in-scope session where the word appeared in
  passing — a 借款 dispute that merely used a 本票 as evidence, a 債權讓與 case
  that opened with 卡債 — and were dropped or narrowed to 「本票裁定」. The
  held-out check is the 386 harvested judgments: 11 fire (2.8%), and all 11 are
  genuinely disputes of the named absent law (裁判費核定 6, 商業事件 2, 執行異議 2,
  消債更生 1), i.e. correct refusals, checked case by case. A fifth bad ruler was
  caught while building that check: the first held-out run scored 0/386 against
  the judgments' `issues` column, which is empty in all 386 rows. It was measuring
  nothing.

  **The floor sweep, measured and NOT shipped.** With the veto carrying
  out-of-scope detection, `INSUFFICIENT_SCORE_THRESHOLD` has almost nothing left
  to do — in the probe it catches exactly one case the veto misses. Sweeping it:
  at 70 (shipped) 18/20 refused and 2/15 falsely refused; at 35, 17/20 and 0/15.
  And any value in 36.51–39.19 gives 18/20 AND 0/15 — a strictly dominant point,
  which is precisely the thing this round exists to stop building. That is a
  constant wedged into a 2.7-point gap between two individual probe cases; it
  would look free and would not survive the next corpus import. The floor stays at
  70 and the two false refusals stay on the books.

  **The ablation was re-run and its delta is NOT publishable, which is itself the
  finding.** Second sample of the same 32 cases: bare **16/24 flagged (67%)**,
  gated **4/208 (2%)**, tier distribution insufficient 5 / marginal 1 / normal 26.
  Published was bare 34/51 (67%), gated 9/190 (5%). The bare arm runs with no
  gates at all, so this change cannot touch it — and it moved from 51 citations
  to 24 on identical code. That is the harness's own spread, never measured
  before, and it is larger than the gated 5%→2% move I would otherwise have
  claimed. What survives: the bare FLAGGED RATE is 67% in both samples, and the
  tier distribution's insufficient 3→5 is this change, since the coverage veto
  short-circuits two more cases before the model runs. The published row stays as
  it is; a second single sample is not an improvement on a first single sample.

- **Two numbers in the table above were stale, and re-running them was the only
  way to know.** Same day, while proving this change moved nothing it should not.
  `mutation` re-runs to **11,904/11,904 caught, 0/2,921 false positives** — the
  published 10,437 / 2,560 was measured before the corpus reached 2,922 articles
  and was never re-run. Same 100% and same 0%, larger denominators. Nothing to do
  with the tier change; it just had not been looked at.
  Also found: `app.py`'s retrieval tab grades the tier WITHOUT `lexicon_hit`,
  which the CLI passes — so the Spaces demo refuses questions the CLI marks
  「僅供參考」. It was written up here as 「two lines and clearly right, moves no
  measured number, so not shipped」. **That was the wrong call, and measuring it
  is what showed why.** The 35 probe questions through the demo's own path (raw
  question text, no intake facts, so BM25 runs on less and scores lower):

  | demo retrieval tab | before | after |
  |---|---|---|
  | out-of-scope refused (n=20) | 20/20 | 18/20 |
  | in-scope falsely refused (n=15) | **8/15** | **3/15** |

  The demo was turning away eight of fifteen questions the corpus answers — four
  times the CLI's rate — and 「moves no measured number」 was only true because
  nobody had pointed a harness at that path. The two out-of-scope cases it stops
  refusing (oos-19 動物虐待, oos-22 地下匯兌) are exactly the two the coverage
  table does not name: they had been refused by the accident of a low score, not
  by knowing anything. Shipped; the demo now grades identically to the CLI.

- **The install was measured instead of assumed, and it was stuck in one place.**
  2026-08-06. Fresh clone from GitHub, clean venv, `LEGAL_AGENT_HOME` pointed at
  an empty directory to simulate a machine that has never run this. Timed:
  clone 1.3s (5.1 MB, 110 tracked files), `pip install .` 29s (3 dependencies, no
  GPU), and the README's five-line snippet run VERBATIM from a directory with no
  checkout — first call 5.0s while the database builds itself, 0.00s after, and
  the corpus comes out complete (2,923 rows, 17 statute_ids, 386 judgments).
  `pip install .[dev] && pytest` is 438 passed in 17s. The library path is two
  commands and needs no model, no key and no network.
  **What was stuck:** `LLM_PROVIDER` was a source constant, and `pip install`
  puts `config.py` in site-packages — so someone without Ollama who ran the CLI
  had a clear error telling them to edit an INSTALLED file. It reads
  `LEGAL_AGENT_PROVIDER` now (same for `OLLAMA_MODEL` and `OLLAMA_HOST`), so the
  free 「manual」 backend is one env var away. Verified end to end on the clean
  venv: `LEGAL_AGENT_PROVIDER=manual legal-agent` starts and runs.
  **What the fresh install proved was already right:** without Ollama the
  harnesses refuse to be misread. `real_recall` reports 320/356 — exactly the
  figure the README advertises for a plain install — with 「168/168 個查詢的
  dense 半邊失敗」 printed beside it, and `honesty_probe` reports 35/35 the same
  way. The guard that four bad rulers bought is doing its job on a machine that
  has never seen this project.
  **What it caught:** the CLI greeting still said 「11 部民生法規」 and the demo
  said 「11 部…2,560 條」 — the first sentence a new user reads, stale since the
  corpus reached 16 statutes and 2,922 articles. Also `SPEC.md`'s scope
  paragraph. Fixed; no measured number moves, which is why this is recorded here.
  Added `AGENTS.md`, because the traps in this file (the corpus living outside
  the repo, dense degrading in silence, the grader's temperature, `DEFAULT_K`
  binding at definition time, the ablation's double-meaning column) are spread
  across 1,300 lines and a coding agent reads none of them before its first run.

- **Two silent failures found by using the thing, not by running a harness.**
  2026-08-06. Every number in this file says the pipeline is trustworthy; none
  of them asks what a person with a legal problem actually receives. So one real
  consultation was walked end to end — a deposit dispute, 「房東說牆壁有污損,要
  扣我兩個月押金四萬八」 — and read as the reader rather than as the author.

  **A blank answer passed every gate.** `config.py`'s own comment invites
  swapping in a better 繁中 model (「要更好的繁中可換 qwen3:latest 等」). Doing it:
  `qwen3:4b` is a thinking model, spends the entire `num_predict` budget of 2,048
  inside `<think>`, and returns an empty string. The pipeline then reported tier
  **normal**, **0 flagged citations**, `sections_ok=False` — and nothing read
  that last flag outside the CLI. The demo would render a green 「充分」 bar over
  an empty page. Fixed: an empty model output is now a failure with its own text
  (`stage3.MODEL_EMPTY_TEXT`), carries `model_output_ok=False` through
  `PipelineResult`, and takes the tier bar in `app.py`. The retrieved articles
  stay attached — the deterministic half of the answer survives a model failure
  and is still worth reading.
  Worth naming as its own class: the flag EXISTED and was correct. Computing a
  signal and never reading it is indistinguishable from not having it.

  **An unsegmented answer lost its guarantees quietly.** A model that answers
  well but ignores the 法律明文/實務見解/分析研判 headings produced
  `sections_ok=False`, which only `run.py` acted on. Everywhere else the reader
  got prose with no way to tell verbatim law from model inference — the exact
  separation Mechanism 4 exists to provide. Fixed by tolerating the shape and
  labelling the gap: the text is kept (throwing away a real answer for being
  shaped wrong serves nobody) with `stage3.UNSEGMENTED_NOTICE` above it, and the
  notice travels with the answer so every caller shows it.

  **What that consultation ALSO showed, and this round did not fix.** The answer
  cited 租賃住宅條例§7 correctly and then said 「押金扣除的部分應與兩個月租金總額
  相等,不得超過」. §7 caps the DEPOSIT at two months' rent; it says nothing about
  how much may be deducted. Every gate passed it, correctly: the article exists,
  and the amount and the direction word both match the article's own 「不得逾二個
  月之租金總額」. The error is which object the cap attaches to — the
  `subject_swap` class that `mutation.py` already documents as provably beyond
  the structural axes, catchable only by the semantic 4th axis, which is off
  because it false-positives 10–30%. So the honest statement of what this system
  does for a real user is narrower than the numbers suggest: it is reliable about
  **which article governs**, and the prose explaining that article is an 8B
  model's, with one measured failure mode nothing in the pipeline can catch.
  The third route to that problem — a better model — is what surfaced the blank
  page above. It is now loud rather than silent, but still blocked: `qwen3` needs
  either a larger generation budget or Ollama's `think: false`, neither of which
  is wired up. Recorded rather than guessed at.

  440 tests. No published number moves: the fixes fire only when the model
  returns nothing or ignores the headings, and llama3.1 does neither.

- **The numbers in prose got a harness, after rotting four times in one day.**
  2026-08-06. Every measured figure here has a runnable harness; the copies of
  those figures pasted into a README badge, the demo's hero line, the CLI
  greeting and the Spaces `short_description` had nothing behind them. In a
  single day that cost four separate rounds: the greeting said 「11 部民生法規」
  and the demo footer 「2,560 條」 long after the corpus reached 16 statutes and
  2,922 articles; the Space advertised 10,437/10,437 after the mutation
  denominators were re-measured; the tests badge and the hero each lagged a
  commit twice. Three of those four were caught by reading the deployed page, not
  by any check.
  `tests/test_published_numbers.py` derives the counts from the live corpus and
  fails when a sentence disagrees. It found its own commit immediately: 443
  collected against prose still saying 440.
  Deliberately narrow. The corpus counts are DERIVED (statutes and articles
  excluding the 行政實務見解 routing note, which the prose describes separately),
  so 「16 部 / 2,922 條」 is checked rather than hardcoded. The test count is
  checked in one direction only — the stated number may not fall behind what
  pytest collected — because a subset run collects fewer and failing then would
  punish `pytest tests/test_one.py`. Figures whose harness needs a model
  (mutation, golden, the tier pair) are NOT pinned here: a test that has to run
  llama3.1 to check a README line is worse than the rot.
  **Then the guard turned out to be half-applied.** It pinned the README badge
  and the demo hero and missed the two lines a newcomer reads FIRST: the setup
  blocks in `AGENTS.md` and `CONTRIBUTING.md` still said 438 and 433 tests
  against a suite of 468. Both now go through the same check, matched on the
  `python -m pytest -q` command rather than on the digits — `DEPLOY_SPACES.md`
  records 「Both were stale on 2026-08-06 (10,437/10,437 and 433 tests)」 as
  HISTORY, and a looser pattern would have quietly rewritten the record of the
  mistake. Verified by breaking it: setting the AGENTS.md count to 999 fails
  `test_the_stated_test_counts_agree`, which is trap 7 in AGENTS.md applied to
  the guard itself.

- **The reference judgment was never asked whether it is about the reader's
  problem — it is, 51/88 times.** 2026-08-06. `related_judgments` JOINs on
  articles the pipeline already retrieved, so a case cannot appear unless it
  cites the same law: relevance to an ARTICLE, guaranteed by code. Relevance to
  the reader's DISPUTE had one favourable anecdote and no number, and this table
  said so — 「counted, never scored」.
  `evaluation/judgment_relevance.py` scores it over the same 168 lived problems,
  with `focus` set to the session's own expected articles that reached the
  window, i.e. the path stage3 takes when the model cites the right law and
  verification clears it. Measuring under a CORRECT answer is what isolates this
  layer from model quality.
  **Why 案由.** `judgments.full_text` holds the header and the 主文 only — no
  facts, no reasoning. So the block a reader sees offers four things: the 案由,
  the court and case number, the sum ordered paid, and the shared article. The
  案由 is the only one that says what the case was ABOUT. Grading it is not a
  proxy of convenience; it grades the one field the reader has to judge by.
  **No hand labels, on purpose.** Both sides are derived — the session's family
  from its own `expected_statutes` through 民法's 編/章/節 ranges (a legal fact),
  the judgment's from keywords in the court's own 案由. The author of the system
  grading his own system on labels he wrote would be worth nothing; anyone can
  re-derive both tables.
  **146/168** sessions carry a judgment. The other 22 are honest silence: 18 have
  one available and lose it to `focus`, because no harvested judgment cites the
  article the answer actually stands on — the layer would rather show nothing
  than something adjacent.
  **51/88 (58%)** of the scorable ones are the same kind of dispute.
  **58/146 are unscorable** because the 案由 is 「損害賠償」 or 「損害賠償等」, which
  names no dispute at all. Those are reported, not scored: counting them as hits
  would flatter the number and counting them as misses would blame the layer for
  the courts' filing vocabulary. Same-family is also a NECESSARY, not sufficient,
  condition — two 租賃 cases can still be different situations — so 58% is a
  CEILING on usefulness, the way `real_recall.precision` is a floor.
  **The split by family says the cause is the corpus, not the ranking.** Perfect
  where the harvest is dense — 監護 6/6, 家暴 5/5, 侵權 5/5, 婚姻 4/4, 僱傭 3/3,
  租賃 3/3 — and bad where it is thin: 繼承 3/10, 委任 4/8, 共有 2/6, 寄託 1/4,
  扶養 2/5, and 0/2 each for 保證, 買賣, 贈與, 消費. This is the same finding as
  「judgment coverage is thin exactly where it matters」 above, now per family.
  One mechanism is worth naming because it is systematic rather than random:
  **three of the five 扶養 sessions are shown a car crash.** Taiwanese traffic
  judgments compute dependants' support and therefore cite 民法§1114/§1115/§1117
  heavily, so any 扶養 question joins straight onto them. (An earlier claim in
  this file that a 押金 session pulled three car-crash judgments was wrong and
  was retracted — it was an artifact of a stub LLM. The mechanism is real; the
  session it was pinned to was not.)
  **What the taxonomy cannot settle.** A 保證 question shown 清償借款 counts as a
  miss, but suing a guarantor IS filed as 清償借款; likewise 繼承 → 不動產所有權
  移轉登記等. Both are defensible either way, and both were left as measured
  rather than reclassified, because tuning the map until the number improves is
  the thing CONTRIBUTING forbids. The map was corrected exactly twice, for rule
  bugs rather than outcomes: cross-cutting articles (民法§273 連帶債務 and the
  like) are rules that apply inside a loan, a sale or a repair job alike, so they
  identify no dispute and are excluded on both sides — grading by them scored
  清償借款, the right case, as a miss; and the EARLIEST keyword in a 案由 wins
  rather than the first in the table, because a court writes the claim it decided
  first and appends the rest after 「等(含…)」, so 「離婚等(含未成年子女親權酌定、
  扶養費等)」 is a 婚姻 case that also settled support.
  464 tests. The published `50/60 first judgments state an award` is unaffected;
  on all 168 it reads 93/146.

- **The 主文 outcome, read one sentence at a time — and the whole-block ruler it
  replaces measured at 58–72% false positives, all in the same direction.**
  2026-08-15. Reserving a seat for a judgment that states no sum (below) stops
  the block implying nobody lost, but it cannot say who did. Saying that needs a
  ruler, and the obvious ruler — test the whole 主文 for 「駁回」 — is far worse
  than it looks. Measured on the shipped 386:
  「之訴駁回」 anywhere calls **121/386** a loss and is wrong on **87 of them
  (71.9%)**; the broader 「駁回」 anywhere calls **200/386** a loss and is wrong on
  **115 (57.5%)**. **Every single disagreement runs the same way — a win or a
  part-win read as a loss** (83 and 101 of them are 一部勝訴一部敗訴). For a block
  whose purpose is to tell a reader that someone lost, that is the worst
  available direction of error.
  **The cause is a LEVEL error, not a shortage of markers.** `award_amounts` has
  always decided sentence by sentence; the outcome was testing the block. A 主文
  is a list of operative orders and the case result is a function of that list.
  `judgment_text.outcome()` now splits with the SAME `_sentences()`, classifies
  each sentence, and folds them: relief (確認 / 准 / 不得 / an 應-order against
  the other side) against refusal (a 駁回 aimed at the mover), with costs,
  clerical corrections and conditional 補正 orders excluded because they decide
  nothing. Distribution over the 386: **granted 119 (30.8%), partly 101 (26.2%),
  denied 85 (22.0%), denied_procedurally 1, unreadable 80 (20.7%)** — the last
  splitting into 35 judgments with no 主文 heading at all and 45 procedural or
  非訟 裁定 (裁判費核定, 移送管轄, 輔助宣告). Those stay unreadable on purpose:
  VERBATIM or nothing applies to verdicts too.
  **An outcome that does not name WHO is misleading on its own.** An appellate
  主文 is relative to position — 「被告應給付原告」 and 「上訴人應給付被上訴人」 are
  the same grammar pointing opposite ways — so `Outcome` carries the mover and
  respondent as the 主文 itself names them, and `describe()` refuses to render a
  verdict without them.
  **Eight regression seeds, each a case the whole-block ruler gets wrong**, all
  pinned against the shipped corpus in `tests/test_judgment_outcome.py`: the
  先位/備位 split (`MLDV,114,家繼訴,56`), two outright appellate wins written as
  「原判決廢棄。被上訴人在第一審之訴駁回」 (`TPHV,114,上,908`, `TPHV,114,上易,270`),
  two injunctions granted beside a refused 緊急處置 (`IPCV,115,商暫,4/5`), two
  partial appeals whose amount sits inside the 廢棄 clause and whose partial loss
  is written 「其餘上訴駁回」 (`TCDV,114,簡上,160`, `CTDV,115,簡上,4`), and a
  procedural 「再審之訴駁回」 (`SCDV,114,再易,12`). 8/8.
  **What is NOT claimed.** 8/8 on the seeds and 0 suspicious calls in an audit of
  all 204 granted/denied verdicts is not a validated recall — there is no
  hand-labelled outcome set for the 386, so the classifier's own error rate is
  unmeasured above the seeds. The published number here is the OLD ruler's false
  positive rate, which needs no such set: a judgment ordering 被告應給付原告 X 元
  is not a loss, and that can be checked by reading it. The classifier is not
  wired into the rendered block for the same reason — see the seat reservation
  below, which needs no outcome label at all.

- **The judgment block was sorting the losses out of sight, and now keeps one
  seat for them.** 2026-08-15. `related_judgments` widens to `limit * 3` = 9
  candidates and then re-sorts them all by 「states an award」 — `not ()` is True,
  `not (260000,)` is False, and False sorts first. `judgment_text.award_amounts`
  returns an empty list for a 主文 reading 原告之訴駁回. Multiply the two: as soon
  as three of the nine parse a sum, every seat a reader sees carries one, and the
  code has actively hidden the cases that ordered nothing.
  Measured over the 168 real sessions, 146 of which are shown judgments:
  **102/146 sessions saw at least one judgment with no stated sum; with the last
  of the three seats reserved for one, 129/146 do.** The remaining 17 have no
  such judgment among their nine candidates, and the seat is then filled by the
  ordinary rule rather than left blank — a missing row says nothing a reader can
  check. `dense_fallbacks` 0.
  **Both published figures are untouched, by construction.** 「First judgment
  states a sum」 stays **93/146** and 案由 same-family stays **51/88 (58%)**,
  because the reservation only ever touches seat 3 and both figures are defined
  on seat 1. Seat 1 was the alternative and would have broken the first figure by
  definition. It is also why this is compatible with 「making the award sort a
  tiebreak」 being rejected below: the sort's primary key is not touched.
  **What it deliberately does NOT do.** The seat carries no win/loss label. Its
  note says 「此判決主文未載明給付金額」 and prints the 主文 verbatim beside it — a
  fact about the text the reader can check, not a claim about the case. A
  classifier would need a ruler that has itself been graded, and the obvious
  whole-block substring ruler already measures ~12% false positives on the
  shipped 386, every one of them labelling a win as a loss. The price of staying
  cheap is stated plainly: this cannot tell a reader 「N people lost under these
  same articles」. It can only stop the block from implying that nobody did.

- **A reasoning model was losing its whole answer inside `<think>`, and the fix
  proves the Tier-1 numbers are model-independent.** 2026-08-06. This file
  carried qwen3 as blocked: 「needs either a larger generation budget or Ollama's
  `think: false`, neither of which is wired up」. Measured, that was too
  generous — it needs BOTH. qwen3:4b at the shipped 2 048 cap returns
  `response` 0 chars, `thinking` 2 564 chars, `done_reason` 「length」; setting
  `think: false` alone still ends at 「length」, truncated, opening with monologue
  instead of the 法律明文 heading. `think: false` AND 4 096 finishes at 「stop」 in
  44 s with all three sections.
  Wired as a retry keyed on the SYMPTOM, not on a list of model names — the next
  thinking model will not be on that list. An empty answer WITH thinking text is
  the signature; the retry disables thinking and doubles the cap. A server or
  model that rejects `think` leaves the empty answer alone, which stage3 now
  reports loudly rather than rendering blank. `LEGAL_AGENT_OLLAMA_THINK=false`
  skips the wasted first generation for anyone who knows their model thinks.
  **Then the comparison, both models on the same code, same golden_v2, k=8,
  temperature 0.** qwen3:4b: 法條涵蓋 pass 19 / partial 7 / miss 0, 73% strict,
  誠實分級 29/32, 前提偵測 32/32. llama3.1:8B: **identical, every figure**. That
  is not a coincidence to be explained away — statute coverage, the tier and the
  premise flag are decided by retrieval and by code, so the model cannot move
  them, and swapping an 8B for a 4B reasoning model is the empirical version of
  the claim this project has been making in prose.
  What did differ is unscored. qwen3 emits **154,854 characters against 31,626**
  — five times the text for the same 32 cases — and its extra named citations
  pull twice as many reference judgments (**20/32 with 15 stating an award,
  against 10/32 with 6**). That is the model citing more, not the judgment layer
  improving: `focus` deliberately attaches judgments to what the answer STANDS
  on, so a model that names more articles widens the join. Whether that helps a
  reader is exactly what 51/88 above says it cannot be assumed.
  Default stays llama3.1. The wiring ships anyway, because what moved is a
  user-facing failure rather than a score: a reader running a reasoning model got
  a fully-retrieved, fully-verified page with nothing written on it, and now gets
  32/32 complete three-section answers. 468 tests.

- **The semantic axis's exam had three questions, and the axis could fail
  invisibly.** 2026-08-06, working the §7 `subject_swap` debt. Two things turned
  up before any checker could be improved.
  **The exam.** `mutation.py` grades the 4th axis on `_SUBJECT_SWAPS` — **three**
  hand-written sentences, against ~2,921 controls. All three are ACTOR swaps
  (承租人/土地所有人, 房東/住戶, 環境主管機關). None is the shape that actually
  reached a reader: a numeric cap attached to the wrong OBJECT. Tuning the
  checker against n=3 would have been tuning against noise, so the exam was
  widened first — six new cases covering both shapes, starting with the real §7
  failure (租賃住宅條例§7 caps the 押金; the answer said it caps the deduction),
  plus 民法§432, 消保法§19, 勞基法§24, 公寓大廈§10 and 家暴法§14.
  Every one was run through `verify_answer` with the semantic axis OFF first and
  had to come back `flagged=False`. All six do — which is itself the finding
  worth stating: **six plainly wrong statements of who owes what, and the
  pure-code verifier passes every one.** A case the structural axes already
  catch would have credited the semantic axis with work it never did.
  **The instrument.** The first run of the widened exam returned 0/9 caught and
  0/120 false positives — a perfect false-positive record. Ollama was down. Not
  one of the 129 calls reached a model: `semantic_consistent` returns
  `(True, "")` on every failure path, which is the right call (a checker that
  cries wolf over its own infrastructure gets switched off) with a sharp edge —
  **the failure direction is the flattering one.** This is trap 2 (dense
  retrieval fails silently) in a second component, and trap 7 (a harness reading
  a field that is not there) in a second form.
  `semantic_unreached_count()` now counts every verdict the model did not
  render, `mutation --semantic` refuses to present a clean scorecard when it is
  non-zero, and six tests pin the distinction between an outage and a verdict.
  No published number moves — the axis is still off by default — but any past
  4th-axis measurement was taken with no way to prove the model participated,
  and that is now checkable. 474 tests.

  **Then the widened exam ran on a live model, and it settles the §7 debt.**
  `mutation --semantic`, llama3.1, `semantic_unreached` 0 — so the model
  rendered every verdict in this number:

  | | |
  |---|---|
  | catch, all classes | 11,913/11,913 (100%) |
  | of which `subject_swap` | **9/9** |
  | false positives on correct citations | **1,259/2,921 (43%)** |

  So the axis is not weak — it catches every planted swap including the §7
  object-of-a-cap shape. It is unusable: it calls **43% of correct citations
  wrong**, against 0/2,921 for the pure-code verifier. The published 「10–30%」
  was optimistic and is superseded.
  **The false positives are not a scoping problem.** Concentrating the axis on
  the everyday statutes would not rescue it — 民法 alone accounts for 544, and
  every statute in the corpus contributes: 勞基法 50, 家暴法 36, 個資法 27,
  租賃住宅條例 24, 公寓大廈 22, 消保法 21. Reading them, the model objects to
  controls that quote the article's own figure back at it (「主張把罰金金額改為
  700000元,與條文明顯不同」 — the article says 七十萬元) and treats a sentencing
  range as a period (「相關期間為10年」 out of 「十年以下有期徒刑」). The
  structural amount axis handles both correctly, at 2,921/2,921.
  **So §7 closes as a measured limit rather than a fix.** The error class is
  catchable, by exactly one mechanism, and that mechanism costs 43% false
  alarms. Both cheaper routes were measured and lost: a second inverted question
  requiring both to agree moved a 120-control sample from 38% to 31% (the two
  framings agree on the false alarms, so it is not noise), and the model swap
  measured earlier the same day scores identically on every graded axis. The
  honest statement of what this system does for a reader is unchanged and now
  fully bounded: reliable about **which article governs — on the cases this
  project wrote**, with the prose about that article carrying one failure mode
  that nothing in the pipeline can catch without making two of every five
  correct citations look wrong. The scope clause is not hedging. §7 measures the
  same claim on disputes labelled by the deciding authority instead of by us,
  and it drops to 7/27.

---

## Archive A — measured results as of 2026-07-10

Environment: local, zero paid API. Models via Ollama on an RTX 4060 (8 GB);
corpus = the 11-entry hand-verified 住宅噪音 reference corpus; golden set =
[`golden_noise_v1.json`](golden_noise_v1.json) (25 cases).

**Closed-world caveat** (applies to every table): "unverifiable / corpus 查無"
means *not traceable to this corpus* — which is exactly the promise the system
makes ("every citation must be verifiable back to the corpus") — it does NOT
claim the statute doesn't exist in the real world.

---

### A0. Corpus v2 (2026-07-18) — 11 → 2 561 articles, and what the numbers did

The corpus grew 233× in one day: 11 statutes of everyday law (民法, 中華民國
刑法, 消保法, 勞基法, 道交條例, 公寓大廈條例, 噪音管制法, 社維法, 租賃住宅
條例, 家暴法, 社維法處理辦法) imported from the official 全國法規資料庫 bulk
XML via `data/moj_xml.py`. Importer verified against a golden sample: all 9
articles previously typed in by hand match the XML text **character for
character**. Two official-data traps were caught live and fixed: the
`生效日期=9999-12-31` sentinel ("amendment not yet in force" — taken literally
it date-excludes 民法 entirely), and duplicate current slices from the old
hand-typed seed (plus seven test fixtures that wrote to the LIVE DB — now
isolated; tests never touch it again).

What re-measurement honestly showed:

- **The out-of-scope cases stopped being out of scope — that's the point.**
  oos-02 (遺產), oos-03 (網購), oos-04 (欠薪) now retrieve real 民法/消保法/
  勞基法 articles. Golden-set expectations written for an 11-article corpus
  are obsolete; golden v2 with re-scoped expectations is the next task.
- **BM25 magnitudes rescaled** (top scores 20–84 vs the old 4–42): the
  calibrated insufficient floor no longer separates anything → re-calibrate
  against golden v2.
- **Noise-scenario coverage diluted** (pass 11 → 4 of 19 scorable): recall on
  sparse fact wording degrades in a 2 561-article corpus — hybrid (dense)
  retrieval is no longer a roadmap nicety; it is measured necessity.
- **The mutation exam adapted to scale**: planted "nonexistent" articles are
  now verified absent before planting (in a 1 439-article 民法, 第X+500條 can
  be real), and direction flips only target amounts whose direction is
  unambiguous (range wording carries both directions legitimately). Full-corpus
  run: **9 833/9 833 mutations caught (100%), 0/2 560 false positives.**
- **Re-verification (2026-07-21): the number above briefly went stale, and the
  reason is worth keeping.** A fresh full re-run measured 9 836/9 837 — one
  out_of_force miss. Cause: the hand-era noise-routing proposal and the
  official-XML import both shipped 違反社會秩序維護法案件處理辦法第11條 as an
  OPEN slice (effective_from 1992-02-21 and 2020-11-16, both effective_to
  NULL, content byte-identical) — so "the day before the current slice" was
  legitimately covered by the older row, and the verifier's no-flag was
  *correct on bad data*. Three fixes shipped: (1) the 1992 slice is capped at
  2020-11-16 in the proposal file — the corpus's first true historical slice;
  the cap is a record seam, not a legal amendment (the article was never
  amended), documented in its `_review`; (2) `source_ingest` now refuses a
  second open slice per article (fail-fast ValueError, checked in-file and
  against the DB); (3) the mutation harness dates out_of_force citations
  before the article's *earliest* slice, not the current one — the exam had
  silently assumed single-version articles. DB rebuilt from scratch via the
  README quickstart: **9 833/9 833 caught, 0/2 560 false positives**, now on
  a corpus that actually contains a historical slice.
- **period_swap (2026-07-21): the demo found this blind spot before the exam
  did.** On 07-19 a demo sample had to *drop* a 七日→十四日 defect because the
  content pass compared only monetary amounts — an advertised catch that did
  not exist. The new mutation type plants a same-unit period swap on every
  article that states a period (fake value verified absent for that unit):
  **0/602 caught before the fix.** The fix mirrors the direction-word rule —
  flag only when BOTH sides state a value in the SAME unit (日/天, 週/星期,
  個月, 年, 小時 normalized; bare 「月」 excluded — 「三月」 is a date), so a
  paraphrase into a unit the article never states is left alone. Controls now
  carry a real period wherever the article states one, so the 0-FP bar
  exercises the new pass. After: **602/602; full run 10 435/10 435 (100%),
  0/2 560 false positives.** Known limits, unclaimed: cross-unit swaps
  (七日→七年 where the article has no 年-value), 半年/半個月 (no numeral),
  and a restatement INTO a unit the article does state (一個月 as 三十日 next
  to a 七日 rule) would flag — 分析研判 should paraphrase in the article's
  own units.
- **The user's ask joins the retrieval query (2026-07-21): coverage 88% → 96%.**
  Diagnosis of the four cases missing 民法§184/§195: the tort articles share
  ZERO tokens with distilled fact fields (噪音種類/時段/證據), so they are
  dense-only candidates — and measured, even at dense rank 2 (oos-05, expanded
  query) RRF's dual-list bonus buries a single-list item below the top-8, while
  §195 elsewhere sat at dense 61–108, outside the top-50 fusion cut. The real
  root cause sat a layer higher: the fact fields DROP the user's remedy
  vocabulary — 「可以請求精神慰撫金嗎?」 shares 請求/賠償 tokens with §195
  verbatim, and 「賠我五十萬精神賠償」 with §184/§195 — words the user
  actually typed. Fix: `run_stage3` appends `user_text` to both retrieval
  halves (containment-checked; generic flow already seeds `problem` with it).
  The inclusion rule stays exactly what it claims to be: the user's own words.
  Stub-LLM A/B (same harness): pass 13→16, miss 3→1, zero regressions.
  Real-LLM run: pass 17 / partial 8 / miss 1 — **96% pass+partial (65%
  strict)**, honesty tier 23/30 and premise 30/30 untouched. Remaining honest
  misses: §184 where the ask has no 賠償-family token (in-06 asks 慰撫金 →
  §195 only; oos-01/05 ask 怎麼辦/不理賠), wp-03 民法§793, and the
  noise-fixture MISS case was re-engineered to zero lexical overlap so the
  miss-scoring path no longer depends on the gap this fix closed. Harness
  robustness, same day: one case decoded 7 472 tokens at 42 t/s straight into
  the 180 s client timeout — `ollama_llm` now caps generation
  (num_predict=2048; a well-formed answer is < 1 500 tokens).
- **Dense reserved seats (2026-07-21): the embedder knew, the fusion buried
  it — strict 62% → 69%.** Per-case diagnosis of the remaining partials found
  six of nine missing articles already in the DENSE top-10 (§1141 at 3,
  噪管§6 at 4, §793 at 5, §184 at 2) yet fused past rank 24: RRF's
  dual-presence bonus lets dozens of lexically-matched articles collect BOTH
  reciprocal ranks and swamp any single-list item. Fix: the dense channel's
  top-N get guaranteed seats at the TAIL of the top-k window (BM25 scores
  untouched; promoted dense-only items carry 0.0, so the honesty floor cannot
  move; the point-in-time filter still rules — a slice not in force is never
  promoted). N was SWEPT, not guessed (stub-LLM harness, pass/partial/miss):
  N=0 16/9/1 · N=2 17/8/1 · **N=3 18/7/1** · N=4 17/7/2 · N=5 17/8/1 — at
  N≥4 the displaced fused tail costs mg-02 its expected §16, the cautionary
  trade the sweep exists to catch. Real-LLM harness confirms: pass 18 /
  partial 7 / miss 1 — 96% pass+partial, **69% strict**, tier 23/30, premise
  30/30. Honest remainders: 噪管§3 (dense 31, definitions article), 噪管§9
  (dense 8), 噪管§6 for ts-01 (dense 4 but outside its query's top-3),
  勞基§22 (dense 9) / §84-1 (dense 30), §184 for water-leak (dense 148 — the
  one true vocabulary gap left), wp-03 §793 (dense 5, outside top-3; N=5
  would fix it but kills mg-02).

**Golden set v2 (`evals/golden_v2.json`, 30 cases) re-baselines the suite.**
The five old out-of-scope cases are re-scoped as in-scope with real expected
statutes (their topics are now covered — the point of the pivot), three new
genuinely-uncovered domains join (商標/公司/稅務), and two new everyday
in-scope cases (租屋押金, 責任制加班費). Deterministic re-run (fake LLM,
retrieval+tier only):

- **The pain-point route works**: all five re-scoped cases retrieve their law
  at `normal` tier — 押金 case top-BM25 94.2 hits 租賃住宅條例§7, 繼承 67.4
  hits 民法§1138/1141, 網購 43.2 hits 消保法§19.
- **Honest negative: absolute BM25 cannot detect out-of-scope at this corpus
  size.** The three new oos cases score 21.1–32.9 — interleaved with true
  in-scope cases (weakest: 19.1). In 2 561 articles, every query finds a
  generic-token match (民法§184 sticks to everything). The insufficient floor
  stays at 6.0 (still guards pure lexical noise; no data supports another
  constant) and out-of-scope detection moves to the hybrid/semantic-signal
  roadmap item — measured, not assumed.
- Tier 23/30 (77%): misses = the 3 new oos (above) + the 4 marginal probes
  (unchanged verdict: not separable by any BM25 cutoff).
- Coverage pass 5 / partial 10 / miss 11 of 26 scorable — recall dilution is
  now the single largest measured gap → hybrid retrieval.

**Hybrid retrieval groundwork (2026-07-18, `retrieval/dense.py`).** Live
simulation supplied the smoking gun for BM25's vocabulary gap: the overtime
query 「雇主不給加班費」 cannot reach 勞基法§24, whose text says
「延長工作時間之工資」 — zero lexical overlap, BM25 rank >20 (top-5 even
surfaced 刑法§201). Dense embeddings via local Ollama (zero new Python deps,
optional like every model here), embedding model chosen by exam, not fashion:

| 4-query everyday benchmark (target-article rank) | bm25 | nomic-embed-text | bge-m3 dense | hybrid (RRF) |
|---|---|---|---|---|
| 網購退貨 → 消保§19 | none | 925 | **1** | **1** |
| 遺產怎麼分 → 民法§1138 | 20 | 1524 | **1** | 5 |
| 押金不還 → 租賃條例§7 | 1 | 28 | 2 | **1** |
| 加班費 → 勞基§24 | none | 408 | 37 | 58 |

nomic-embed-text failed Traditional-Chinese legal text outright (even with its
task prefixes) and was rejected; **bge-m3** is the shipped default. RRF fusion
(rank-based, no tuned weights) keeps BM25's exact-term strength while dense
closes the paraphrase gap. The 加班費 row shows honest headroom: statutory
phrasing sits far from everyday wording even for bge-m3.

**Wired into the pipeline (config `DENSE_RETRIEVAL="auto"`).** Contract: RRF
only re-orders and widens candidates; BM25 scores are untouched, so the
honesty floor keeps its meaning, and a dense-only candidate carries its honest
lexical score of 0.0. Any failure (flag off, index unbuilt, Ollama down, CI)
silently degrades to pure BM25 — tests pin both paths. Golden v2 re-measured
with the live hybrid: coverage **miss 11 → 9, partial 10 → 12** (pass+partial
58% → 65% of 26 scorable), tier unchanged at 23/30 — recall improved, honesty
untouched, exactly as designed. Rebuild the index after corpus changes with
`python -m legal_agent.retrieval.dense`.

**Dense-query focusing (generic flow only).** Process facts are semantic
noise for the dense half: 勞基§24 ranks **34** against the full fact string
but **5** against problem+goal alone. Stage 3 now sends the focused
problem+goal text to the dense half for GENERIC cases while BM25 keeps the
full fact string. Scenario checklists deliberately don't focus — measured
first: focusing noise-case fields dropped golden coverage (「報過警」/
「管委會」 are content there, not process). Net golden effect: generic cases
gain, noise cases unchanged.

**口語→法條語彙 expansion (2026-07-19, `retrieval/lexicon.py`) — the frontier
moved.** People name the HARM (「失眠」「精神困擾」「網購退貨」); statutes name
the LEGAL CONCEPT (「不法侵害他人之身體、健康」「非財產上之損害」「通訊交易…
解除契約」). A hand-curated table appends the statutory wording when everyday
triggers appear; every statutory term is copied verbatim from a corpus article
(pinned by a test that greps the live corpus), and expansion only ever ADDS.

| golden v2, k=8 | pass | partial | miss | pass+partial | tier |
|---|---|---|---|---|---|
| expansion off | 5 | 12 | 9 | 65% | 23/30 |
| **expansion on** | **13** | 10 | **3** | **88%** | 23/30 |

Honesty is untouched (tier identical; out-of-scope cases carry no triggers, so
they are never widened).

**The false positive that shaped the design.** A first version fed expanded
terms into the lexical-overlap INCLUSION test as well. It scored higher — and
was wrong: 「同一順序之繼承人」, added for an inheritance question, collided
with 民法§195's 「不得讓與或繼承」 and turned an out-of-scope question into a
confident answer. Fixed by splitting the two roles: **the user's own words
decide match / no-match, expanded terms only decide ORDER.** The measured gain
survived the fix (96% → 88%, still up from 65%) and the out-of-scope guard came
back.

**Correction to a previously published number.** This session's earlier claim
that "k=8 was measured and does not help" was produced by a broken experiment:
`retrieve_scored`'s `k=DEFAULT_K` default binds at definition time, so
reassigning the module constant changed nothing. Re-run properly, k moves
partial→pass (k=5: 11 pass, k=8: 13, k=12: 14) at a flat 88% pass+partial;
`DEFAULT_K` is now **8** — everyday problems legitimately span several statutes,
and a 5-slot window truncated correct answers.

**A flag that lied, found by simulation.** Running a real noise-damages
consultation through llama3.1, the verifier flagged 社維§72 with 「corpus
查無此法源」 — but that article is in the corpus; it simply was not retrieved
that turn. Retrieval-first is unchanged (an un-retrieved citation is still
`exists=False` and still flagged — the model went outside its sources), but
the reason now distinguishes the two cases: **「未出現在本次檢索結果中 — 模型
可能憑記憶補充。該條文確實存在於資料庫」** vs 「corpus 查無此法源」 for a truly
fabricated one. Without a corpus connection the verifier says the weaker thing,
because it genuinely cannot tell. Mutation suite unaffected (9 833/9 833, 0 FP).

Remaining honest misses: 民法§184/§195 in a pure-noise fact pattern (the
generic tort articles stay outranked by the on-point noise statutes), and
ts-01, which asks about a **2024** dispute while the corpus holds only the
current 噪音管制法 slice (effective 2025-12-26) — the point-in-time filter
correctly refuses it. That is a corpus-history gap, not a retrieval bug.

Numbers in the sections below predate corpus v2 (measured on the 11-article
corpus) and are kept as the baseline.

### A1. Verifier mutation test — catch rate on planted errors

Deterministic (no LLM). Answers are generated from real corpus rows with one
planted defect each; the verifier must flag every defect and none of the
correct controls. `python -m legal_agent.evaluation.mutation`

| type | planted | caught | note |
|---|---|---|---|
| control (correct citation + correct amount) | 10 | — | **0 false positives** |
| nonexistent_article (第X+500條) | 10 | 10 | exists-axis |
| ghost_suffix (真條號+之99) | 10 | 10 | exists-axis |
| wrong_amount (×10 金額) | 10 | 10 | content-match axis |
| direction_flip (同金額,以下↔以上) | 2 | 2 | content-match axis |
| out_of_force (as-of 生效日前一天) | 10 | 10 | in-force axis |
| fake_statute (虛構法名) | 1 | 1 | exists-axis |
| **total mutations** | **43** | **43 (100%)** | false-positive rate **0%** |

Two of these rows are the harness catching the verifier's own blind spots —
each started at 0% and forced a fix:

- `direction_flip` (2026-07-15): **0/2** at first — the v1 content match
  compared amounts only, so 「一萬元**以下**」 cited as 「一萬元**以上**」
  sailed through. Fix: a conservative direction check that fires only when
  BOTH the claim and the verbatim article bind a direction word to the SAME
  amount (paraphrases stay unflagged).
- `ghost_suffix` (2026-07-16): **0/10** at first — the citation regex silently
  dropped the 之X suffix, laundering an invented 「民法第793條**之99**」 into
  the real 第793條 (LLMs love inventing 之X sub-articles). Fix: the suffix now
  survives into `article_no`, normalized to the corpus form
  (「第800條之1」≡「第800-1條」), so a ghost variant can only fail lookup —
  never collapse into its real parent.

Both fixes restored 100% with false positives still 0.

**The semantic class now has an axis (2026-07-17, optional).** Subject swaps
(「土地所有人」 cited as 「承租人」) pass every lexical check by construction —
that class needs a model, not more regex. `verify_answer(...,
semantic_llm=...)` adds an injected-LLM 4th axis: off by default (the
structural verifier stays pure code), conservative on every failure path
(unreachable model / garbage output → NOT flagged), and spent only on
citations the structural axes already passed. The harness grades the checker
itself: `python -m legal_agent.evaluation.mutation --semantic` wires a local
Ollama and plants 3 hand-written subject_swap cases (plus the 10 controls,
which must still produce zero false positives). With an injected reference
model the full suite is **46/46, 0 FP**.

**Measured with real local models (2026-07-17/18, temperature pinned to 0 —
two identical back-to-back runs confirm determinism). None passes both bars;
that is the finding.**

| model (`--model`) | subject_swap catch | control false positives |
|---|---|---|
| llama3.1 8B | **3/3** | 1/10 |
| qwen3 8B | 1/3 | **0/10** |
| qwen3.5 | 0/3 | **0/10** |

A perfect recall/precision trade with no winner: llama3.1 catches every
planted swap but still cries wolf once; the qwen models never cry wolf but
wave the swaps through. (Prompt iteration mattered — the first "is it
consistent?" wording had llama3.1 flagging **8/10** controls because *not
restating* the subject read as *contradicting* it; the contradiction-only
rewrite fixed that class.) Conclusion, stated plainly: at the local-8B tier
the semantic axis cannot meet the 0-FP bar the structural axes hold, so it
stays **off by default — by measurement, not assumption**. A stronger model
re-takes the same exam with one command:
`python -m legal_agent.evaluation.mutation --semantic --model <name>`.

### A2. Tier-1 golden set — llama3.1 8B through the full gated pipeline

`python -m legal_agent.evaluation.golden_set evals/golden_noise_v1.json`
(auto-scored axes only; legal-judgment wording is human-compared by design)

| axis | result |
|---|---|
| 法條涵蓋 (19 scorable cases) | **pass 11 / partial 5 / miss 3** — strict 58%, pass+partial 84% |
| 誠實分級 accuracy (25) | **21/25 (84%)** |
| 前提偵測 accuracy (25, Gate 5) | **25/25 (100%)** |
| out-of-scope refusal (5 cases) | **5/5** short-circuited to `insufficient` |

Coverage gaps (each missing statute was neither retrieved top-5 nor cited):
in-04 缺§3(定義條), in-05 缺§9, in-06 缺§195, in-12 缺§793, ts-01 缺§6;
mg-02 / wp-02 / wp-03 全缺。These are retrieval-recall gaps on sparse fact
wording — the documented next step is hybrid (dense) retrieval.

Tier misses: the 3 borderline probes (mg-01/02/03) and wp-03 scored BM25
15.4–29.4, interleaved with true in-scope cases → graded `normal`, not
`marginal`. (A previous fourth miss — **oos-01 漏水 leaking past the honesty
gate at top BM25 3.89** — is fixed by the calibrated `insufficient` floor
below.)

**What the golden set caught while being built:** out-of-scope questions
initially matched half the corpus through single-character function-word
tokens (的/與) in jieba's output — a real retriever defect, fixed in
`retriever._tokenize` (drop 1-char CJK word tokens; bigrams keep the signal),
all tests green after the fix.

### A3. Honesty-threshold calibration

`python -m legal_agent.evaluation.calibrate evals/golden_noise_v1.json`

The score distribution shows a clean gap at the bottom: the out-of-scope leak
(oos-01) tops out at BM25 **3.89** while the weakest in-scope case scores
**9.65**. `honesty.INSUFFICIENT_SCORE_THRESHOLD = 6.0` (the geometric midpoint)
now short-circuits anything below it as `insufficient` — out-of-scope refusal
5/5, no in-scope case affected.

Above that floor the sweep is unchanged: default marginal threshold 1.5 → 84%
tier accuracy; **best possible marginal threshold → also 84%**. The remaining
misses (marginal probes at 15.4–29.4, interleaved with true in-scope cases)
are not linearly separable by any BM25 cutoff — quantified evidence that the
marginal/normal distinction needs a better relevance signal (hybrid retrieval
/ score normalization), not more threshold tuning.

### A4. Ablation — bare (憑記憶引用) vs gated (五閘門), per model

`python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json --models llama3.1:latest qwen3:latest`

Same 25 questions. **bare** = the question sent straight to the model, asked to
cite applicable statutes from memory (what a raw chatbot gives you). **gated** =
the full five-gate pipeline. Every citation in both conditions is checked
against the corpus on all three axes.

| model | condition | citations | traceable to corpus | flagged & shown to user |
|---|---|---|---|---|
| llama3.1 8B | bare | 12 | 0 (**0%**) | — (no verifier in this condition) |
| llama3.1 8B | gated | 83 | 58 (70%) | **25 (30%), each with the verbatim article attached** |
| qwen3 8B | bare | 76 | 4 (**5%**) | — |
| qwen3 8B | gated | 126 | 76 (60%) | **50 (40%), each with the verbatim article attached** |

All flags in both conditions were exists-axis (corpus 查無); no wrong-amount or
out-of-force citations were produced this run. Honesty-tier distribution under
gated was **identical for both models** (insufficient 4 / normal 21) — the tier
is decided *before* the LLM runs, from retrieval scores alone, so it cannot
vary by model. Zero case-runs errored.

Reading the table:

- **Bare, the user has no trail.** 95–100% of memory-cited statutes cannot be
  traced to any vetted source. (Closed-world: some are real statutes outside
  the 11-entry corpus, some are fabrications — *the user cannot tell which*,
  and that indistinguishability is precisely the hallucination problem.)
- **Gated, small 8B models still over-reach** — 30–40% of their citations go
  beyond the supplied verbatim articles despite the "cite only what I supply"
  instruction. The pipeline does not pretend otherwise: every such citation is
  flagged inline with the corpus original for comparison. *The model errs; the
  user knows.* A stronger model lowers the flagged rate; the gates are
  identical regardless of backend.

---

### A5. 判決參考層 — what the harvested judgments actually buy (2026-07-23)

Two nights of harvesting (裁判書開放API, 0-6h window, incremental 7-day-lag
feed) put **1 367 judgments** in the reference table. The honest audit:

| what | number |
|---|---|
| judgments harvested | 1 367 |
| **usable** — cite ≥1 article that exists in our statutes corpus | **386 (28%)** |
| corpus articles with ≥1 judgment behind them | 239 / 2 561 (9%) |
| judgments with an extractable 主文 block | 1 078 (79%) |
| judgments with a readable award figure | 370 (27%) |
| award cases ordering SEVERAL payments | 107 / 370 (29%) |

**The 28% matters more than the 1 367.** A day's civil feed is dominated by
交通損賠 / 給付票款 / 返還借款, so most of it cites 民事訴訟法 and never
touches the everyday-law corpus. Worse, the thinnest coverage is exactly the
domains users ask about: 民法 841 matches, but 租賃住宅條例 **2**, 消保法
**4**, 道交條例 **2**. Volume is not the constraint — alignment is. Harvest
cadence should therefore be targeted by 案由, not nightly-everything (measured
argument against a standing schedule).

**主文 extraction (`data/judgment_text.py`) is verbatim-or-nothing**, the same
rule as the statutes corpus; 爭點/裁判要旨 stay NULL because summarising
reasoning is an NLP task this project will not fake. Three properties of real
judgment text shaped it, each found by reading the harvested data:

1. The heading is 「主　　　文」 with IDEOGRAPHIC SPACES — a plain `"主文"`
   search finds *zero* of them. It also appears inside body text quoting
   民訴§436-18 (「判決書得僅記載主文」), so the anchor must be a standalone line.
2. Text wraps at fixed width with indented continuations, so a line is not a
   sentence — and an amount can be split across two lines. Lines are rejoined
   before sentences are split.
3. 主文 carries THREE kinds of money: the award, 訴訟費用, and 假執行擔保.
   Only 給付 sentences carrying neither of the other two markers are read.
   Small-claims judgments write 大寫 numerals (貳萬伍仟玖佰肆拾伍元), which
   are normalised and parsed by the verifier's own numeral parser.

**No single headline number.** 29% of award cases order several payments — one
real case orders six defendants 165 000–1 672 000 元 separately — so printing
the largest as 「判賠 X 元」 would misstate the case. One amount is reported
exactly; several are reported as a range marked 多筆.

**Negative result — 同法 anaphora resolution, measured and NOT shipped.**
Judgment prose writes 「並依同法第392條」, and the citation extractor stores
同法 as the statute name, so those citations never match anything. Resolving
the anaphora (同法 = the last statute named before it) looked like free
recall. Two measurements, and the first one was wrong:

- A loose antecedent regex reported **0 of 425** anaphora citations resolving
  into the corpus — it was capturing particles (依同法, 本件係就民事訴訟法)
  as if they were statute names. A bad ruler produces a confident zero.
- Anchoring on KNOWN statute names instead: **61 of 425 (14%)** resolve to a
  corpus statute (民法 55, 家暴法 3, 勞基法 2, 消保法 1).
- The number that decides it: **0 judgments become newly usable.** Every
  judgment that would gain a resolved citation already cites a corpus article
  directly, so the reference layer's 386 usable judgments do not move. The
  only effect would be small shifts in overlap ranking — bought with a real
  risk of mis-attributing an article to the wrong statute.

Not shipped. Same rule as the lexicon table: a change that moves no number
does not enter the codebase.

Live output on real data (慰撫金 consultation): three 損害賠償 judgments
citing 民法§184/§185/§195 with 判賠 2 150 000–5 134 300 元(多筆) etc. The
押金 consultation correctly shows NO judgments — the corpus has 2, and neither
was retrieved. That silence is the measurement working.

---

### A6. Six lived sessions — what USING it exposed (2026-07-25)

Everything above measures the system against sets the system was built for.
This section is what happened when six ordinary problems were typed into
`python -m legal_agent.run` and the whole transcript was read as a user reads
it: 押金不退, 房東不修漏水, 打工加班費, 機車車禍, 網購瑕疵, 樓上小孩跑跳.

Six sessions produced **eleven distinct defects**, of which the two most
serious were in the guardrail itself.

#### A6.1 The verifier was wrong in both directions

| class | what the user saw | status |
|---|---|---|
| **false NEGATIVE — bracketed citations invisible** | 「根據《民法》第9999條」 extracted **nothing**: the citation regex required a CJK character immediately before 第, and 》 is not one. A pure fabrication in the model's most natural writing style was never checked. | fixed |
| quoted cross-references | 勞基§32-1's own text says 「雇主依第三十二條第一項…」; each was read as a citation of a statute named 「雇主依」 → three 「corpus 查無此法源」 warnings on a **correct** answer | fixed |
| common abbreviations | 「依刑法第271條」 flagged as unknown source — the corpus id is 中華民國刑法 | fixed |
| shared claim scope | 「依社維法§72處一萬元以下罰鍰,依民法§195得請求…」 — §195 graded against §72's 一萬元 | fixed |

The false negative is the one that matters: **4 of 8 realistic writing forms
were skipped entirely** (《名》第X條, 「名」第X條, 名 第X條, and the bracketed
parenthetical). A gate that silently ignores a writing style is worse than a
noisy one, and the earlier "31/31 seeded errors caught" number never saw it —
every seeded citation was written 依{名}第X條, the one form that worked.

Fixes: optional closing bracket / whitespace between name and 第X條; a verified
alias table (刑法 → 中華民國刑法 …) that may only resolve to ids that EXIST;
unnamed references inherit the previously named statute and are checked for
EXISTENCE but not content (the sentence around them belongs to the quoted
article, not to them); claim scope clipped at the neighbouring citation, and at
the clause comma when two citations share a sentence.

**Full mutation suite re-run after all four changes: 10 435/10 435 caught
(100%), 0/2 560 false positives** — unchanged. A statute-shaped unknown name
(「台灣安寧保障法」) still flags; only prose runs are treated as anaphora, which
is what keeps `fake_statute` caught.

#### A6.2 Retrieval — the vocabulary gap was worse than the lexicon could fix

Recall on the users' OWN wording (the six sessions' turns joined, expected
articles verified in the corpus first, hit@8):

| build | hit@8 |
|---|---|
| before this session | **7/14 (50%)** |
| + domain lexicon rows (租賃修繕, 押金/毀損, 買賣瑕疵, 時薪/打工, 跑跳/拖椅子) | 9/14 (64%) |
| + lexicon phrases as a retrieval channel (N=3) | **12/14 (86%)** |

Why the lexicon alone could not do it: inclusion (match / no-match) is decided
by the USER'S OWN WORDS on purpose, and expansion only reorders. 「樓上小孩跑跳、
拖椅子」 shares **not one token** with 社維§72, so no amount of ranking help can
reach it; the dense channel ranked the missing targets 8–25, too deep for the 3
reserved seats. The lexicon's statutory side is verbatim article text, so a
phrase hit is an exact pointer (「製造噪音或深夜喧嘩」 occurs in exactly one
article) — it now promotes up to N such articles into the window at an honest
BM25 score of 0.0, leaving the honesty floor (the TOP score) untouched.

N swept on both harnesses (stub-LLM golden v2 pass/partial/miss of 26 scorable
· six sessions hit@8):

| N | golden | real |
|---|---|---|
| 0 | 18/7/1 | 9/14 (64%) |
| 1 | 19/6/1 | 9/14 (64%) |
| 2 | 18/7/1 | 10/14 (71%) |
| **3** | **17/8/1** | **12/14 (86%)** |
| 4 | 13/11/2 | 12/14 (86%) |

N=3 costs one golden case a strict pass (pass+partial stays 25/26 = 96%) and
buys 22 points of real-wording recall. Two known losses remain, recorded rather
than hidden: 勞基§22 (工資全額給付) and — displaced BY the promotions — 公寓大廈
§16 on the noise question.

**Negative result — per-statute cap on the top-k window, measured and NOT
shipped.** One statute floods the window (公寓大廈條例 took 7 of 8 seats on the
noise question), so capping seats per statute looked obvious. It loses on both
harnesses, because real answers legitimately cluster inside one code
(瑕疵擔保 = 民法§354+§359, 加班費 = 勞基§22+§24+§30):

| cap | golden | real |
|---|---|---|
| off | 18/7/1 | 9/14 (64%) |
| 2 | 15/10/1 | 5/14 (36%) |
| 3 | 16/9/1 | 5/14 (36%) |
| 4 | 17/8/1 | 7/14 (50%) |

The six cases now ship as a harness, because a published number has to be
reproducible: [`evals/real_sessions.json`](real_sessions.json) +
`python -m legal_agent.evaluation.real_recall`. It scores retrieval only (no
LLM, no network) on the users' own words, and a test asserts every expected
article actually exists in the corpus — an expectation the corpus cannot
contain would make the number meaningless.

#### A6.2b What the full pipeline did after all of it (real llama3.1 8B, 30 cases)

| | before | after |
|---|---|---|
| golden statute coverage | 96% pass+partial (69% strict) | **100% pass+partial (73% strict)** — pass 19 / partial 7 / **miss 0** |
| honesty tier | 77% (23/30) | 77% (23/30) — unchanged |
| premise detection | 100% (30/30) | 100% (30/30) — unchanged |
| cases with a reference judgment | 21/30 (20 with an award figure) | **11/30 (10 with an award figure)** |

The judgment row went DOWN by design and is reported as a loss, not spun: the
join now runs on the articles the answer actually cites instead of the whole
retrieved window, which is what stopped a 本票 case appearing under a noise
question. Precision up, coverage halved. Whether that trade is right is a
judgement call, and the number is here so it can be revisited.

#### A6.3 The rest of what the transcripts showed

- **The flagship scenario never fired.** 「樓上小孩每天晚上跑跳到十一二點,還會
  拖椅子」 — the textbook complaint for the ONE scenario with a hand-built
  ladder — contains neither 噪音 nor 吵, so triage classified it ambiguous and
  the user got the generic ladder: no 報警, no 管委會, no 存證信函範本. Behaviour
  words added to the triage keywords.
- **Anti-sycophancy fired on the question itself.** 「這樣有沒有違法?」 tripped
  Mechanism 5, and the user was told they had 「先下了法律判斷」 for asking the
  question the tool exists to answer. Conclusion words now flag only outside a
  genuine question frame — 「就是違法,對吧?」 (agreement-seeking) still flags,
  and the golden set's three wrong-premise cases still score 30/30.
- **The intake did not ask anything.** The local 8B model restated the user's
  facts and asked 「你覺得這樣合法嗎?」 — for four turns straight, filling no
  fields. Code now guarantees progress: a reply that asks nothing, or repeats
  an earlier one, is replaced by the next missing checklist question, and the
  answer to a code-asked question is filed verbatim if the extractor drops it.
- **Cosmetics that cost trust.** Sections rendered as 「法律明文**」 with a stray
  「**」 line between each (models write markdown headings); a 「實務見解段未標明
  非法律明文」 warning fired on a section whose body was 「(無)」; the reference
  judgments printed the API's jid (「PCDV,115,訴,493,20260713,1」) instead of the
  案號 a person can look up. The 案號 is now read verbatim from the judgment's own
  first two lines — **1 362/1 367 (99.6%)** parse; the five that do not are
  調解筆錄 / 宣示判決筆錄, which genuinely have no such header.
- **The banner still said 住宅噪音法律助理** while the corpus covered eleven
  statutes — the first line every user reads, wrong for a week.
- **The model uses only part of what it is given.** One session was handed
  勞基§22/§24/§30 and wrote about §30 alone. The retrieved window is now listed
  code-side beside the answer, so the reader sees the law that was FOUND, not
  only the law the model chose to discuss.

---

### A7. Round two — the honesty floor had been dead for a week (2026-07-25)

Six MORE lived sessions, chosen to be things the assistant had never seen:
資遣費, 房東擅自進房間, 車禍對方受傷求償, 前男友騷擾, plus two deliberate
out-of-corpus probes (商標搶註, 虛擬貨幣課稅).

#### A7.1 The worst failure this project has shipped

Asked 「虛擬貨幣獲利怎麼課稅」, the assistant answered with **中華民國刑法§195/
§196/§198 — 偽造、變造通用貨幣**. Top BM25 37.5, honesty tier `normal`,
citations all verified (they exist, they were retrieved, the quotes match). Every
gate did its job and the answer was still nonsense, because the gate that was
supposed to say 「資料庫沒涵蓋」 never fired.

Cause: `INSUFFICIENT_SCORE_THRESHOLD` was calibrated at **6.0** against the
11-article corpus, where top scores ran 4–42. Corpus v2 lifted the same scores
to 30–330 and the floor was never revisited — so *every* out-of-scope question
cleared it by 5×. The number that would have caught this (tier accuracy 77%) was
published on the README the whole time; it was read as 「out-of-scope detection
is hard」 rather than 「the constant is stale」.

`evaluation/calibrate.py` swept only the marginal threshold, with the floor
pinned — so the harness could not see it either. It now sweeps **both**:

| thresholds | tier accuracy |
|---|---|
| floor 6 / marginal 1.5 (as shipped since v1) | 77% (23/30) |
| **floor 70 / marginal 106** | **90% (27/30)** |

Observed top-BM25 by expected tier: insufficient **31.6–40.5** (n=3) · marginal
85.4–268.1 (n=4) · normal 126.4–330.6 (n=23). The floor is set at 70 rather than
the golden gap's midpoint (62.96) because 商標搶註 scored 62.92 in a real session
— the midpoint would have refused it by 0.04. Golden accuracy is identical
anywhere in 60–80. The three remaining tier misses are all marginal-vs-normal,
which absolute BM25 provably cannot separate (the ranges overlap); that stays
recorded as a signal problem, not a constant to tune.

Verified end-to-end after the change: both probes now short-circuit to
`insufficient` with **0 articles retrieved and no LLM call**, while 資遣費 still
answers (marginal, 8 articles, 勞基§16/§17 among them).

**Negative result — dense cosine as the insufficiency signal, measured and NOT
adopted.** Cosine is scale-comparable across queries, so it looked like the
better floor. Top-1 bge-m3 cosine on golden v2: out-of-scope **0.619 / 0.640 /
0.649** — the three lowest of all 30 — but the weakest in-scope case sits at
**0.634**, interleaved. Length-normalised BM25 (per-token and /√n) and the
top/median ratio were measured too; only /√n matched raw BM25's separation, and
neither beat it. Raw BM25 with an honest floor wins; the extra machinery does not
pay for itself.

**A latent crash fell out of the fix.** The marginal band had been effectively
empty (threshold 1.5), so `_format_result`'s marginal branch had never run in
production — and it read `result.honesty_label` off `PipelineResult`, which has
no such field. Making the band real crashed the CLI immediately. An unreachable
code path is an untested one; the fix also reworded the marginal label, which
claimed 「未找到直接對應的法條」 while sitting on top of 勞基§17.

#### A7.2 Three more vocabulary gaps, one of them safety-critical

| session | what it retrieved before | what was missing |
|---|---|---|
| 前男友騷擾 | 家暴法§2/§13, plus 違反社維法處理辦法§25 (police **interrogation procedure**) as 實務見解 | **家暴法§63-1** — the article that lets 「曾有親密關係之未同居伴侶」 use 保護令 at all — and **§14**, what a 保護令 can actually order |
| 房東擅自進房間 | 民法§441, 租賃住宅條例§7/§23/§24 | **刑法§306** 無故侵入他人住宅 |
| 被資遣沒給資遣費 | 勞基§17/§18/§20/§28 (already good) | — |

The harassment one matters most: without §63-1 the 8B model asserted 「這是家庭
暴力」 about someone who was never a 家庭成員, which is both legally wrong and,
for a person deciding whether to seek a protective order, actively unhelpful.
Three lexicon rows later (all statutory sides verbatim), the same query surfaces
§63-1 and §14.

#### A7.3 Two bugs inside the promotion mechanism itself

Re-running the stalking session with the new rows exposed the seat allocator:

1. **Seats went to whichever row sat higher in the table.** 「前男友」 (a 3-char
   trigger) lost its seats to rows triggered by 「聲」 (1 char), because the noise
   rows come first. Phrases are now ordered by how specifically they were
   triggered — a long trigger matching is far less likely to be incidental — with
   ties broken by table position, NOT by the phrase text (the first version
   sorted 「持續性監視…」 above 「現有或曾有親密關係之未同居伴侶」 alphabetically and
   cost the case its most important article).
2. **The promotion evicted the articles it exists to protect.** 家暴法§14 sat at
   rank 6 of the 8-slot window, so it counted as 「already in the window」 and was
   not promoted — and then three promotions trimmed the window to five and
   dropped it. The trim now takes the unprotected tail first: an article matching
   the same triggered phrases is cut only when nothing else is left.

Recall harness, nine cases: **19/20 (95%)** hit@8 — the noise case reached 3/3
for the first time and the stalking case 2/2. Golden v2 at its best measured
state: stub pass/partial/miss **19/7/0**, tier 27/30, premise 30/30. The one
remaining miss is 民法§423 on 房東擅自進房間, where 刑法§306 (無故侵入他人住宅)
does surface — the stronger article of the two.

#### A7.4 The web demo had never been used either (2026-07-25)

Twelve lived CLI sessions, zero web sessions — and the Gradio tab is the front
door AND a different code path: it runs the RULE-BASED intake (model-free by
design, so it works on HF Spaces free CPU), so none of §A6.3's intake work
applied to it. Three consultations through `app.consult_step`:

| what the visitor saw | fix |
|---|---|
| Typed 「退租後房東說牆壁有釘孔要扣我兩個月押金」 and was asked 「這是租屋、勞資、消費、車禍、家事,還是鄰里的問題?」 — classify what you just described | triage now recognises 租屋/勞資/消費/車禍/家事 by keyword; only genuinely vague openings get the discriminating question |
| Four turns in, the result column was still blank and there was no way to finish | 「請幫我分析」 (and a 6-turn cap) end the intake from `handle_turn`, so BOTH front ends have the exit; every question block now says the exit exists |
| Answered 「公寓大廈有管委會」, was then asked 「有管委會的公寓大廈,還是透天?」 | answers are filed by WHAT THEY SAY when a line unambiguously matches one still-open field, positional otherwise |
| 「噪音主要是什麼?」 asked four turns running to someone whose opening line was 「樓上小孩跑跳、拖椅子」 | the noise flow seeds that field from the opening complaint, exactly as the generic flow already seeded `problem` |
| 民法§432 — the article that decides a 押金/釘孔 case — displayed last, labelled 「相關度 4%」 | a 0.0 BM25 score is the honest score of a dense/lexicon-channel candidate, not 4% relevance; those cards now say 「語彙/語意比對命中(與提問無字面重疊)」 |

A bug in the routing fix itself, worth keeping: the leftover lines were indexed
by the PENDING-question index rather than their own cursor, so a routed line
silently ate a positional slot and `impact` went unfilled. Caught by the
existing full-transcript test, which is what it is for.

#### A7.5 UX pass — 「不接 AI 的情況下真的很難用」 (2026-07-25, owner feedback)

The owner typed 「退租後房東說牆壁有釘孔要扣我兩個月押金」 into the running demo
and got 「這是租屋、勞資、消費、車禍、家事,還是鄰里的問題?」. That exact case had
just been fixed (§7.4) — they were on a server started before the fix — but the
verdict stood: the model-free flow reads as paperwork, not a consultation.
What shipped after that feedback:

- **The web demo now drives its INTAKE with the model** when one is available.
  It had used Ollama for the Stage-3 narrative since the day it shipped while
  still asking a scripted checklist, even with a model running on the same
  machine. `flow.handle_turn_smart` has the same `(reply, state)` contract as
  `handle_turn`, so the front ends pick per-request and the scripted path still
  runs when there is no model — which is what keeps the demo alive on HF Spaces
  free CPU.
- **The opener stopped describing its own plumbing.** 「「住宅噪音」有專屬問診流程,
  其他問題走通用流程(同一套檢索與五道關卡,語料涵蓋民法、租賃住宅條例…)」 was the
  first thing a visitor read. Now: 「了解,租屋的問題。再問一件事就好——」. Triage
  carries a `label` for the human line and a `message` only when it is
  ACTIONABLE (the personal-safety route's 110 / 113 pointer).
- **One question per turn, and at most three.** MAX_INTAKE_TURNS 6 → 3, because
  this session's own measurement says retrieval on the user's opening words
  already reaches 19/20 of the wanted articles: questions four through six buy
  paperwork, not accuracy.
- **Two more model-intake failure modes, both found in the same three web runs.**
  The 8B model asked 「你覺得房東扣你的押金是公平的嗎?」 — a question mark, not a
  repeat, and it hands the legal judgement back to the person who came to ask
  it. And after the visitor answered 「公寓大廈有管委會」 it asked 「…公寓大廈有管
  委會嗎?」. Both are now caught deterministically: a verdict-seeking phrase, or
  a question whose keywords belong to an already-filled field, is replaced with
  the next missing checklist question. The keyword router that the rule-based
  intake uses also runs UNDER the model, so an extraction miss no longer loses
  the answer.

---

### Reproduce (archive era)

```bash
python -m pytest -q                                                    # 238 tests
python -m legal_agent.evaluation.mutation                              # full-corpus catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json       # golden v2 (30 cases)
python -m legal_agent.evaluation.calibrate evals/golden_v2.json        # threshold sweep
python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json --models llama3.1:latest qwen3:latest --out evals/ablation_raw.json
```

(Tables A2–A4 above are the 11-article-era baselines and still reproduce
against `evals/golden_noise_v1.json`; §A0 records what moved at corpus v2.)

Raw per-run ablation data: [`ablation_raw.json`](ablation_raw.json).

**Ollama note (measured 2026-07-21):** the golden/ablation runs drive a local
Ollama for both embeddings (bge-m3) and generation (llama3.1). On an 8 GB GPU
the default single-resident-model setting swaps the two models on every case —
two runs aborted on the 180 s client timeout that way. Start the server with
`OLLAMA_MAX_LOADED_MODELS=2` and load bge-m3 *before* llama3.1 (small model
first fits both); a clean 30-case run then takes ~10 minutes.
