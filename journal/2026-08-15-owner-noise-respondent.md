# Case journal — owner's own live dispute, 2026-08-15

**This file is NOT an eval. Nothing here is scored, and nothing here may ever
enter a published number.** It is one unfinished dispute, n=1, with labels the
party himself supplies. `evals/` is off limits for it by rule; see the reason at
the bottom of this file.

## The case

The owner is the **respondent**: a neighbour has complained that HE is too
loud. Every part of this system — the 168 real sessions, the lexicon, the
`NOISE_CHECKLIST` questions, all five rungs of the escalation ladder — was
built for the complainant.

His own words, verbatim:

> 目前我被鄰居投訴太吵了,不是鄰居太吵,這套系統如何幫助我保障自身權益?

The description fed to the pipeline for this run is the fuller paraphrase used
in the earlier retrieval-only probe, so the two windows are comparable. It is a
paraphrase written by an agent from his sentence plus two facts he gave (the
committee has come to warn him once, the police attended once) — labelled here
as a paraphrase precisely because it is one:

> 鄰居投訴我家太吵,說我半夜有聲音走路關門,管委會也來勸導過,警察也來過一次,我覺得沒有那麼吵,想知道我要怎麼保障自己的權益

## Predictions, written and committed BEFORE the run

The point of this section is that it is timestamped by git ahead of the result
commit, the same discipline `realworld.py --direction` uses: the answer side is
coded before the outcome side is read, and the order is checkable rather than
asserted.

Already known and therefore NOT predictions: that the three governing articles
arrive at score 0.0 on the lexicon's reserved seats while BM25's top of the
window is unrelated, and that the honesty tier came back `marginal` for both
sides. Both were measured in the earlier probe, on the degraded
`dense_fallbacks=1` path.

**(a) Will the 分析研判 section write him as the complainant?**
Predicted YES — the section will contain at least one instruction that only
makes sense for the party asserting the claim (record the noise, report it,
demand that it stop, or seek compensation). Falsified if every sentence in the
section is consistent with him being the respondent.

**(b) Which rungs does the ladder actually print?**
`problem_type == "noise"` routes to `solution.build_solution_ladder`, which
ignores `retrieved` entirely. Predicted: the five canonical rungs
`hoa / police / mediation / letter / litigation` (four if the building is not
classified as 公寓大廈, which drops `hoa`); `hoa` and `police` both marked
已嘗試 because 管委會 and 警察 appear in his own description and
`_TRIED_KEYWORDS` matches on those words; therefore **`mediation` is flagged
👉 建議下一步**, with `letter` and `litigation` below it. That is: apply for
mediation against the neighbour who complained about him, then send that
neighbour a demand letter, then sue him.

**(c) Does the answer read the THRESHOLD, or only the penalty?**
This is the prediction that matters. The three thresholds are in the statutes'
own words: 社維法§72 第二款「不聽禁止者」, 公寓大廈條例§16 第五項「經制止而不遵
從者」, 民法§793 但書「但其侵入輕微,或按土地形狀、地方習慣,認為相當者,不在此
限」. Predicted NO for all three: the answer will quote or paraphrase the
penalty side (罰鍰、得報請主管機關處理) and will not surface any of the three
threshold phrases as a condition the complaining side must still satisfy.
§793 did not reach his window at all in the degraded probe; this run has dense
retrieval participating, so whether it now arrives is itself worth recording.

**(d) Is any deadline quoted to him that only means something to the party
asserting a right?**
Predicted NO deadline appears anywhere in the noise path — not because the
system judged it irrelevant to a respondent, but because
`build_solution_ladder` never calls `_deadline_rung` (only
`build_generic_ladder` does), and the system prompt forbids the model from
stating any period itself. So the correct-looking outcome here would be
produced by a structural gap rather than by a decision. If a period does appear,
it came from the model in violation of that instruction, and that is the finding.

**Secondary, recorded so they cannot be reinterpreted afterwards:** predicted
`flagged_count == 0` and predicted tier is `normal` or `marginal`, never
`insufficient`. On the 24 externally-coded cases, `flagged_count` was 0 on all
five direction inversions — the citation check and the direction error are
disjoint, so a clean verification line is expected here and proves nothing about
whether the answer points the right way.

## Run conditions

- corpus fingerprint: `statutes 2923 列 / 2922 條號｜judgments 386｜地板 2923/2922/386｜達出貨地板`
- `dense_fallbacks`: **0** on both runs
- provider / model / temperature: ollama / `llama3.1:latest` / **0.0**
- baseline harnesses on the same tree, before any change: pytest 525 passed;
  mutation 11904/11904 (100%) with 0/2921 false positives; real_recall 348/356
  (98%) at `dense_fallbacks` 0

Two configurations, both driven straight into `advance_to_stage3` with
`problem_type="noise"`, so no words were put in his mouth by a scripted intake:

- **Run A — his sentence only.** `noise_type` holds the paraphrase above and
  nothing else; `building_type` and `actions_taken` are empty.
- **Run B — the same sentence re-filed into fields.** No new facts: the
  committee and the police move from the description into `actions_taken`, and
  「公寓大廈(有管委會)」 into `building_type`, which is what a smart-intake
  session extracts. This is the configuration that reaches `_TRIED_KEYWORDS`.

