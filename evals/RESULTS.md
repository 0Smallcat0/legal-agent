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

## Reproduce

```bash
python -m pytest -q                                                    # 180 tests
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
