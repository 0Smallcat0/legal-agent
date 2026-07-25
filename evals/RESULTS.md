# Measured results — 2026-07-10

Environment: local, zero paid API. Models via Ollama on an RTX 4060 (8 GB);
corpus = the 11-entry hand-verified 住宅噪音 reference corpus; golden set =
[`golden_noise_v1.json`](golden_noise_v1.json) (25 cases).

**Closed-world caveat** (applies to every table): "unverifiable / corpus 查無"
means *not traceable to this corpus* — which is exactly the promise the system
makes ("every citation must be verifiable back to the corpus") — it does NOT
claim the statute doesn't exist in the real world.

---

## 0. Corpus v2 (2026-07-18) — 11 → 2 561 articles, and what the numbers did

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

## 1. Verifier mutation test — catch rate on planted errors

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

## 2. Tier-1 golden set — llama3.1 8B through the full gated pipeline

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

## 3. Honesty-threshold calibration

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

## 4. Ablation — bare (憑記憶引用) vs gated (五閘門), per model

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

## 5. 判決參考層 — what the harvested judgments actually buy (2026-07-23)

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

## 6. Six lived sessions — what USING it exposed (2026-07-25)

Everything above measures the system against sets the system was built for.
This section is what happened when six ordinary problems were typed into
`python -m legal_agent.run` and the whole transcript was read as a user reads
it: 押金不退, 房東不修漏水, 打工加班費, 機車車禍, 網購瑕疵, 樓上小孩跑跳.

Six sessions produced **eleven distinct defects**, of which the two most
serious were in the guardrail itself.

### 6.1 The verifier was wrong in both directions

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

### 6.2 Retrieval — the vocabulary gap was worse than the lexicon could fix

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

### 6.2b What the full pipeline did after all of it (real llama3.1 8B, 30 cases)

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

### 6.3 The rest of what the transcripts showed

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

## 7. Round two — the honesty floor had been dead for a week (2026-07-25)

Six MORE lived sessions, chosen to be things the assistant had never seen:
資遣費, 房東擅自進房間, 車禍對方受傷求償, 前男友騷擾, plus two deliberate
out-of-corpus probes (商標搶註, 虛擬貨幣課稅).

### 7.1 The worst failure this project has shipped

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

### 7.2 Three more vocabulary gaps, one of them safety-critical

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

### 7.3 Two bugs inside the promotion mechanism itself

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

### 7.4 The web demo had never been used either (2026-07-25)

Twelve lived CLI sessions, zero web sessions — and the Gradio tab is the front
door AND a different code path: it runs the RULE-BASED intake (model-free by
design, so it works on HF Spaces free CPU), so none of §6.3's intake work
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

---

## Reproduce

```bash
python -m pytest -q                                                    # 236 tests
python -m legal_agent.evaluation.mutation                              # full-corpus catch rate
python -m legal_agent.evaluation.golden_set evals/golden_v2.json       # golden v2 (30 cases)
python -m legal_agent.evaluation.calibrate evals/golden_v2.json        # threshold sweep
python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json --models llama3.1:latest qwen3:latest --out evals/ablation_raw.json
```

(Tables 2–4 above are the 11-article-era baselines and still reproduce
against `evals/golden_noise_v1.json`; §0 records what moved at corpus v2.)

Raw per-run ablation data: [`ablation_raw.json`](ablation_raw.json).

**Ollama note (measured 2026-07-21):** the golden/ablation runs drive a local
Ollama for both embeddings (bge-m3) and generation (llama3.1). On an 8 GB GPU
the default single-resident-model setting swaps the two models on every case —
two runs aborted on the 180 s client timeout that way. Start the server with
`OLLAMA_MAX_LOADED_MODELS=2` and load bge-m3 *before* llama3.1 (small model
first fits both); a clean 30-case run then takes ~10 minutes.
