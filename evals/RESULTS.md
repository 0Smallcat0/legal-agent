# Measured results

Local, zero paid API. Models via Ollama on an RTX 4060 (8 GB). Corpus: 2,560
articles across 11 everyday-law statutes + 1,367 harvested judgments.
Last full run: 2026-07-25.

**Closed-world caveat**: "not traceable to the corpus" is exactly the promise the
system makes — it never means "this statute does not exist."

## Current numbers

| what | number | harness |
|---|---|---|
| seeded defects caught, every article | **10,435/10,435 (100%), 0/2,560 false positives** | `evaluation/mutation.py` |
| statute coverage, 30-case golden set | **pass 19 / partial 7 / miss 0** of 26 scorable — 100% pass+partial, 73% strict | `evaluation/golden_set.py` |
| honesty tier | **27/32 (84%)** | same run (decided from retrieval scores, so model-independent) |
| wrong-premise detection | **30/30 (100%)** | same run |
| retrieval recall, real user wording | **348/353 (99%)** | `evaluation/real_recall.py`, 167 lived problems |
| reference judgments beside an answer | 11/30 cases, 10 carrying a 主文 award figure | counted, never scored |
| bare model vs gated, memory-cited statutes traceable | 0–5% → 30–40% flagged | **STALE** — measured on the 11-article corpus, not re-run at v2 scale |

```bash
python -m legal_agent.evaluation.mutation                          # catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # golden set
python -m legal_agent.evaluation.real_recall                       # lived sessions
python -m legal_agent.evaluation.calibrate evals/golden_v2.json    # threshold sweep
```

## What each harness refuses to measure

- **Mutation test** grades the *verifier's* recall, not the model's. Errors are
  planted in otherwise-correct answers over every article in the corpus.
- **Golden set** auto-scores statute coverage only. Legal correctness is printed
  side by side for a human — a harness that auto-passed legal judgement would be
  the same sin the project exists to avoid.
- **Where the next case comes from** is itself measured. Real disputes cite 239
  corpus articles; the question is which of them the system never reaches. The
  first version of this measure diffed against `expected_statutes` and was too
  loose — an article can be retrieved every time and simply never be expected.
  It now diffs against what the sessions actually SURFACE, which immediately
  showed 民法§1111 as a false gap: that session was correct and had never been
  stored. 民法§188, §252, §92, §1116-2 and 公寓大廈條例§30 all came off the top of
  the list, and every one of them was a real failure.
- **Real-session recall** measures retrieval alone, from the user's own words, so
  the number does not depend on how well the intake performed that day. That
  makes it a FLOOR, not the product: Stage 3 also hands the dense channel a
  focused problem+goal query, and the harness deliberately does not. Measured on
  the same session — 民法§1111 is rank 5 of the window the CLI actually produced
  and absent from the window the harness produces for the same story. Making the
  harness match production would raise the published number by changing the
  measurement, so it stays as it is.
  **The label was over-used, though.** §1111, §439, §450 and §271 sat under it
  for several rounds until a sharper test — does ANY lexicon phrase match the
  article at all — showed none did. They were reachable gaps, not measurement
  noise: four rows later they hit, and recall went 204/223 to 208/223. 「The
  harness is a floor」 is true and was also a place to put things.
- **Judgments** are counted, never scored: there is no ground truth for "the
  right judgment," and inventing one would poison the layer.

## Honest limits

- **The honesty tier reads a score the vocabulary table inflates.** BM25 runs on
  the EXPANDED query, so the tier measures how much of my own lexicon fired, not
  how well the corpus covers the question. Measured on three sessions
  (expansion on / off): an out-of-scope 本票裁定 goes 153.0 / 50.2 — confident
  instead of refused — while an in-scope 時效 question goes 156.6 / **16.1**, so
  simply scoring the user's raw words would refuse the case that belongs. The
  out-of-scope question outscores the in-scope one unexpanded, which is why no
  threshold separates them: `oos-09-promissory-note` and `oos-10-debt-relief`
  are in the golden set failing, and the number moved from 27/30 to 27/32 to
  say so.
- **The golden set's strict/partial split moves with model sampling, and the
  published number does not chase it.** Two runs over the SAME 32 cases, the
  same corpus and identical retrieval (verified: not one of the round's new
  lexicon rows fires on any golden case) scored 19 pass / 7 partial and
  21 pass / 5 partial. pass+partial is 100% in both, and 27/32 tier and 32/32
  premise did not move — the seam is the model choosing to name an article
  versus paraphrasing it. Five runs now: 19/7, 21/5, 20/6, 20/6, 22/4 — a spread
  of three cases. The last of those followed a change to the noise row, which
  golden's noise cases do use, so unlike the earlier samples a real effect cannot
  be ruled out there; one sample cannot separate it from a spread this wide
  either. The table keeps 73% strict rather than publish the luckiest run, and
  tier (27/32) and premise (32/32) have not moved in any of the five.
