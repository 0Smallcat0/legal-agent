# Legal Agent — Engineering Specification

> Jurisdiction-agnostic engine; this document specifies the **Taiwan (R.O.C.)** reference implementation.

> **Document purpose**: This is a build specification for an AI coding tool (Claude Code / Codex). It defines *what to build* and *why*, module by module. Technical scaffolding is in English; Taiwan-specific legal content (statute names, legal terms, intake scripts) is kept in Chinese on purpose — translating it would introduce distortion and cause the retriever to fetch the wrong material.

---

## 0. Project Definition & Scope

### 0.1 What this is
A **personal-use** legal assistant for **Taiwan (R.O.C.) law**. Single user (the owner). Not a commercial product, not a multi-user service.

### 0.2 What "goal" means here
The realistic goal is: *"When I hit a legal problem, get me to ~80–90% understanding on my own before deciding whether to pay for a lawyer."*

**Explicitly NOT a goal**: replacing a courtroom lawyer, giving legally binding advice, or handling arbitrary Taiwan law across all domains. The system must always keep a **referral exit**: for complex / high-stakes matters it tells the user to consult a real lawyer.

### 0.3 Why personal-use simplifies the build
Because output is consumed only by the owner (not distributed to third parties):
- No 律師法 (Attorney Act) unauthorized-practice exposure.
- No licensing / redistribution obligations from data sources (see §1.4).
- No personal-data (個資) risk from showing judgment texts.

**Important caveat**: personal-use does NOT make the AI more accurate. Hallucination, statute-timeliness, and mis-classification are model-level problems independent of who consumes the output. The owner *will* make real decisions (call police? send a demand letter? sue?) based on this tool, so accuracy controls (§2) remain mandatory.

### 0.4 Build tool vs. runtime model (do not conflate)
- **Build/dev tool**: Claude Code / Codex — used to *write* this system.
- **Runtime reasoning model**: **Anthropic API** (Claude) — called by the agent at inference time to do legal reasoning.
- These are different layers. The dev tool is not a runtime dependency. Runtime requires its own Anthropic API key (usage-billed; personal-use volume is negligible).

---

## 1. Data Layer (build this FIRST — everything else stands on it)

### 1.1 Why first
Retrieval retrieves *from* this layer; the anti-hallucination verifier validates *against* this layer. With no reliable data layer, every layer above is castles in the air.

### 1.2 Primary sources (Taiwan)

**Statutes → 全國法規資料庫 (law.moj.gov.tw)**
- Has a "公開資料下載" area providing XML/JSON.
- Access requires an application (帳號/密碼) approved by 法務部, non-exclusive license.
- Structured fields already available: 法規名稱, 類別, 最新異動日期, **生效日期**, 廢止註記, **沿革內容**, 條號, 條文內容.
- `生效日期` and `沿革內容` are the fields that make timeliness possible — treat them as critical.
- Reference: third-party project `kong0107/mojLawSplit` splits official XML into small JSON (useful format reference).

**Judgments → 司法院資料開放平臺 (opendata.judicial.gov.tw)**
- Two APIs: one returns the list of judgment changes in the last 7 days; one returns a single judgment by JID.
- Daily-updated data retains only the most recent ~2 months.

### 1.3 Three traps (must design around these)