| | Run A | Run B |
|---|---|---|
| tier | `marginal` | `normal` |
| `flagged_count` | 0 | 0 |
| `premise_flag` | False | False |
| 民法§793 in window | yes, score **0.0** | yes, score **0.0** |
| 社維法§72 in window | yes, score **0.0** | yes, score **0.0** |
| 公寓大廈§16 in window | yes, score **0.0** | yes, score **0.0** |
| top of window | 噪音案件…處理原則 59.5 | 噪音案件…處理原則 114.3 |

All three governing articles arrive on the lexicon's reserved seats at 0.0 in
both runs, with dense retrieval fully participating. §793 DID reach his window
this time — in the earlier `dense_fallbacks=1` probe it did not — and it still
scores 0.0, so it is the reserved seat carrying it, not the retriever.

## Results against the predictions

**(a) Does 分析研判 write him as the complainant? — WRONG, and wrong in the
direction that flatters the model.** Run A's analysis is written from his seat:
「他可以向警察機關主張**自己沒有**製造…之聲音」 and 「準備或保存證據…以**證明自己
沒有**製造噪音」. It even tells him the other side's position holds:
「對方的說法站得住,因為警察機關已經來過一次,並且管委會也來勸導過」. Run B drifts
back: 「保存警察機關的處理紀錄和證據,以便於**追究法律責任**」 is complainant
language. So the prose half handled the seat better than predicted, and
unevenly between two runs of the same case.

**(b) Which rungs print? — RIGHT, both runs, including the recommended rung.**
Run A prints four rungs (no `hoa`, because `building_type` is empty) and flags
**報警請警察到場 👉 建議下一步** — the tool's recommended next step for the
person being complained about is to call 110 about the noise, with 社維法§72,
the article that fines him, printed as its 依據. Run B prints five, marks
`hoa` and `police` 已嘗試 off his own words, and flags **調解 👉 建議下一步**,
with 存證信函 and 民事訴訟 below it: apply for mediation against the neighbour
who complained about him, then send that neighbour a demand letter, then sue
him. Under it, in both runs, the code prints a 存證信函 template whose 主旨 is
「請停止製造噪音」 and whose 說明 reads 「台端…持續發出【噪音情形】,妨害本人生活
安寧」 — a letter for him to send, accusing someone else of the thing he is
accused of.

**This is the finding.** The model's prose was the half that partly got his
seat right; the deterministic half — the ladder and the letter template, the
layer this project trusts most and forbids the model to touch — was wrong in
both runs and wrong identically. The severity order in the task description
holds up exactly.

**(c) Threshold or penalty? — HALF WRONG, and the half that was wrong is worth
more than the half that was right.** The threshold text did reach the page:
Run A's 法律明文 quotes 社維法§72 **including「不聽禁止者」** and 民法§793
**including the 但書**「但其侵入輕微,或按土地形狀、地方習慣,認為相當者,不在此
限」, verbatim. Run B quotes §72's 「不聽禁止者」 and 公寓大廈§16's 喧囂 prohibition.
But no run uses any of them AS a threshold. The 但書 is never connected to him,
and 「不聽禁止」 is never named as something the other side must still establish
— in Run A the analysis takes the two facts that would go toward satisfying it
(the committee came, the police came) and reads them as evidence that 「對方的說
法站得住」. Retrieved, quoted, and not read: the distinction the prediction was
written to test.

An unpredicted result belongs here too. Run B's 實務見解 surfaced the 新北市
police handling principle verbatim: 「必須有舉發人具名指證並製作筆錄…如經相鄰住戶
具名指證確有妨害安寧情事,始得以社維法移送法辦」. That is a procedural threshold
on his side, it was found without any vocabulary being added for him, and it is
the single most useful line either run produced.

**(d) A deadline that only means something to the asserting party? — RIGHT, for
the predicted structural reason.** No period appears anywhere in either run.
`build_solution_ladder` never calls `_deadline_rung`; the noise path ignores
`retrieved` entirely. Nothing decided this was inappropriate for a respondent —
the noise path simply has no deadline code at all. The model also stated no
period, which is the system prompt's ban holding.

**Secondary — both right, and both worth nothing on their own.**
`flagged_count` 0 in both runs, tier `marginal` / `normal`, never
`insufficient`. Exactly as expected, and exactly as uninformative: on the 24
externally-coded cases `flagged_count` was 0 on all five direction inversions.
The verification line was green here while the ladder pointed him at mediation
against his own complainant.

## Why this case is never allowed to be a ruler

n=1, unfinished, and self-labelled — but the deciding reason is the fourth one:
if vocabulary is added for this case and this case is then used to score the
result, that is the 93% loop rebuilt exactly. 25/27 (93%) was measured after two
rounds of vocabulary curation against those same 16 cases; on 17 unseen cases of
the same kind the same pipeline scores 12/23 (52%).

If this dispute ever ends with a disposition or a mediation record **written by
someone else**, it may become an `official`-labelled ended dispute — but it must
be permanently marked as a case that vocabulary was once tuned against, and it
may never enter any held-out number. A case that has been tuned against can
serve as a regression case and never as a ruler.