- **marginal vs normal is not separable by BM25.** The score ranges overlap
  (marginal 85–268, normal 126–331). That needs a better relevance signal, not a
  better constant — dense cosine was measured as a candidate and interleaves the
  same way.
- **Judgment coverage is thin exactly where it matters.** Of 1,367 harvested,
  386 (28%) cite an article in our corpus, and the thinnest domains are the
  everyday ones (租賃住宅條例 2, 消保法 4). A day's civil feed is 交通損賠 /
  票款 / 借款.
- **Historical statute versions**: the corpus carries one true historical slice.
  "Which version applied in 2024?" is answerable in mechanism, not yet in data.
- **The 8B model is the weakest component** and is treated that way: it repeats
  itself on long article lists and uses only part of what it is given. What must
  be right — citations, judgments, the tier — is not left to it. Measured this
  round in a full CLI session (贈與/扶養): the model emitted the SAME 民法§473
  sentence 32 times, and the citation verifier faithfully printed the same
  「民法第466條 未出現在本次檢索結果中」 warning 8 times under it. De-duplicating
  identical flags in `run.py` is three lines and clearly right — and it moves no
  published number (recall / golden / tier / mutation all unchanged), so by this
  project's own rule it is recorded here rather than shipped. It also reaches for
  the FIRST limb of a numbered article: handed 民法§1145 for a brother who hid a
  will, it explained 款一 (故意致被繼承人於死) when the case is 款四 (隱匿遺囑).
  Retrieval put the right article in front of it; picking the right
  sub-paragraph is the model's job and the weakest link in the chain. In the same
  batch it was handed 民法§276 at rank 1 for 「公司被免除了我還要不要還」 and wrote
  about §273 and §281 instead — the neighbours, answering 「誰可以被追」. Rank 1 is
  not a hint the model reliably takes, which is why the window is printed in full
  under every answer: the reader can see the article the model skipped.
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
- **The ablation row is stale** (see the table).

## Measured, then NOT shipped

Each of these looked obviously right and lost on the numbers:

- **per-statute cap on the retrieval window** — one statute really does flood it
  (7 of 8 seats), but capping loses on both harnesses, because real answers
  legitimately cluster inside one code (民法§354+§359).
- **capping corroboration once a row already had N articles in the window.** A
  session about a living man with dementia had a window that was 8/8 繼承編, so
  the inheritance row counted as corroborated and spent 2 of 3 seats fetching a
  ninth and tenth inheritance article. Measured against the uncapped 68/70:
  N=1 → 65/70, N=2 → 66/70, N=3 → 68/70. Finishing a topic is worth more than
  the one case it was meant to rescue — that case was fixed by knowing the
  father is alive instead.
- **three separate signals for 「is this question out of scope」**, all measured
  against the five out-of-scope golden cases and all overlapping the in-scope
  range: dense cosine (0.611–0.649 out of scope, 0.569–0.770 in scope — the
  earlier rejection re-confirmed with two new cases), BM25 on the user's RAW
  words (out-of-scope 本票裁定 50.2 beats in-scope 時效 16.1, i.e. inverted), and
  the share of query terms appearing in no article (0.62–0.74 against 0.38–0.70).
  The tier cannot be rescued by a better number; 票據法 and 消費者債務清理條例
  are simply not in the corpus, and nothing in a score knows that.
- **dense cosine as the insufficiency signal** — scale-comparable across queries,
  so it should have beaten raw BM25; the out-of-scope cases are the three lowest
  but the weakest in-scope case sits between them.
- **「同法第X條」 anaphora resolution in judgments** — 61 of 425 resolve, and
  **0 judgments become newly usable**.
- **query-term weighting**, and the **first lexicon design** (expansion terms
  entering the match decision, which manufactured false hits).
- **ranking corroborated lexicon rows by the STRENGTH of their evidence**
  (how high the corroborating article sits) rather than yes/no. 民法§191 at rank
  1 does look like better proof of a topic than a tenancy article at rank 8 —
  and it costs 民法§818 without recovering 民法§184 (59/61 against 60/61).
- **breaking lexicon ties by how MANY triggers matched** (instead of table
  position) — it recovers 民法§354 for a house-purchase case, and costs the
  golden set two strict passes (19 -> 17). One real hit is not worth two.

## More

[`HISTORY.md`](HISTORY.md) — how each number was arrived at: the three defect
classes that started at 0%, the data bug the exam caught before a human did, and
the week the insufficiency gate was dead. ·
[`golden_v2.json`](golden_v2.json) · [`real_sessions.json`](real_sessions.json) ·
[`README.md`](README.md) — case schema and provenance.