1. **The statute DB is incomplete.** Many 行政規則 / 自治條例 / 自治規則 are NOT in 全國法規資料庫. Pre-2018 historical versions only cover command-level (命令) rules; statute-level (法律) history must be pulled separately from 立法院. → For the noise scenario, central statutes are fine, but **local 自治條例 (e.g. some cities' own noise/pet rules) may be missing**. The system must be honest when a locality-specific rule might exist but isn't in the corpus.

2. **Judgment text is poorly structured.** Official judgment data is semi-structured, badly formatted. Parsing out 爭點 / 引用法條 / 主文 / 理由 is itself an NLP task, not a given.

3. (Commercial licensing traps exist but are **out of scope** for personal use — see §0.3.)

### 1.4 Data model (the core architectural decision)

This is NOT a flat document store. It is a **time-versioned, hierarchy-aware knowledge base.** Three core tables:

**`statutes` (time-sliced — this is the #1 thing most first builds get wrong)**
```
statute_id        # e.g. "民法"
article_no        # e.g. "第793條"
content           # 條文內容 (verbatim, Chinese)
effective_from    # 生效日
effective_to      # 失效日 (null = currently in force)
hierarchy_level   # 憲法 > 法律 > 命令 > 函釋
source_url
```
Primary key is effectively `(statute_id, article_no, effective_from)` — a **time slice**, not just an article number. Rationale: statutes get amended; the system must be able to answer "for a dispute that happened in 2023, which version applied?" Missing this is how systems end up citing repealed articles.

**`judgments`**
```
jid
court
year              # 年度
case_type         # 案由
issues            # 爭點        (parsed)
cited_articles    # 引用法條     (parsed → enables "find all judgments citing 民法第793條")
holding           # 裁判要旨
full_text
```

**`source_hierarchy`**
Ranks each source's authority (憲法 > 法律 > 命令 > 函釋). Used at reasoning time so that when a statute and a 函釋 conflict, the system knows which wins.

### 1.5 Build strategy: small-and-accurate, single scenario first
Do **NOT** build the full corpus first. For the initial scenario **住宅噪音糾紛 (residential noise disputes)**, manually scope the relevant sources:
- 民法 相鄰關係 relevant articles (e.g. 第793條, 第800-1條)
- 噪音管制法
- 社會秩序維護法 第72條
- 公寓大廈管理條例 relevant articles
- ~dozens of relevant judgments

Volume small enough to **human-verify every article's correctness and timeliness.** Get the full pipeline (retrieval → anti-hallucination → dialogue) working on this small accurate corpus, prove it works, THEN tackle full-corpus / auto-update as separate heavy engineering.

---

## 2. Anti-Hallucination Layer (the technically strictest part)

### 2.1 The reality that sets the strictness bar
2025 Stanford study measured hallucination rates on *professional* legal AI tools: Lexis+ AI ~17%, Westlaw AI-Assisted ~33%, GPT-4 ~43%. General-purpose LLMs on legal tasks: 58–80%. These are funded commercial products WITH RAG. Conclusion: zero-error is impossible; the achievable goal is **"when it errs, the user knows."** Therefore every mechanism below is tuned to the **most conservative** setting — non-negotiable.

Core principle: **the model may not cite statutes from memory. It may only cite what was retrieved, and every citation must be verifiable back to the corpus. Anything not traceable is not said.**

### 2.2 Mechanism 1 — Retrieval-first, no bare answers
Flow is forced: user question → retrieve relevant statutes/judgments from corpus → inject retrieved verbatim text into model input → model answers **based only on that text.**

The system prompt must hard-code a rule (exact wording to be finalized in prompt file): *"You may only cite the provisions I supply. If they are insufficient, you must say '現有資料不足'. You must never supplement from memory."*

Accepted tradeoff: this makes the agent **conservative** — it will more often say "資料不足" instead of forcing an answer. For personal use this is **desirable**: "tell me you don't know" beats "a fluent possibly-fabricated answer."

### 2.3 Mechanism 2 — Citation verifier (independent second gate)
After the model generates an answer, a **separate programmatic step** runs before the answer reaches the user:
1. Extract every statute citation from the answer (e.g. "噪音管制法第9條").
2. For each, check against the corpus: **(a) does the article number exist? (b) does the model's paraphrase match the source content? (c) is it currently in force?**

All three checks are required — checking existence alone is insufficient. Research shows RAG-era hallucinations shifted shape: systems cite *real* documents but apply them anachronistically / incompletely / mis-read details (transposed numbers, conflated entities, misattributed quotes). The verifier must catch content-mismatch and outdated-version, not just fake article numbers.

Strictness for personal-use version: **flag + attach the corpus's verbatim original next to the flagged claim** so the owner can compare directly. (Not auto-deleting; not full regeneration — those over-prune useful answers.)

Note: the same logic is reused as an evaluation tool in §4.

### 2.4 Mechanism 3 — Three-tier honest response (most-often-done-badly part)
The corpus may lack any source for a question (unrecorded local 自治條例, or not a legal question at all). Bad legal AI forces an answer here — highest hallucination rate. Correct behavior, graded:
- **High-relevance sources retrieved** → normal answer + citations.
- **Only marginal sources** → answer BUT explicitly mark "以下僅供參考,未找到直接對應的法條".
- **Nothing retrieved** → say "這個問題我的資料庫沒有涵蓋,建議諮詢律師或換個描述方式" — **do not fabricate.**

This "three-tier honesty" is the soul of the personal-use version: the owner relies on it, so it must make clear how much confidence each answer carries.

### 2.5 Mechanism 4 — Separate 法條 (statute) from 研判 (analysis)
A legal answer has two halves: statute citations (verifiable, high-trust) and reasoning ("given this, your situation may constitute…" — model inference, cannot be corpus-verified). Research is explicit: *RAG verifies what sources say, not how the AI reasons about them.*

Requirement: **visually/structurally separate** "法條依據" (verifiable) from "分析研判" (model inference, for-reference-only) in every answer. The owner should see at a glance which parts are black-letter law vs. AI speculation, and calibrate trust accordingly.

### 2.6 Mechanism 5 — Anti-sycophancy / premise correction
Research names **sycophancy** as a top-4 error type: when a user asks with a wrong premise, the AI tends to *support* the wrong claim with fabricated/distorted authority instead of correcting it.

This is the MOST dangerous failure mode for personal use, because the owner is a legal layperson who will frequently ask with wrong premises (e.g. "邻居半夜走路有声音,这构成恐吓罪吧,我要告他"). A sycophantic agent says "yes, you can sue"; an honest one says "your described situation likely does NOT constitute 恐嚇罪, because…".

Requirement: instruct the model that when a user's statement contains an incorrect legal judgment, **correcting it takes priority over agreeing.** Its job is to state what the law actually says, not what the user wants to hear.

### 2.7 Summary of the five-gate defense
Retrieval-first (blocks bare answers) → Verifier (blocks bad citations: exists + content-match + in-force) → Three-tier honesty (blocks fabrication-from-nothing) → 法條/研判 separation (blocks over-trust of inference) → Anti-sycophancy (blocks premise-following). All tuned most-conservative.

---

## 3. Dialogue Flow Layer

### 3.1 Core difficulty
The user does not know which facts are legally relevant. "我有惡鄰居" could legally be noise / water leakage / space encroachment / threat / pets / odor — each a different statute path. The flow's first job is NOT to answer, but to **structure the facts.**

### 3.2 Four-stage flow ("clinic-style", not "chat-style")

**Stage 1 — Triage.** After the opening description, the agent does NOT answer. It coarse-classifies "惡鄰居" into a concrete legal problem type. If one sentence is insufficient (usually is), ask 1–2 discriminating questions ("主要困擾是噪音、漏水、占用空間,還是言語衝突?"). **No retrieval in this stage.**

**Stage 2 — Structured intake.** Once type is locked (assume 噪音), walk a **pre-designed question checklist** for that type, extracting the legally-relevant facts: 持續多久 / 什麼時段 / 公寓 or 透天 / 有無錄到證據 / 是否報過警或反映管委會 / 對方是否知情. The checklist is **designed in advance** from "which element-facts does this legal issue require", not improvised — so it never misses key facts nor asks irrelevant ones.
- **Question batching**: ask a small group (2–3 related questions) at a time. Rationale: faster than one-at-a-time, warmer than a cold form. This stage is BEFORE retrieval, so batching has **zero** effect on accuracy — choose purely on UX. **No retrieval in this stage.**

**Stage 3 — Classification & retrieval.** Facts complete → retrieve from corpus → legal classification → all five anti-hallucination gates (§2) fire here.

**Stage 4 — Solution output.** Give a **ranked** list of action options — and critically, **litigation is usually NOT ranked first.** For noise disputes, 反映管委會 / 報警請警察到場 / 里長調解 are often faster and cheaper than suing. A good lawyer says "don't rush to sue"; the agent must have this judgment and present a **low-to-high escalation ladder** with each option's cost / time / effort. Where an option involves a document (存證信函, 調解申請), it can generate a draft.

### 3.3 Critical design principle — retrieval fires ONCE, after facts are complete
Research: multi-turn RAG degrades badly (best-case recall ~33%). **The cause of that degradation is repeated re-retrieval + growing context, NOT the number of questions asked.** Therefore:
- Stages 1 & 2 (triage, intake) do **NOT** retrieve — pure fact-collection dialogue.
- Stage 3 retrieves **once**, on the complete fact set, when information is most complete.

This makes the flow "clinic-style" (take the full history, then diagnose once) rather than "chat-style" (query every turn, degrade while chatting). This single-retrieval design is a core reason this system can be more hallucination-resistant than a general chatbot.

### 3.4 Scenario coverage decision
Each problem type ideally has its own hand-designed intake checklist + solution ladder. Full coverage is heavy. Personal-use version: **build the most-likely scenario(s) first** — currently **住宅噪音糾紛** is locked as scenario #1 — others fall through to a generic, shallower flow.

---

## 4. Evaluation Layer (almost everyone skips this and gets silently burned)

### 4.1 Why it is mandatory, not optional
Recall: even professional tools hallucinate 17–33%. Without evaluation, you cannot know whether YOUR system's rate is 20% or 60% — you only get a *feeling* that "it answers fluently." Fluency and correctness are uncorrelated; a fabricated statute reads exactly like a real one. "Feels about right" is the most dangerous state. Evaluation converts feeling into numbers.

### 4.2 Three tiers (do at least tiers 1 & 2)

**Tier 1 — Golden Set (baseline, mandatory).**
Prepare ~20–30 test questions for the locked scenario (住宅噪音) where you **already know the correct answer.** For each, pre-write the standard answer: which statutes apply, correct action path, common wrong classifications. Run them against the agent, human-compare. **Fix this set and reuse it** — after any change (prompt, retrieval tuning), re-run and watch the score move. Gives objective "did this change help or hurt" signal instead of guesswork. ~An afternoon to build; the only window into "is it actually accurate."

**Tier 2 — Automated hallucination check (semi-automated, strongly recommended).**
A script that extracts all statute citations from each answer and auto-checks against the corpus: exists? content-matches? in-force? (This is literally the Mechanism-2 verifier logic reused as an eval tool.) Automatable, runs at scale, targets the most-lethal error (fabricated statutes). Complements Tier 1: Tier 1 tests "is the legal judgment right" (needs human), Tier 2 tests "are citations real" (machine can check).

**Tier 3 — Red-teaming (advanced, as time allows).**
Attack with adversarial inputs:
- **Sycophancy test** — ask with a deliberately wrong premise, check if it follows (bad) or corrects (good). Validates Mechanism 5.
- **Out-of-scope test** — ask something absent from the corpus, check if it admits "not covered" (good) or fabricates (bad). Validates Mechanism 3.
- **Vague-input test** — give an ambiguous description, check if it rushes to answer (bad) or asks follow-ups (good). Validates dialogue flow.

### 4.3 Recommendation
Tiers 1 + 2 are sufficient for personal use; do Tier 3 ad hoc. Tier 1 gives global "is it accurate", Tier 2 gives automated "did it fabricate" — together they cover the lethal risks. Grow the golden set organically: whenever a real answer looks suspicious in daily use, save it as a new test case.

---

## 5. Recommended Build Order

1. **Data layer, single scenario (住宅噪音).** Manually build the small time-versioned corpus (§1.4, §1.5). Human-verify every entry.
2. **Retrieval + Mechanism 1 & 2.** Get retrieval-first working; build the citation verifier (it doubles as the Tier-2 eval tool).
3. **Dialogue flow (§3)** with single-retrieval design (§3.3), noise-scenario intake checklist + solution ladder.
4. **Remaining anti-hallucination mechanisms (3, 4, 5)** wired into Stage 3/4 output.
5. **Golden Set eval (Tier 1)** — build ~20–30 verified Q&A, establish baseline score.
6. Iterate: use eval score to tune. Only after this loop is stable, consider full-corpus expansion / additional scenarios / auto-update.

---

## Appendix — Locked Decisions (from design discussion)

| # | Decision | Rationale |
|---|----------|-----------|
| Positioning | Personal-use assistant, ~80–90% self-understanding; keep lawyer-referral exit | "Replace lawyer" unachievable; personal use removes compliance risk but not accuracy risk |
| Dev vs runtime | Claude Code/Codex to build; Anthropic API at runtime | Different layers; dev tool is not a runtime dependency |
| Data model | Time-sliced statutes (effective_from/to + hierarchy); parsed judgments | Statutes amend; must apply the version in force at event time |
| Corpus strategy | Small-and-accurate, single scenario first | Retrieval quality depends on corpus quality; small corpus is human-verifiable |
| Anti-hallucination | 5 gates, all most-conservative | Pro tools still hit 17–33%; only defense is "know when it errs" |
| Verifier scope | exists + content-match + in-force | RAG-era hallucinations cite real docs wrongly, not just fake numbers |
| Dialogue style | Clinic-style, retrieval fires once after intake | Multi-turn re-retrieval is the degradation cause, not question count |
| Question batching | 2–3 at a time, chosen on UX | Intake is pre-retrieval, so no accuracy impact |
| Language | English tech scaffolding + Chinese legal content | AI coding parses English specs better; legal terms must stay verbatim Chinese |
| Evaluation | Tiers 1+2 mandatory, Tier 3 ad hoc | Converts "feels right" into measurable rate on the lethal risks |

---

*End of specification. This document reflects design decisions only; all legal-content specifics (exact articles, intake questions, prompt wording) are to be finalized during implementation against the live corpus.*
