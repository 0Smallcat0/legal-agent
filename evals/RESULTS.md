# Measured results

> **This file is long on purpose, and much of it is failures.** If you read one
> screen, read this one: what is claimed, the current numbers, the limit that
> outranks them, and how to reproduce them. Sections are dated individually —
> there is no single "last full run" date, and a number is only as current as
> the entry it sits in. The dated changelog that used to fill this file now lives
> in [`HISTORY.md`](HISTORY.md).

**What is claimed.** A RAG pipeline whose citations are checked by code after
the model runs — does the article exist, does the quote match, was it in force —
and whose checker is itself graded by planting errors in otherwise-correct
answers over every article in the corpus. Retrieval, the citation check, the
confidence tier, the deadline quotes and the action ladder are decided by code;
the model writes the prose. **What is not claimed:** that an answer is legally
right. Green means the cited article exists, is in force and was not misquoted —
never that it governs the reader's problem (§2, §7).

## §1 — Current numbers

This table is the single source of truth: the README's table is a subset copied
from it. Harness names are modules in `legal_agent/evaluation/`; rows marked
*(model)* call a real model and are not deterministic, every other row re-runs
identically.

| what | number | harness |
|---|---|---|
| seeded defects caught | **100% in each of 22 kinds, 0/2,921 false positives** — per-kind denominators in §4 | `mutation` |
| blindspot cases the checker catches | **21/25** — 4 named misses, all modal/proviso semantics | `blindspots`, `evals/blindspots_v1.json` |
| semantic 4th axis — the only thing that catches a subject swap | catches **9/9**, and flags **1,259/2,921 (43%)** of CORRECT citations, so it stays off | `mutation --semantic` *(model)*, llama3.1, `semantic_unreached` 0 |
| statute coverage, 32-case golden set | **pass 19 / partial 7 / miss 0** of 26 scorable — 100% pass+partial, 73% strict | `golden_set evals/golden_v2.json` *(model)*, grader at temperature 0, k=8 |
| honesty tier | **29/32 (91%)** | same run (decided from retrieval scores, so model-independent) |
| wrong-premise detection | **32/32 (100%)** | same run |
| out-of-scope refused / in-scope falsely refused | **18/20 · 2/15** — both directions, because only measuring the first hid the second | `honesty_probe`, 35 cases, retrieval only |
| retrieval recall, real user wording | **348/356 (98%)**, 5.9 unexpected articles per session | `real_recall`, 168 stored sessions, k=8, `dense_fallbacks` 0 |
| the same, after a plain `pip install` (no dense index) | **320/356** | `real_recall`, `dense_fallbacks` 168/168 |
| deadlines quoted from the retrieved articles | **69/168 sessions** | counted over the 168 stored sessions |
| first action names the reader's own documents | **83/168 sessions** | counted, same sessions |
| 存證信函 template, law quoted verbatim | **168/168 sessions** | counted, same sessions |
| articles on the page the model skipped | **8 → 18 of 21 expected** | counted on the saved sessions |
| first reference judgment states an awarded sum | **50/60 sessions** (shipped corpus; 54/60 on the full local harvest) | counted over 60 stored sessions |
| that judgment is the same KIND of dispute as the question | **107/118 scorable (91%)**, 156/168 sessions carry one, 38/156 案由 too generic to tell (was 51/88, 146/168 before §11; the ranker now uses the grader's own table — read §11 before quoting) | `judgment_relevance`, both sides derived |
| dispute families holding ≥3 same-kind judgments | **23/25**, 6 judgments short — only 僱傭 and 消費, which no 案由 can name (was 15/25, 25 short) — §10 | `judgment_coverage`, families of the 168 sessions |
| judgments on the page that are ones the question should cite | **87/100 (87%)**, 35/38 questions get one, **0/38 答非所問** (before: 18/63, 11/38, 17/38) — §11 | `judgment_qa`, 38 questions, focus |
| the same, 12 questions **held out** | **27/32 (84%)**, 11/12, 0/12 答非所問 (before: 1/23, 1/12, 8/12) | `judgment_qa evals/judgment_qa_holdout_v1.json`, never tuned against |
| reference judgments beside a golden-set answer | 11/30 cases, 10 carrying a 主文 award figure (30-case golden v2, 2026-07-25); the 32-case run after §8's respondent ban reads 7/32, 3 with an award | counted, not scored |
| bare model vs gated, citations the user must trust blindly | **67% → 5% flagged** (bare 34/51, gated 9/190); a second sample read 16/24 and 4/208, so the bare 67% reproduces and the gated delta is inside the harness's spread | `ablation` *(model)*, llama3.1 over golden_v2, `evals/ablation_v2.json` |
| the article the AUTHORITY cited — cases tuned on | **25/27**, 0 of 16 answered with none of them (first run, before tuning: 7/27 and 9/16) | `realworld`, 16 臺中市 公寓大廈 調處案, labels from the case table's own 法令依據 column |
| the same thing, on 17 cases **held out** | **12/23**, 5 of 17 answered with none of them | `realworld`, 臺北市 13 + 新北市 4, never tuned against |
| answer points the OPPOSITE way to the recorded outcome | **3 of 16** externally labelled, **2 of 8** derived — `flagged_count` 0 on all five | `realworld --direction`, blind-coded, re-runs without a model |

Environment: local, zero paid API; models via Ollama on an RTX 4060 (8 GB).
Corpus: **2,921 articles in force across 16 everyday-law statutes, plus one
historical version** (a repealed slice of 違反社會秩序維護法案件處理辦法§11) and the
police routing note, which is counted separately; 1,367 harvested judgments, 386
of them shipped, plus 49 fetched from the public 裁判書查詢 site (435) — see [`legal_agent/corpus/README.md`](../legal_agent/corpus/README.md).

**Closed-world caveat**: "not traceable to the corpus" is exactly the promise the
system makes — it never means "this statute does not exist."

**Reproduce.** The full list of harnesses, and which of them need a model, is in
[`CONTRIBUTING.md`](../CONTRIBUTING.md#the-harnesses). The short version:

```bash
python -m legal_agent.evaluation.mutation                          # catch rate
python -m legal_agent.evaluation.real_recall                       # lived sessions
python -m legal_agent.evaluation.honesty_probe                     # refuse / false-refuse
python -m legal_agent.evaluation.realworld                         # already-ended disputes
python -m legal_agent.evaluation.golden_set evals/golden_v2.json   # golden set (needs a model)
```

Before comparing any retrieval figure to this table, confirm the harness printed
`dense_fallbacks` 0 — without Ollama + bge-m3 + `python -m
legal_agent.retrieval.dense` it silently measures BM25 alone
([`AGENTS.md`](../AGENTS.md), trap 2).

## §2 — The limit that outranks the rest

Every row in §1 above the last three is measured against expectations this
project wrote — the same hand built the retriever and the answer key, and the 168
sessions were curated against (§8.1). `realworld` breaks that loop: on 16
disputes that already ended, labelled by the article the *deciding authority
itself* cited, the governing article first reached the window **7 times out of
27**, with **9 of the 16 cases answered anyway with none of them** and no
refusal. Two passes of curated 社區治理 vocabulary took that to **25/27 and zero
silent misses**, with every other published figure unmoved. **On 17 cases from
two further tables that nothing was ever tuned against, it is 12/23 (52%), with
5 of 17 answered on none of the governing articles.** That is the figure to quote
for a dispute the project has not seen; 25/27 is not wrong, it is the number on
the set it was curated against. The verifier stayed green throughout, because
green means "this article exists, is in force, and was not misquoted", never
"this article governs your problem" — on the blind-coded direction check the five
answers that pointed the wrong way drew no flag at all. §7 has the full
breakdown.

**Two further limits worth knowing before trusting any of it.** The honesty
tier's 「is this in scope」 half is a list of the statutes we know we lack, so it
refuses **18 of 20** named absences and nothing outside that list — a question
that describes an out-of-scope problem without naming its law still gets
answered. What is left of the score-based tier separates 「相關」 from
「邊緣相關」, and it cannot: BM25 magnitude is inflated by the project's own
vocabulary table. And **precision's harness only prices window changes**: every
other measure here asks whether the right article reached the window, never what
else the reader had to wade through.

## §3 — Three things that looked obviously right and lost

These are the reason to trust §1; the full list is §9.

1. **Widening the reserved retrieval seats.** Four seats measured identical to
   three, five seats measured *worse* (107/113 against 111/113). Measured
   twice, on 22 sessions and again on 47. Not shipped.
2. **Telling the model to walk the retrieved list.** Numbering every article in
   the prompt and demanding it address each one took citations from **20 to 16
   of 56**, and expected articles reaching the answer from 9/24 to 8/24. A
   checklist narrowed the 8B model instead of widening it. Reverted.
3. **Ranking the un-cited remainder by the reader's own words.** Character
   bigram overlap with the session text took the letter's 依據 lines from
   **9 to 7**. Lexical similarity to a lay description does not indicate which
   article governs. Reverted, and the helper deleted rather than left behind a
   flag.

## §4 — Per-kind recall: what the old 11,904/11,904 did and did not cover

That figure was one number over eight seeded-error kinds. It read as "the checker
catches everything", and what it actually measured was "the checker catches
everything the generator knows how to break". Errors the generator could not
express were not in the denominator, so they could not lower it.

The generator now covers twenty-two kinds. Every one is still at 100%, and the
per-kind denominators are what the claim is now allowed to mean — the recall
number for a kind that is not listed here does not exist.

| seeded error kind | caught | what it plants |
|---|---|---|
| `nonexistent_article` | **2,513/2,513** | an article number the statute does not have |
| `ghost_suffix` | **2,513/2,513** | a 之N suffix on an article that has none |
| `prefixed_statute` | **48/48** | a real statute name behind a qualifier prefix |
| `verbatim_crossref` | **15/15** | a cross-reference quoted from another article |
| `ghost_paragraph` | **1,433/1,433** | a 項 the article does not have |
| `real_paragraph_ref` | **1,433/1,433** | a 項 that exists (must NOT be flagged) |
| `ghost_item` | **392/392** | a 款 beyond the article's last one |
| `real_item_ref` | **392/392** | a 款 that exists (must NOT be flagged) |
| `ghost_item_multilist` | **24/24** | a 款 above every list, in an article with several 款 lists |
| `real_item_ref_multilist` | **24/24** | the highest 款 that exists there (must NOT be flagged) |
| `period_swap` | **707/707** | a deadline replaced with a different one |
| `period_direction_flip` | **454/454** | 內 flipped to 後, or the reverse |
| `real_period_direction` | **457/457** | the direction as written (must NOT be flagged) |
| `anaphora_period` | **707/707** | a deadline attributed to the wrong article |
| `direction_flip` | **326/326** | 以上 flipped to 以下 on a penalty |
| `real_bare_amount` | **345/345** | the amount as written (must NOT be flagged) |
| `docnum_adjacent_amount` | **2,921/2,921** | a wrong amount with a 文號 written right after the citation |
| `docnum_before_citation` | **2,921/2,921** | a 文號 written right before the citation; graded on the status line, which must not claim full traceability |
| `real_positional_amount` | **344/344** | the amount in digit-by-digit form, 一〇〇〇〇 (must NOT be flagged) |
| `anaphora_amount` | **345/345** | an amount attributed to the wrong article |
| `fraction_tamper` | **63/63** | 三分之二 altered |
| `real_fraction` | **82/82** | the fraction as written (must NOT be flagged) |

`docnum_adjacent_amount` and `real_positional_amount` were added on 2026-10-16
after an audit reproduced both failures by hand; on the verifier before that day's fix they scored **0/2,921** caught
and **344/344 false positives**. The 文號 pattern admits CJK, so 「依…第72條及
內政部…第123號函,處九萬元」 swallowed the 條 citation and its claim scope
collapsed to nothing; and positional digits replaced each other, so 一〇〇〇〇
read as 0. A bare 「萬」 (數萬元) also read as 0 and now states no amount.
The two `*_multilist` kinds were added the same day: the 款 axis used to stand
down entirely on the 24 articles with more than one 款 list, so a 款 above every
one of them went unflagged (**0/24** before, **24/24** after). A 款 within range
there still reads as unverified, because which list it means is undecidable.

`docnum_before_citation` records a regression this branch introduced and then
caught in review. The first fix for `docnum_adjacent_amount` trimmed the 文號 to
start after any 條 citation it overlapped; with the 文號 written FIRST, the
following citation's name run starts inside it, the trim emptied it, and the
文號 vanished — the status line then read 「全數可回溯」 with an unverified 函釋 on
the page (**0/2,921** on that commit). The 文號 pattern now stops at 條 instead,
which fixes both orders without span arithmetic (**2,921/2,921**). The same
review found 「三四千元」「一兩萬元」 reading as 34,000 and 120,000 after the
positional-digit fix; two non-zero Chinese digits before a unit are now an
approximate range and state no amount.

The `real_*` kinds are the half that makes the other half mean anything: they
plant nothing and must come back unflagged, which is where a false-positive rate
of 0/2,921 comes from rather than from a checker that simply flags less.

**Also in every run, outside the twenty-two rows above:** `control` **2,921/2,921** (the correct-citation population
the 0/2,921 is measured on), `wrong_amount` **2,921/2,921**,
`bare_penalty_amount` **2,921/2,921**, `out_of_force` **2,921/2,921**,
`prose_prefix` **32/32**, `alias_typo` **2/2**, `fake_statute` **1/1** and
`prefixed_statute_control` **3/3** (parse-only positive controls for
`prefixed_statute`). `tests/test_published_numbers.py` checks every per-kind
figure the harness prints against this section.

**Still not covered.** The 項 axis is verifiable for 1,433 of 2,921 articles;
the other 1,488 are marked unverified because the official two-space indentation
was flattened during ingestion, so paragraph existence cannot be derived. The 款
axis is verifiable for 392; on the 24 whose 款 numbering restarts it catches
only a 款 above every list and marks the rest unverified.
Those are not failures being hidden — they are articles this claim does not
speak for.

**Blindspots: 21/25.** Twelve of sixteen originally-missed cases are now caught.
The four that are not — `modal_de_to_ying`, `modal_full_negation`,
`proviso_reversal`, `anaphora_tong_fa_20` — are all the same shape: the citation
is real, the article exists, the quote is close, and what moved is a modal (得 to
應, 得禁止 to 不得禁止) or an inverted proviso. No structural axis can see them.
They are marked `xfail(strict=True)` in `tests/test_verifier.py`, so if a later
change catches one the suite goes red and says so.

## §5 — What each harness refuses to measure

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

## §6 — Honest limits

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
  **Both now pass, and not because the score got better.** 2026-08-06 stopped
  asking a score whether 票據法 exists and asked the corpus instead — see the
  coverage veto in §6.1. The inflation is unchanged and still governs everything
  the veto's list does not name.
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
  tier (27/32) and premise (32/32) have not moved in any of the five. (27/32 is
  the tier before the 2026-08-06 coverage veto; it has read 29/32 since — §1.)
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

The dated entries that used to follow here — every round between 2026-07 and
2026-08-06, with its measurement and the limits it found — moved verbatim to
[`HISTORY.md` → "Honest-limits changelog"](HISTORY.md#honest-limits-changelog-through-2026-08-15).

### §6.1 — where the rows of §1 come from

Short provenance for the §1 rows whose full account is now in that changelog
(entry titles in quotes):

- **Semantic axis, 9/9 and 1,259/2,921.** The exam was widened from three
  hand-written actor swaps to nine, the six new ones each confirmed first to pass
  the pure-code verifier; on a live llama3.1 with `semantic_unreached` 0 the axis caught all
  nine and called 43% of correct citations wrong, superseding an earlier
  「10–30%」. "The semantic axis's exam had three questions…"
- **Golden set at temperature 0, k=8.** At grader temperature 0.2 identical code
  spanned 73.1–80.8% over five runs; one roll (81%) was published and retracted,
  and the grader is now pinned at 0. k=12 shipped on recall and coverage and was
  reverted when the precision harness priced it: 9.9 unexpected articles per
  session instead of 5.9, for 3 recovered expected ones. "The Tier-1 grader was
  rolling dice…", "k=12 shipped…", "The precision harness I said should come
  first…"
- **Honesty tier 29/32 and 18/20 · 2/15.** The 35-case probe showed the old score
  floor refusing only 5/20 out-of-scope questions while falsely refusing 2/15
  in-scope ones. A coverage veto — a closed list of statutes verified absent from
  the corpus — took that to 18/20 with 2/15 unchanged, and the golden-set tier
  from 27/32 to 29/32. "The honesty tier was wrong in BOTH directions…"
- **348/356 and 320/356.** Vocabulary table × dense index over the 168 sessions:
  348 with both, 320 with the table alone, 110 with dense alone, 55 with
  neither. `dense_fallbacks` exists because one command printed 348, 334 and 320
  within an hour as dense degraded silently. "The 1,843-line hand-written lexicon
  is not redundant…", "The recall harness could report a BM25-only number…"
- **69/168, 83/168, 168/168, 8 → 18 of 21.** After the model invented a deadline,
  periods are quoted verbatim from the retrieved articles by a rule-based rung
  (fires on 69 of 168); the ladder's first step names documents the user typed
  (83 of 168); every session gets a 存證信函 template whose 依據 lines are corpus
  text only (168/168); and retrieved articles the answer never mentioned are
  listed for the reader (8 → 17 of 21 expected articles visible), with
  period-bearing articles first (17 → 18). "Then the model invented a
  deadline…", "The first thing every reader was told to do…", "The 存證信函 rung
  pointed at a template…", "What the model skipped…", "Read end to end, the page
  contradicted itself."
- **50/60.** Shipped judgments are redacted to header + 主文, and 31 of the 386
  name a party inside the 主文 and ship header-only; first-listed judgment then
  states a sum 54/60 on the full local corpus and 50/60 on the shipped one. The
  published figure is the one a cloner gets. "Shipping the judgments cost four
  sessions their headline number…"
- **51/88.** Both sides derived with no hand labels — the session's family from
  its own expected articles via 民法's 編/章/節, the judgment's from the court's
  案由 — and perfect where the harvest is dense, poor where it is thin. "The
  reference judgment was never asked whether it is about the reader's problem…"
- **67% → 5%.** "The ablation was re-run instead of deleted…", and the second
  sample inside the honesty-tier entry.

## §7 — disputes that already ended, labelled by whoever decided them

Every harness above grades this system against expectations this project wrote.
The retriever and the answer key came from the same hand, so a high number can
only ever mean "consistent with itself". `evaluation/realworld.py` breaks that
loop: the cases are government dispute-resolution case tables, the input is the
party's opening description with the statute names stripped, and the article the
case turns on is the one the deciding body printed in its own 法令依據 column.

**臺中市公寓大廈爭議事件調處案例（113年）, 16 cases, 27 governing articles**

| what | first run | + 社區治理 rows | + second pass |
|---|---|---|---|
| governing article reached the window | 7/27 (26%) | 19/27 (70%) | **25/27 (93%)** |
| cases answered with NONE of them, no refusal | 9/16 | 1/16 | **0/16** |
| cases refused | 0/16 | 0/16 | 0/16 |
| dense fallbacks | 0 | 0 | 0 (hybrid fully participating) |

The first run's misses were not random. Everything physical hit — 漏水 (§10, §12),
外牆 (§10), 拒絕進入受檢 (§6). Everything about governance missed — 規約修訂,
決議效力, 委員選任連任, 管理費計算方式, 共用部分使用之特別約定. The vocabulary
table had been grown from noise, rental, labour and consumer sessions; nobody had
ever typed 「區分所有權人會議」 into it. So the fix was the same instrument as
2026-07-19: eight hand-curated 口語→法條 rows, every statutory phrase copied
verbatim from the article it points at.

**Every published number is unchanged, and that was not free.** Four triggers had
to be narrowed after measurement, each for the reason the table's own comments
already warned about — a word that names the counterparty rather than the dispute:

- `管委會` / `管理委員` fired in **9 of the 168 lived sessions**, in every one of
  them as the counterparty of a leak or noise complaint. Handing those sessions
  選任、解任、職務 cost 公寓大廈§10 its seat in a stairwell-leak case. Removed; an
  election dispute always names the election (遴選/連任/留任/改選).
- bare `決議` / `表決` pulled 公寓大廈§31 into a 社團總會 session and pushed out
  民法§56. Removed — but the same case showed the row was *incomplete*, not just
  over-broad: someone challenging a meeting needs the quorum rule **and** the
  article that lets a court set the decision aside, so 民法§56's own wording now
  rides in that row alongside §31.
- `佔用` displaced 民法§821 in a co-owned-land session. 共有物 and 共用部分 are
  different institutions and only the second is in this statute. Removed.
- bare `不配合` displaced 民法§821 as well (「對方不配合」). The refusal only means
  §6 when what is refused is entry for maintenance, so the trigger is now
  不願意配合 / 拒絕配合 / 拒絕進入 / 不讓進 / 不給檢查 / 不讓修.

After those four narrowings: `real_recall` **348/356**, per-case diff against the
pre-change table showing **zero lost and zero gained** (measured 3× in-process
plus once from a clean process — an earlier reading of 345 came from the broad
table, not from run-to-run noise); BM25-only **320/356** before and after, twice
each; golden_v2 **pass 19 / partial 7 / miss 0, 73% strict, tier 29/32, premise
32/32** — every figure identical to what was already published.

**The second pass, and the trade it exposed.** Ranking the eight remaining misses
first was the whole method: none sat in the dense top-3, so the reserved seats
could not reach them (N was swept to 3 on 2026-07-21 and N≥4 costs a golden case),
which left vocabulary as the only lever. Four targeted additions, each aimed at a
named case: §23's 「非經載明於規約者，不生效力」 and §10's 管理 clause moved into the
共用部分 row (apt-13 said 停車格/永久使用 and never said 規約; apt-01's committee was
exercising the 管理 power, not repairing anything); 分擔一半/各分擔/要我分擔 as
triggers plus §36's 「共有及共用部分之清潔、維護、修繕及一般改良」 in the fee row
(apt-05); and a new 樓地板/共同壁/龜裂/滲水/壁癌 row carrying §12 verbatim (apt-16).
漏水 was deliberately left out of that row — it is the most common word in these
sessions and already reaches §10/§12 on its own.

**One addition immediately broke another case, and the fix is the lesson.**
Widening the 共用部分 row with those two clauses knocked 公寓大廈§57 out of the
handover case (apt-06), turning a hit into the run's only silent miss. Reordering
the rows did not help — the expansion-order theory was wrong, and it is recorded
as wrong. The actual cause was the trigger: `公共設施` is also how a committee
describes what the DEVELOPER still owes it, so the shared-space clauses were
being handed to a handover complaint. Removing `公共設施` from that row (apt-13
still fires on 停車格/永久使用) restored §57 and took the run to **25/27, zero
silent misses**.

**What is still missed (2 of 27), so nobody reads 93% as done.** §48 in apt-03 is
the penalty article — a lay description of a dispute never resembles a schedule of
fines, and no honest trigger points at it. §10 in apt-12 is a window-budget
problem, not a vocabulary one: that case is labelled with three governing articles
(§6, §10, §12) and `DEFAULT_K` is 8 seats shared with everything else the query
pulls; two of the three now surface. Widening k would buy it and is refused here
for the reason `real_recall` prints every run — the window already carries 5.9
unexpected articles per session, and that cost is paid by the reader.

Every published figure is unchanged after both passes: `real_recall` **348/356**,
golden_v2 **pass 19 / partial 7 / miss 0, 73% strict, tier 29/32, premise 32/32**,
480 tests.

**The finding that matters more than the percentage.** A separate full-pipeline
run over 8 已結案 rental disputes (llama3.1, temperature 0) produced reasoning
that contradicted the recorded outcome in 4 of 8 cases — including one where the
court forfeited the tenant's two months' deposit while the answer said their
position held, and one where the answer said an electricity bill need not be paid
that was in fact paid in full. **`flagged_count` was 0 in all eight.** Nothing
malfunctioned. Every citation existed, was in force, and misquoted no figure, so
all four axes passed. The gates certify that a cited article is REAL; they have
never certified that it APPLIES, and the 11,904/11,904 figure is a measurement of
the former. Both statements were always true; this is the first run that shows
what the gap costs a reader.

**Held out: 25/27 was 93% on the cases it was tuned on. On 17 cases from the
same domain that nothing was ever tuned against, it is 52%.** 2026-08-15. Two
more government tables of the same kind were found and added — 臺北市公寓大廈爭
議事件調處委員會調處案例 (13 of its 14 cases) and 新北市公寓大廈爭議事件調處委員會
—調處案件參考 (4 of its 7). Both publish a per-case 法令依據 column, so the
labels are again the deciding body's and not this project's.

| set | cases | hit@k | silent misses |
|---|---|---|---|
| 臺中市 — **tuned on**, two vocabulary passes | 16 | **25/27 (93%)** | 0/16 |
| 臺北市 — held out | 13 | **8/19 (42%)** | 5/13 |
| 新北市 — held out | 4 | **4/4 (100%)** | 0/4 |
| held out, combined | 17 | **12/23 (52%)** | 5/17 |
| official pool, all | 33 | **37/50 (74%)** | 5/33 |

`dense_fallbacks` 0. **The published 25/27 is not withdrawn and is not wrong —
it is the number on that set. It is now labelled as what it always was: a
measurement taken after two rounds of vocabulary curation against those exact
16 cases.** 52% is what the same pipeline scores where no such round happened,
and it is the figure to quote about unseen disputes. This is the single most
informative row this file has ever carried, and the reason the split is stated
rather than the pooled 74%.

**Why the misses, which is more useful than the rate.** Three of the five
silent misses expect the SAME article — §10, 共用部分之修繕、管理、維護及其費用
分擔, the most-cited article in all three tables. It fails to reach the window
for 「管道間漏水費用分擔」, 「地下室停車場修繕動用社區基金」 and 「樓下寵物店空調造成
樓地板溫差」, each time under a window full of neighbours: §11, §12, §16, §33,
and in one case 民法's 連帶債務 block (§273–§282) end to end. A fourth expects
§29 for a committee-handover dispute and the window returns §20 — literally the
handover article, and arguably the better one, but the committee cited §29 and
relabelling to match the retriever is exactly what CONTRIBUTING forbids. The
fifth (「雙方都報備為主任委員」) expects six procedural articles at once and gets
§28/§29/§29-1/§55 — adjacent, none of the six.

**These cases are NOT being tuned on, and that is the point.** Curating
vocabulary rows until §10 surfaces would move 52% toward 93% and would destroy
the only held-out number in this file. Anyone tempted should read the row above
it first. If those rows are ever added, this table has to gain a THIRD set.

**No `outcome_direction` on the new 17.** The person who built these entries had
already read part of the disposition column while checking the PDFs' structure,
so direction coding on them would not be blind. Adding a non-blind set would
contaminate `--direction`; measuring their direction needs a coder who has not
read their outcomes. The gap is recorded in each source's
`why_no_outcome_direction` field rather than papered over.

**What this harness refuses to measure.** Whether the reasoning is right.
`--answers` prints the 分析研判 beside the recorded outcome for a human, and
scores nothing — the same refusal `golden_set.py` makes about legal correctness.

**The 4/8 above was one hand-read of one run. Blind-coded, it is 2/8 — and the
same measurement now exists on the EXTERNAL labels, where it is 3/16.**
2026-08-15. `python -m legal_agent.evaluation.realworld --direction`.
The old figure could as easily have been 2/8 or 6/8, and until it re-ran, no
change could be judged against it. It is re-runnable now WITHOUT auto-grading
legal reasoning, which this harness still refuses. Two blind codings and
arithmetic:

  1. the answers are generated (llama3.1:8B, temperature 0) into
     `evals/realworld_answers_run1.json`, which carries the opening description
     and the generated text and **deliberately no `real_outcome`**;
  2. they are coded from that file alone into `evals/realworld_answer_coding_run1.json`;
  3. the outcome side is coded from the case record afterwards, into
     `outcome_direction` in `evals/realworld_v1.json`;
  4. `compare_directions` counts.

The order is checkable rather than asserted: the commit adding the answer
coding touches no outcome field, and the outcome coding lands in a later one.
Nobody is ever asked whether they AGREE with an answer — both sides go into one
closed vocabulary (`asker` / `other_party` / `split` / `unclear`) and a value
outside it aborts the whole run, the same rule and the same reason as
`check_labels`. Every coded value carries the span it rests on, so a reader
checks the quote instead of trusting the coder.

| pool | opposed | same direction | at least one side non-committal |
|---|---|---|---|
| official — 臺中市公寓大廈, 16 cases | **3/16** | 7/13 | 3/16 |
| derived — 臺北市租賃, 8 cases | **2/8** | 4/7 | 1/8 |

**`flagged_count` was 0 on all five inversions, and tier was `normal` on all
five.** Sharper than the anecdote it replaces: the five cases that DID draw a
flag (apt-01, apt-11, apt-13, apt-15, apt-16 — 13 flags between them) and the
five that pointed the wrong way do not overlap at all. On this set the citation
check and the direction error are disjoint. That is what it means for four axes
to certify that a cited article is REAL and never that it APPLIES.

**This is the split the file complained about, closed.** hit@k was external
(公寓大廈, official labels) while direction was internal (租賃, labels this
project inferred) — direction had only ever been measured on the weakest label
in the set. It is now measured on both pools, reported separately, never pooled.

**Limits.** `unclear` is a real answer and stays available: 4 of 24 answers do
not commit (two contradict themselves inside one paragraph, one never reaches
the question asked, one refused at `tier=insufficient`), and forcing a coder to
pick a side there would manufacture the number. `split` against a committed
side counts as neither agreement nor inversion, which is why 同向 has a smaller
denominator than the case count. One model, one run, one coder — the coder is
the weak point and is stated as such: coding both sides in sequence is weaker
than two people, and only the ORDER (answers first, outcomes after) is
guaranteed here. Re-coding the answer side by a second hand is the obvious next
strengthening.

**Bad ruler, caught by its own guard.** The first draft labelled 民法 as
「中華民國民法」 (the corpus spells 刑法 that way, 民法 not) and published a
confident 1/9 that was almost entirely fake misses. `check_labels` now aborts the
run when a label names an article the corpus cannot contain, and
`tests/test_realworld.py` pins it. Third entry in this file's bad-ruler list.

**Limits of this measurement, stated before anyone quotes it.** One domain and 16
cases for the external number; the 8 rental cases carry labels this project
inferred from a narrative outcome, so they are reported separately and excluded
from the headline. Most recorded outcomes are mediated settlements, shaped by
goodwill and bargaining power rather than by law alone — that makes them a strict
yardstick for a legal answer, though the two decided in court are not.
Full-pipeline reasoning was read on one model, one run.

## §8 — the seat the user is sitting in

**2026-08-15. The owner brought a live dispute of his own and he is the party
being complained about. Everything on the noise path was written for the party
making the complaint, and the half that pointed the wrong way was the
deterministic half.** The full record, including the predictions written and
committed before the run, is `journal/2026-08-15-owner-noise-respondent.md`. It
is a journal entry and not an eval: n=1, unfinished, self-labelled, and — the
deciding reason — tuning vocabulary for a case and then scoring against that
same case is the 93%-then-52% loop in §7 rebuilt exactly.

Run end to end twice, `dense_fallbacks` 0, llama3.1:8B at temperature 0, corpus
at the shipping floor.

| predicted | measured |
|---|---|
| the analysis writes him as the complainant | **wrong** — it largely wrote him as the respondent (主張自己沒有製造, 證明自己沒有製造) and even said 對方的說法站得住 |
| the ladder hands him the complainant's actions | **right, including which rung it recommends** |
| §72's 不聽禁止 and §793's 但書 are never surfaced | **half wrong** — both reached the page verbatim, and neither was used as a condition the other side must still meet |
| no deadline appears | **right, for the predicted structural reason** — the noise ladder never called `_deadline_rung` |
| `flagged_count` 0, tier not `insufficient` | right, and as uninformative as §7 says: the five direction inversions there also had `flagged_count` 0 |

**The ladder is the finding.** With his sentence alone it recommended
報警(110) — to the person being complained about — with 社維法§72, the article
that fines him, printed as its 依據. With the same sentence filed into fields it
marked 管委會 and 報警 已嘗試 off his own words and recommended 調解, then
存證信函, then 民事訴訟, against the neighbour who had complained about him;
underneath, a 存證信函 template reading 請停止製造噪音 for him to send. **The
model's prose was the half that partly got his seat right. The escalation
ladder — pure Python, the layer this project forbids the model to touch — was
wrong in both runs and wrong identically.**

What shipped, and what each change cost:

- **the seat is asked and printed** (`triage.classify_stance`, `flow`). Inferred
  where the sentence says it, asked once in TRIAGE where it does not, re-read
  every turn so a later 不對,是鄰居投訴我 flips it. `MAX_INTAKE_TURNS` is still 3.
  The inference renders as 【本次假設】 above the answer, with the fields the
  answer never got — gaps alone read as 「you did not answer」, and the assumption
  line is the half that lets a reader see the tool in the wrong chair. Gaps come
  from `field_keys(ptype)` minus `collected_facts`, never from `asked_keys`,
  which is empty on the default smart path.
- **the respondent gets no escalation ladder** (`build_respondent_ladder`). Not
  an inverted one: there is no cheapest-first escalation for someone who is not
  asserting a claim, and inventing one so there is something to print is how the
  wrong-side ladder came about. He gets the conditions the retrieved articles
  state in their own words and the records he can keep, and the note says plainly
  why the ladder is absent.
- **a ban on 你沒事 verdicts** in `stage3.SYSTEM_PROMPT`, at the same level as the
  existing ban on the model stating periods. The reason is the statute: §72 fines
  不聽禁止者, so a reader who concludes the other side has not met the requirement
  and therefore ignores the next warning supplies the missing element himself.
  **It cost something, and the cost is recorded rather than buried: the golden
  run attaches reference judgments in 7/32 cases against 10/32 before, 3 with an
  award against 6.** That is the counts-only line, not a published figure, and it
  reproduced identically on a second run at temperature 0 — so it is the ban's
  effect, not harness spread. Everything scored stayed put: pass 19 / partial 7 /
  miss 0, tier 29/32, premise 32/32.
- **one vocabulary row** for the respondent's wording. Triggers are compounds
  only (被投訴, 投訴我, 說我太吵, 來勸導), never a bare 檢舉 — that word is also
  how a 勞資 or 消費 session describes going to the authority. The terms are the
  conditions the articles state themselves: 不聽禁止, 經制止而不遵從, 按土地形狀,
  each verbatim in the corpus. **The test a row must pass is whether it could be
  written by reading the statutes alone, before seeing any case** — §7 is what
  the other kind costs. After it: `real_recall` 348/356 with the window still
  8.0 sent / 5.9 unexpected, and `realworld` **byte-identical** to the run
  before, so the held-out 12/23 did not move. What it buys: on 我被投訴太吵,
  收到管委會的通知 all three governing articles now reach the window; §793 could
  not before, because its row keys on 樓上/樓下/隔壁/鄰居, none of which a
  respondent says.
- **the noise ladder quotes deadlines at all.** It ignored `retrieved` entirely,
  so the one scenario with a hand-built ladder was the only one that never
  surfaced a period. A respondent gets the same sentences under 對方主張權利的期
  間, not recommended and carrying no verdict either way.

**A coverage gap found while testing a presentation hypothesis, and the
hypothesis died.** 2026-08-15. The idea was that a respondent needs 實務見解
before 法律明文, so the three-section order should depend on the seat. The
premise did not survive the first query: **the corpus in force is 法律 2,856,
命令 65, 行政實務見解 1.** That single 行政實務見解 row is the 新北市 police
handling principle — the one document the hypothesis was built on IS the entire
population, so nothing can be tested and there would be nothing to reorder.

The direction has separate support, and it points at coverage rather than
presentation. Counting articles that contain any of 具名/指證/筆錄/限期/通知/舉發/
查證/會同/移送/報請:

| level | articles | with procedural wording |
|---|---|---|
| 法律 | 2,856 | 320 (**11%**) |
| 命令 | 65 | 22 (**34%**) |
| 行政實務見解 | 1 | 1 (n=1) |

Procedural rules — what an authority must do before it acts on someone — live
lower in the hierarchy, at roughly three times the density, and this corpus is
**2.2% 命令 plus one 實務見解 document**. The material a respondent needs most is
the material barely present. Adding it would pass the information-flow test
(「procedural rules live in 命令」 is a fact about the legal system, not about any
case), but **this entry is the whole of the work: the gap is recorded, not
filled.** Ingesting a new tier of sources is its own task with its own
measurement, and starting it here because it was noticed here is exactly the
scope creep this file exists to prevent.

### §8.1 — four measurements taken to check §8's own claims (2026-08-15)

All four are deterministic, no model, `dense_fallbacks` 0, corpus at the
shipping floor. Three of them weaken a claim made above rather than support it.

**44% of the headline recall arrives on a reserved seat.** Of the 348 hits in
`real_recall`, **153 (44%) enter the window at score 0.0** — placed by the
vocabulary table's reserved seat, with the lexical and dense channels both
scoring them zero. §8 said this about the owner's three articles; at corpus
scale it is nearly half the number. **So `hit@k 348/356` measures the retriever
and the vocabulary table together, and the vocabulary table carries a large
minority of it.** That is not a defect — reserved seats exist because BM25
cannot match 「跑跳」 to 「製造噪音」 — but the figure should be read as coverage of
the pair, not of retrieval.

*(The first run of this measurement reported 42% of 321 hits. It had
`dense_fallbacks` 168 — Ollama had stopped between harness runs, silently, for
the second time today. The number above is the re-run at 0. `AGENTS.md` trap 2,
in the wild, twice.)*

**The honesty tier is not miscalibrated; it is measuring something else.** The
five silent misses on the held-out set have top scores of 158 / 530 / 685 / 620
/ 702 against `MARGINAL_SCORE_THRESHOLD = 106.0` — retrieval matched something
extremely strongly, and the something was the wrong article. **No threshold can
separate a wrong 702 from a right 700, so recalibrating this statistic is not
expensive, it is impossible.** The limitation is narrower than 「the thresholds
were never validated externally」 and must be written as what it is:
`max(scores)` separates 「nothing matched」 from 「something matched strongly」 —
`honesty_probe` still refuses 18/20 out-of-scope questions on it — and cannot
separate 「the right article matched」 from 「a strong neighbour matched」. The
44% figure above compounds it: when the governing article rides a 0.0 seat, its
score contributes nothing to `max(scores)` at all.

**Window concentration does not separate them either — measured, then NOT
shipped.** The hypothesis was that a window packed with neighbours from one
statute marks the 「right topic, wrong article」 failure. On the 17 held-out
cases:

| | n | same-statute seats (mean) | range | contiguous run | top score |
|---|---|---|---|---|---|
| silent miss | 5 | 6.40 | 5–8 | 2.80 | 522 |
| hit | 12 | 6.58 | 5–8 | 3.00 | 790 |

The ranges overlap completely and the means differ by 0.2 of a seat. This route
is closed; no threshold was fitted on these 17 and none should be.

**The respondent vocabulary row cannot be validated by anything in this repo.**
Its triggers (被投訴, 投訴我, 說我太吵, 來勸導) fire on **0 of the 168 stored
sessions** — 0 hits and 0 false fires. The false-fire half is the good news and
matches `real_recall` not moving. The other half is not: the 29 sessions that
are respondent-shaped are all money and contract disputes (要我賠, 告我,
說我違約), and **not one stored session is a noise respondent**. So that row's
trigger side still rests on n=1, and no run available here can change that.
Stated rather than papered over with 「we ran a check」.

**Stance inference, measured on the same 168.** respondent 12, complainant 71,
**unknown 85 (51%)**. The 12 were read one by one and all 12 are genuinely the
accused side (對方要我賠修車費, 管委會告我欠管理費, 鄰居要我拆雨遮, 業者說我違約,
房東要扣清運費, 社工要我付安養費). Two respondent-shaped sessions were missed and
they share a shape — `old-card-debt` and `debt-sold-without-notice`, both people
being pursued for money, classified `complainant` because the loose 對方/他們
rows fired first. The 51% unknown is the cost of the generic partisan gate: on
those sessions the asserting rungs are withheld. A live session asks the
question instead, so the user-visible share is lower than 51% — but that is an
argument, not a measurement, and the measurement is 51%.

**Provenance of the 168, since it was called unrecorded.** It is recorded, in
`evals/HISTORY.md` §A6: 「six ordinary problems were typed into
`python -m legal_agent.run` and the whole transcript was read as a user reads
it」, and §A7 adds six more 「chosen to be things the assistant had never seen」.
The file entered at `c088587` (2026-07-25) with those six named. Two real gaps
remain: `real_recall.py`'s docstring still said 「nine problems」 for a file that
now holds 168 (fixed in this commit), and the sessions are the AUTHOR's own
wording typed as an ordinary person types — not external users, so 「real user
wording」 overstates it. They were also curated against: the 2026-07-31 commit
series is one vocabulary row per session whose window came back wrong. **That
makes 348/356 a tuned-on number in exactly the sense §7 spells out for 25/27.**

**What is still wrong, stated rather than fixed.** The three governing articles
reach his window on the lexicon's reserved seats at score 0.0 — BM25 and the
dense half both rank them below 民法§409 (贈與) and 消保法§17. Retrieval does not
find them; the vocabulary table carries them. And nothing here measures whether
the answer is right for him: this is one unfinished case with no outcome, and it
is not allowed to become a ruler.

## §9 — Measured, then NOT shipped

Each of these looked obviously right and lost on the numbers:

- **marking 「…者」 as a statutory condition.** §8 found the thresholds reaching
  the page and never being read as thresholds, and 「…者」 is how an article names
  the person a rule bites. **2,066 of the 2,921 articles in force carry it — 71%.**
  That is the register of Chinese statutory drafting, not a marker: highlighting
  seven articles in ten highlights nothing. 「但…不在此限」 shipped instead
  (`legal_agent/data/statute_text.py`), because it is delimited at both ends by
  the statute itself — 223 articles, and the 2 that carry 不在此限 without 但 are
  MISSED rather than mis-marked. Low recall was chosen deliberately there for
  `award_amounts`' reason: silence beats a wrong number, and the verbatim article
  is on the page either way.

- **asking the semantic axis a second, inverted question and flagging only when
  both agree.** The theory was that the false positives are the model being
  jumpy rather than genuinely reading a contradiction. On a 120-control sample
  it moved 38% → 31% while catch stayed 9/9 — the two framings AGREE on the
  false alarms, so there is no noise to cancel. A 31% false-positive rate is not
  a shippable checker either way.

- **ranking reference judgments by 案由 family** — derivable at runtime from the
  articles already retrieved, no LLM, and it would obviously raise the 51/88.
  That is exactly why it is not shipped: the harness scores by the same map, so
  the ranker would be graded on its own target and the number would rise without
  anything getting better. Shipping it needs a relevance signal the ranker does
  not consult.
- **making the award sort a tiebreak instead of the primary key.**
  `related_judgments` sorts by shared-article count and then re-sorts the whole
  candidate list by 「states an award」, so a case sharing one article with a sum
  outranks a case sharing three without one. Sorting award WITHIN each overlap
  group instead changes the first judgment in **10/146** sessions; all ten gain
  an article of overlap and all ten lose their award figure (93/146 → 83/146
  first judgments stating a sum). Inspecting the ten, the swaps are mixed —
  `inheritance-share` improves (不動產所有權移轉登記等 → 分割遺產),
  `money-left-with-friend` gets worse (返還不當得利 → 分割遺產). A published
  number down, an unpublished one up, on ten cases of mixed quality: not a win.

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
- **a narrow modal / proviso contradiction rule for the four blindspots no
  structural axis sees** (`_verb_suffix_contradiction`, which lived in
  `mutation.py`). It compared the last 「得/應/不得…之」 clause of a claim with the
  same-shaped clause in the source, and flagged a universal negation set against
  a 「但…不在此限」. Every mutation run printed 「規則存活:是,可提交」 because its
  gate was three sentences about 民法§793 that it had written itself, and its
  corpus sweep compared each article with itself. On the four cases it was
  written for — `modal_de_to_ying`, `modal_full_negation`, `proviso_reversal`,
  `anaphora_tong_fa_20`, each answer against its anchor article — it fired on
  **0 of 4**. It was never wired into the verifier; it was deleted (2026-10-16)
  rather than left printing a pass on every run.

## §10 — does each kind of dispute have a judgment to point at? (2026-10-20, backfilled 2026-10-21)

`judgment_relevance` grades the first judgment a page shows. This asks the
question before it: for each kind of dispute the 168 stored sessions bring, how
many shipped judgments are of that kind, and does a consultation about it get
one on the page at all.

```bash
python -m legal_agent.evaluation.judgment_coverage                     # this table
python -m legal_agent.data.fjud --fill                                  # fetch what is short (public site)
python -m legal_agent.data.judgment_backfill "$LEGAL_AGENT_HOME/fjud_cache/docs" --dry-run
```

**Family** is derived from the session's own expected articles
(`statute_family`, 民法's 編/章/節); a session can sit in two rows, and 38 of the
168 name no family (cross-cutting articles only) and are not in the table.
**附判決** = the page shows ≥1 reference judgment; **同類** = ≥1 of those shown
has a 案由 of the session's family. Both use `judgment_relevance`'s focus (the
answer cites the right law), so they are a ceiling. **庫存同類** = shipped
judgments whose 案由 names the family AND that cite an article of it — the only
ones the JOIN can bring to a page under that family. **待補** = short of 3, one
page's worth (`related_judgments` shows three).

Current state — 435 shipped judgments, the code at the end of §11, `dense_fallbacks` 0:

| 家族 | 諮詢數 | 附判決 | 同類 | 庫存同類 | 待補 |
|---|---|---|---|---|---|
| 侵權 | 12 | 12 | 10 | 92 | 0 |
| 勞動 | 12 | 11 | 10 | 7 | 0 |
| 承攬 | 11 | 9 | 8 | 8 | 0 |
| 繼承 | 11 | 11 | 9 | 15 | 0 |
| 委任 | 9 | 9 | 8 | 9 | 0 |
| 租賃 | 9 | 9 | 9 | 12 | 0 |
| 買賣 | 8 | 8 | 7 | 6 | 0 |
| 住戶 | 7 | 7 | 6 | 6 | 0 |
| 共有 | 7 | 7 | 3 | 5 | 0 |
| 所有權 | 7 | 6 | 4 | 21 | 0 |
| 監護 | 6 | 6 | 6 | 31 | 0 |
| 家暴 | 5 | 5 | 5 | 8 | 0 |
| 扶養 | 5 | 5 | 5 | 6 | 0 |
| 消費 | 5 | 5 | 0 | 0 | 3 |
| 不當得利 | 4 | 4 | 3 | 5 | 0 |
| 僱傭 | 4 | 4 | 0 | 0 | 3 |
| 婚姻 | 4 | 4 | 4 | 13 | 0 |
| 寄託 | 4 | 4 | 3 | 3 | 0 |
| 保證 | 3 | 3 | 2 | 3 | 0 |
| 消費借貸 | 3 | 3 | 2 | 20 | 0 |
| 使用借貸 | 2 | 1 | 1 | 3 | 0 |
| 擔保物權 | 2 | 2 | 1 | 3 | 0 |
| 親子 | 2 | 2 | 1 | 5 | 0 |
| 贈與 | 2 | 2 | 2 | 6 | 0 |
| 秩序 | 1 | 1 | 1 | 12 | 0 |

**23 of 25 families hold ≥3 same-kind judgments; the two short (6 in all) are
僱傭 and 消費, which no 案由 can name** (below). Before the backfill it was 15/25,
short 25. The rows that moved, before (386 judgments, base code) → now:

| 家族 | 庫存同類(補件前) | 待補(補件前) | 同類(補件前) | 同類(現在) |
|---|---|---|---|---|
| 承攬 | 5 | 0 | 6 | 8 |
| 委任 | 2 | 1 | 4 | 8 |
| 租賃 | 6 | 0 | 4 | 9 |
| 買賣 | 2 | 1 | 6 | 7 |
| 住戶 | 6 | 0 | 4 | 6 |
| 共有 | 5 | 0 | 4 | 3 |
| 不當得利 | 5 | 0 | 1 | 3 |
| 寄託 | 0 | 3 | 0 | 3 |
| 保證 | 0 | 3 | 0 | 2 |
| 使用借貸 | 0 | 3 | 0 | 1 |
| 擔保物權 | 1 | 2 | 1 | 1 |
| 贈與 | 0 | 3 | 0 | 2 |
| 秩序 | 0 | 3 | 0 | 1 |

By the route triage actually takes on the user's raw words (now):

| 分流 | 諮詢數 | 附判決 | 同類 |
|---|---|---|---|
| ambiguous | 74 | 66 | 38 |
| other:family | 21 | 21 | 19 |
| other:labor | 17 | 15 | 11 |
| other:rent | 16 | 16 | 11 |
| other:consumer | 11 | 10 | 4 |
| other:leak | 8 | 8 | 6 |
| other:safety | 7 | 7 | 7 |
| other:traffic | 6 | 6 | 4 |
| noise | 5 | 5 | 5 |
| other:space | 2 | 1 | 1 |
| other:threat | 1 | 1 | 1 |

What the table says, read plainly:

- **Two of the zeros are the instrument, not the corpus.** No 案由 can be read
  as 僱傭 (「確認僱傭關係」 is mapped to 勞動) or as 消費 (consumer disputes are
  filed as 買賣/返還價金), so those rows are 0 whatever the corpus holds, and the
  backfill skips them and says so. Merging 僱傭 into 勞動 on the session side
  would be the obvious fix, and it would raise `judgment_relevance`'s own
  number by re-drawing its grader; it was not done.
- **Four families had no 案由 keyword at all** — 使用借貸, 寄託, 保證, 秩序.
  Keywords were added (返還借用物/使用借貸, 寄託, 保證債務/連帶保證, 社會秩序維護法)
  before any shipped judgment carried them; the backfilled ones now do, and a
  test holds that each reads as its keyword's family.
- **秩序's stock is 12, not 3**: 9 of them came in for §11's acceptance set,
  which asks about 社維§72/§87 specifically (the family fill alone took three
  §63/§66 rulings, which answer neither question).
- 附判決/同類 above are with `dense_fallbacks` 0 (Ollama + bge-m3 in this
  environment). The before column was re-measured the same way; it reproduces
  the published `judgment_relevance` 146/168 and 51/88 exactly.

### How the backfill got done

**First attempt (2026-10-20 10:00 Asia/Taipei): blocked.** `judgment_backfill` was written
and tested, but the 司法院 hosts are not reachable from the environment this
was measured in — the outbound proxy answered `CONNECT data.judicial.gov.tw:443`
with `403 Forbidden`, body 「request blocked: no rule or allowlist entry allows
host "data.judicial.gov.tw"」, and the same for opendata.judicial.gov.tw,
judgment.judicial.gov.tw, law.judicial.gov.tw and www.judicial.gov.tw. There
were also no API credentials, and the run was at 10:00 Asia/Taipei, outside the
API's 00:00–06:00 window. No judgment was added.

**Second attempt, 2026-10-21 01:17 Asia/Taipei, with outbound network open.**
The hosts are now reachable, but both sources need an account, and none was
registered:

- `GET https://opendata.judicial.gov.tw/api/Datasets?categoryTheme4Sys=051`
  → 200. 裁判書 is 369 datasets, one RAR per month from 199601 to 202608
  (the newest re-issued 「20261016Update」, e.g. 202608 = datasetId 59372,
  fileSetId 72011), plus a `Delete-Infor` CSV (fileSetId 72012). Columns as
  published: ID、JYEAR、JCASE、JNO、JDATE、JTITLE、JFULL、JPDF. Every one is
  `categoryDataset: "B"`; the site's own front end renders the download link
  only when `"A"===categoryDataset || isLogin`, and login sits behind a
  Cloudflare Turnstile.
- `GET /api/FilesetLists/72011/file` (and 72012, and `?preview=true`) → 500,
  `{"succeeded":false,"message":"Entity \"GetFilesetListFileQuery\" (72011) was not found."}`;
  `GET /api/Datasets/59372` and `/59005` (199601) → 500, the same 「not found」.
  As a control, a category-A dataset on the same host (6876, fileSetId 8322)
  answers 200 and serves its 950,580-byte file, so the endpoint works and the
  refusal is the B category. `GET /api/MemberData` → 401.
- `POST https://data.judicial.gov.tw/jdg/api/Auth` with a dummy user → 200,
  `{"error":"驗證失敗"}` — the API host now answers (the 403 is gone, and this
  was inside the 00:00–06:00 window), but it needs `JUDICIAL_USER` /
  `JUDICIAL_PASSWORD`, and neither is set here. `GET /` on that host is an IIS
  403 from the origin, not the proxy.

**Third attempt (2026-10-21): the public search site, no account.**
`https://judgment.judicial.gov.tw/FJUD/` — the same court's 裁判書查詢 — serves
its 進階查詢 form and each judgment's full text to anyone. A bare client is
refused by its bot defence (「The requested URL was rejected by bot-defense」);
the headers a browser sends are enough. `data/fjud.py` submits 案由 (and, for
§11, an article number as a full-text term), walks the result pages newest
first, and turns each result page into the importer's flat record, so
`judgment_backfill`, `parse_judgment` and the redaction are unchanged. It
waits ≥3 s between any two requests (not lowerable), caches every list page
and document under `LEGAL_AGENT_HOME`, and a re-run resumes from the cache.

- Family fill: 68 requests, 19 judgments — 使用借貸/保證/寄託/秩序/贈與 3 each,
  擔保物權 2, 委任/買賣 1 — exactly the shortfall. 秩序 takes 裁定 as well as
  判決: 社維法 cases are decided by 裁定 (社會秩序維護法§45).
- Situation fill (§11): 57 requests, 30 more.
- Redaction found two holes on the way and both are closed: a 社維法 ruling
  names its person as 被移送人 (not a role the party reader knew), and a 保證
  judgment's 主文 named a 訴外人. Either would have shipped a full name; 5 of
  the 49 now ship header-only. The 386 already shipped are byte-identical.

## §11 — judgment citation acceptance set: are the judgments shown the ones that should be? (2026-10-21)

```bash
python -m legal_agent.evaluation.judgment_qa                                  # 38 questions, tuned on
python -m legal_agent.evaluation.judgment_qa evals/judgment_qa_holdout_v1.json # 12 questions, held out
```

`evals/judgment_qa_v1.json` is 38 plain-words questions over 22 dispute
families, each with the articles a careful person expects and the judgments the
page should cite. Those judgments are not hand-picked: `expected_for` lists every
shipped judgment whose 案由 is the question's family AND that cites one of its
articles, and the list is frozen into the file (a test re-derives it). The
held-out file is 12 more questions over the same families, written before any
fix in this section and never run while choosing one.

Every judgment shown is graded, not just the first:

- **引用正確率** — shown judgments on the question's list / all shown;
- **命中** — questions with ≥1 listed judgment among those shown;
- **答非所問** — questions whose page shows judgments, none of the question's
  family (the reader is pointed at another kind of dispute);
- **無判決** — questions whose page shows none.

`focus` = the answer cites the right law (the expected articles that reached the
window — what stage3 passes when verification clears the answer); `window` =
the answer cites nothing verifiable and stage3 falls back to the whole retrieval
window. All runs: `dense_fallbacks` 0, every stage graded against the same
frozen lists; a second run of the final code is byte-identical (the harness has
no model in it, so its spread is zero).

**Tuned on (38 questions)**

| stage | judgments | focus 引用正確率 | 命中 | 答非所問 | 無判決 | window 引用正確率 | window 答非所問 |
|---|---|---|---|---|---|---|---|
| before | 386 | 18/63 (28.6%) | 11/38 | 17/38 | 10/38 | 9/92 (9.8%) | 21/38 |
| family backfill (§10) | 405 | 29/72 (40.3%) | 17/38 | 10/38 | 9/38 | 18/94 (19.1%) | 14/38 |
| fix 1: situation backfill | 435 | 48/95 (50.5%) | 23/38 | 10/38 | 4/38 | 29/103 (28.2%) | 14/38 |
| fix 2: lexicon rows | 435 | 72/100 (72.0%) | 33/38 | 3/38 | 2/38 | 39/112 (34.8%) | 9/38 |
| fix 3: same-kind first | 435 | **87/100 (87.0%)** | **35/38** | **0/38** | 2/38 | 54/112 (48.2%) | 3/38 |

**Held out (12 questions)**

| stage | judgments | focus 引用正確率 | 命中 | 答非所問 | 無判決 | window 引用正確率 | window 答非所問 |
|---|---|---|---|---|---|---|---|
| before | 386 | 1/23 (4.3%) | 1/12 | 8/12 | 3/12 | 1/32 (3.1%) | 10/12 |
| family backfill (§10) | 405 | 8/30 (26.7%) | 4/12 | 6/12 | 2/12 | 6/33 (18.2%) | 6/12 |
| fix 1: situation backfill | 435 | 8/30 (26.7%) | 4/12 | 6/12 | 2/12 | 7/33 (21.2%) | 6/12 |
| fix 2: lexicon rows | 435 | 20/32 (62.5%) | 10/12 | 1/12 | 1/12 | 18/36 (50.0%) | 2/12 |
| fix 3: same-kind first | 435 | **27/32 (84.4%)** | **11/12** | **0/12** | 1/12 | 23/36 (63.9%) | 1/12 |

Without a dense index (a plain `pip install`), the final code reads 87/100,
35/38, 1/38 tuned and 22/29, 10/12, 0/12 held out (focus).

**Which causes, in which order.** Every miss gets one cause. After the family
backfill (405) the tuned set's misses were: 語料無應引判決 10 · 檢索漏條文 8 ·
被擠出前三 2 · 引錯家族 1. The fixes take them from the top:

1. **語料無應引判決 (the corpus has no judgment for the situation).** Ten
   questions' families had judgments, but none citing the question's own
   article (a 租賃 stock of 修繕 cases does not answer 押金). `fjud --qa` asks
   the site for the family's 案由 plus the article number as a full-text term
   and keeps only records that serve the family AND cite one of the
   question's articles: 30 judgments, 57 requests. This fixes its own metric
   by construction — the honest gain is what it unblocks: the misses it
   cleared turned out to be mostly 檢索漏條文 (12 after it).
2. **檢索漏條文 (the expected article never reached the window).** Five
   contract types' definition articles (使用借貸, 保證, 贈與, 抵押權, 寄託 of
   money) plus 委任 reporting, 承攬 payment and 社維§72① were unreachable from
   plain words, so stage3 fell back to the whole window and showed other
   disputes. Eight lexicon rows, triggers in general words. One cost a real
   session: 「也沒有當保證人」 fired the 保證 row, and §745/§749 attached to it
   pushed §739 out of `adult-son-owes-money` (real_recall 347 → 346); §745 and
   §749 now have triggers of their own and the session is back to 2/2.
3. **引錯家族 (a judgment of another kind ranked first).** `related_judgments`
   ranked by overlap, then by stating a sum, blind to whether a §179 judgment
   is 返還不當得利 or 給付修繕費. Among equal overlap, a judgment whose 案由 is
   the same kind as an article it shares now goes first, and keeps its seat
   against the sums-first sort.

Remaining misses (final, tuned, focus): 被擠出前三 2 — both are pages with NO
judgment, because focus narrows to an article no listed judgment cites
(`deposit-money-relative`: the window holds §603, the two listed cite §602;
`ownership-encroach`: §796, the 19 listed cite §767) — and 檢索漏條文 1
(`mortgage-cancel-paid`: neither §860 nor §767 reaches the window; it shows a
拍賣抵押物 ruling). Held out: `ho-loan-use-scooter`, no judgment shown.

**Every other published number, same environment, `dense_fallbacks` 0:**

| harness | base code, 386 | base code, 435 | final |
|---|---|---|---|
| `real_recall` | — | 347/356 | 347/356 (published 348/356 is from another machine; base reads 347 here) |
| `honesty_probe` | 18/20 · 2/15 | 18/20 · 2/15 | 18/20 · 2/15 (output identical) |
| `judgment_relevance` | 51/88 (58%), 146/168 carry one | 65/99 (66%), 156/168 | **107/118 (91%)**, 156/168; generic 案由 58/146 → 38/156 |
| `judgment_coverage` | 15/25 families, 25 short | 23/25, 6 short | 23/25, 6 short (僱傭, 消費 only) |
| `mutation`, `--retrieval-first`, `blindspots`, `qualifier_audit` | | | output identical to base |

**Read the 91% with this in mind.** Fix 3 ranks with the same 案由→family
table `judgment_relevance` grades with (it moved to `retrieval/families.py` so
the library no longer imports from a harness), and `judgment_qa`'s expected
lists are drawn with it too. The grader and the ranker therefore agree by
construction on what 「same kind」 means; the rise from 66% to 91% is the ranker
learning the grader's definition, not independent evidence that a reader is
better served. The table is coarse: `upstairs-leak` now counts as a match with
a 損害賠償(交通) judgment, because both are 侵權. No session went from match
to mismatch, and 共有's 同類 in §10 went from 4 to 3.

What none of this measures: whether a judgment shown is the same SITUATION.
A 返還寄託物 case about a warehouse and one about cash are both 「寄託」.

## More

[`HISTORY.md`](HISTORY.md) — how each number was arrived at: the three defect
classes that started at 0%, the data bug the exam caught before a human did, and
the week the insufficiency gate was dead. ·
[`golden_v2.json`](golden_v2.json) · [`real_sessions.json`](real_sessions.json) ·
[`README.md`](README.md) — case schema and provenance.
