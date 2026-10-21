# Changelog

Numbers here are copied from [`evals/RESULTS.md`](evals/RESULTS.md), which stays
the single source; each entry names its section. How the project got to 0.1.0 is
told in [`evals/HISTORY.md`](evals/HISTORY.md).

## 0.2.0 — 2026-10-21

The first version with a changelog, covering everything since `23906c0`
(2026-08-17). It is the release in which the public demo answers the question
people bring most — does my position hold up (16 of 33 questions sampled from
PTT) — instead of saying it has no model: 分析研判 is written by Qwen2.5-7B on
ZeroGPU, and every citation it makes is still checked by code afterwards. Around
that, the stance question is read the way it is offered (32 of 33 replies, from
10); the court judgments shown beside an answer are ones the question should cite
(87%, from 28.6%; 84% on twelve questions held out); 49 more judgments come from
the public 裁判書查詢 site; the checker grades itself on 24 kinds of planted error
instead of 17; and CI gates that could never fail now can.

### Added

- **分析研判 on the public Space** (RESULTS §12). `dialogue/hf_llm.py` runs
  `Qwen/Qwen2.5-7B-Instruct` through transformers inside `@spaces.GPU`, and
  retrieval's dense half embeds with `BAAI/bge-m3` through sentence-transformers
  (the `space` extra). Both switch on from `SPACES_ZERO_GPU` alone; locally
  Ollama stays the default and nothing changes.
  - Measured locally on golden_v2 at temperature 0, same pipeline: **7 of 241
    citations flagged (2.9%)**, against llama3.1's 27 of 325 (8.3%). Each
    model's run reproduced byte for byte.
  - The sentence-transformers embedding reads the same as Ollama's:
    `real_recall` 348/356, `honesty_probe` 18/20 · 2/15.
  - On the Space: 593 tokens in 15.6 s, all three citations traceable.
    `GPU_SECONDS` is 60, which allows an unauthenticated visitor two answers a
    day.
- **The bare model, measured** (RESULTS §12.1). `ablation --conditions bare
  --official` checks every citation of a model asked with no pipeline against the
  11,803 laws and regulations of the 全國法規資料庫 open data. qwen2.5:7b, one
  sample at temperature 0: **30 of 231 citations name a law that does not
  exist** (「噪音防制法」 13 times; the law is 噪音管制法). Gated, a nonexistent law
  never reaches the page unflagged. Runs save per question and resume;
  `--from-json` re-buckets a saved run without calling the model.
- **49 judgments from the public 裁判書查詢 site** (`legal_agent/data/fjud.py`,
  RESULTS §10–§11): no account, at least 3 s between requests with no setting to
  lower it, cached under `LEGAL_AGENT_HOME` so a rerun resumes. Shipped judgments
  386 → **435**; dispute families with at least three same-kind judgments
  15/25 → **23/25**.
- **A judgment citation acceptance set** (RESULTS §11):
  `evals/judgment_qa_v1.json`, 38 questions, and
  `evals/judgment_qa_holdout_v1.json`, 12 questions written before any fix and
  never tuned against. The judgments each question should cite are derived by
  rule and frozen in the file; a test re-derives them.
- **Seven seeded-error kinds** (RESULTS §4): 17 → **24**, each at 100% with
  0/2,921 false positives. Among them `docnum_adjacent_amount`, 0/2,921 caught
  before its fix, and `real_positional_amount`, 344/344 false positives before
  its fix.
- **Eight vocabulary rows** for articles plain words never reached: the
  definitions of 使用借貸, 保證, 贈與, 抵押權 and money left in 寄託, plus 委任
  reporting, 承攬 payment and 社維§72①.

### Changed

- **Which judgments are shown** (RESULTS §11). Among equal article overlap, a
  judgment whose 案由 is the same kind as an article it shares goes first. With
  the backfill and the vocabulary rows, on the 38 questions: judgments shown that
  the question should cite **18/63 → 87/100**, questions given at least one
  11 → 35, pages pointing the reader at another kind of dispute 17 → **0**. Held
  out: 1/23 → **27/32**, 1 → 11 of 12, and 8 → 0.
- **The stance answer is read as offered** (RESULTS §8.2). 「對方在向你要求」, the
  question's own second option, used to put the visitor in the opposite seat.
  Money demanded *of* the reader (向我要, 跟我要, 要我…還/付/賠/退) is now checked
  first, and the reply right after the question can answer by position (前者 /
  後者). On a 33-reply probe **10/33 → 32/33, reversed 4 → 0**; on the 168 stored
  sessions, seat unknown 85 → 71, all 21 changed seats read one by one.
- **The 存證信函 quotes its three 依據 and no period.** It used to append the first
  period found anywhere in the window, which for 退租押金 told the landlord about
  合夥人退夥 (民法§686). A period reached the letter in 68 of 168 sessions and was
  an expected article in 11.
- **The answer is what follows the last `</think>`**, so a model that reasons in
  the open no longer puts the prompt's own rules on the page.
- **The heading gates read markdown headings** (RESULTS §12). The gate that moves
  model prose out from under 法律明文 matched `**法律明文**` only and never ran on
  `### 法律明文`; an empty 實務見解 heading is written back as 「(無)」, only when no
  函釋 or 行政實務見解 was retrieved. Qwen answers with all three headings
  20/27 → **26/27**.
- **The README is one page**: the method, and three numbers with what each does
  not say. `evals/RESULTS.md` went from 2,218 to about 830 lines with one table
  of current numbers; the dated log moved verbatim to `evals/HISTORY.md`.

### Fixed

- **CI gates that could not fail.** Tests ran before the corpus was built, so the
  6 comparing published numbers with the corpus always skipped (0 skipped now,
  also from an empty `LEGAL_AGENT_HOME`). The retrieval-first mutation step piped
  into `tee` without `pipefail`. `qualifier_audit` run outside the repo root read
  2,923 sources instead of 6,407 and still exited 0. Four mutation kinds could
  generate zero cases while the run read 100%.
- **The citation checker.** A 文號 written right after a 條 citation swallowed it
  and switched the amount check off; positional digits (一〇〇〇〇) read as 0; a
  bare 萬 (數萬元) read as 0; on the 24 articles with more than one 款 list the 款
  axis stood down entirely (0/24 → 24/24).
- **Loading and retrieval.** One harvested judgment in the table stopped all 386
  shipped ones from loading; `python -m legal_agent.retrieval.dense` crashed on a
  fresh home; `retrieve(k=0)` returned the whole window.
- **The consultation.** Every respondent was told 「有人反映你這邊太吵」, a landlord
  in a deposit dispute included; 20 of 29 checklist fields printed raw keys;
  manual mode printed 「請呼叫 advance_to_stage3()」.
- **The Space's first deploy** failed every model call with
  `No CUDA GPUs are available`: one sentence-transformers forward pass in the
  main process left every forked GPU worker without a card. The embedding now
  runs in its own process (`retrieval/st_worker.py`), its vectors bit-identical.
- **Redaction** missed 被移送人 in 社維法 rulings and 訴外人 named in a 主文. Both
  are covered; the 386 judgments already shipped are byte-identical.

### Removed

- About 2,600 lines of code nothing called, each checked by grep: the hand-entry
  `cli.py`, `evaluation/hallucination_check.py`, `prompts/`, `models.Judgment`
  and `models.SourceHierarchy`, and the mutation "B6 sweep", which printed
  「規則存活:是,可提交」 on every run and fired on 0 of the 4 cases it was written
  for.
