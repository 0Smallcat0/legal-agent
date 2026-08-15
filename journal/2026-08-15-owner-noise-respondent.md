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

## Run conditions (to be filled by the result commit)

- corpus fingerprint:
- `dense_fallbacks`:
- provider / model / temperature:
- retrieval window with scores:
- honesty tier, `flagged_count`:
- full output:

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
