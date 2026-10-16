"""Verifier mutation test — measure the citation verifier's catch rate on
KNOWN-planted errors (SPEC §2.3 / §4.2 Tier 2 hardening).

Rationale: the verifier is the load-bearing gate ("when the system errs, the
user knows"), so its own recall must be MEASURED, not assumed. This module
builds answers from real corpus rows with one planted defect each, runs
`verify_answer`, and reports catch rate per mutation type plus the
false-positive rate on correct controls. Fully deterministic — no LLM, no
network.

Mutation types (one citation per generated answer), 「原 8 類」(2026-07/08):
    control              correct citation, correct amount   -> must NOT flag
    nonexistent_article  real statute, article_no shifted    -> must flag (exists)
    fake_statute         invented statute name               -> must flag (exists)
    ghost_suffix         real article + 之99 suffix           -> must flag (exists)
    wrong_amount         real citation, amount x10           -> must flag (content)
    direction_flip       real amount, 以下<->以上 flipped     -> must flag (content)
    out_of_force         real citation, as_of before 生效日   -> must flag (in-force)
    subject_swap         right article, wrong 行為主體        -> must flag (semantic)
                         (generated ONLY when a semantic_llm is provided — the
                         structural axes provably cannot catch this class)
    alias_typo           suffix-shaped alias, omitted part corrupted -> must flag

「新 8 類」(2026-08-17, structural-axis hardening — SPEC §"blindspots"):
    prefixed_statute        德國/舊/臺北市 + real id           -> must flag (A1)
    ghost_paragraph         zero-newline article + 第2項        -> must flag (A3)
    ghost_item               single-list article + max+1 款      -> must flag (A4)
    anaphora_amount          explicit 同法 back-ref, wrong 元    -> must flag (A5+A7)
    anaphora_period          explicit 同法 back-ref, wrong 期間   -> must flag (A5)
    bare_penalty_amount      real citation, wrong AMOUNT, no 元   -> must flag (A7)
    period_direction_flip    real period, 以上/以下/內 flipped    -> must flag (A8)
    fraction_tamper          real citation, unsupported 分數      -> must flag (A8)

Each new "must-flag" axis above gets a matching, corpus-derived POSITIVE
CONTROL — restating the article's own real paragraph/item/fraction/period/
amount correctly must never be flagged either, and each has ITS OWN
denominator (never averaged into the headline "0/2,921", which would hide
false positives the same way the original 11,904 number hid this file's own
uncovered classes — see RESULTS.md "新增的七條軸沒有任何對照組"):
    real_paragraph_ref, real_item_ref, real_fraction, real_period_direction,
    real_bare_amount, verbatim_crossref, prose_prefix, prefixed_statute_control

retrieval_miss_quoted is generated ONLY under --retrieval-first: a citation
quoted verbatim inside a RETRIEVED source's own text, whose own article was
NOT retrieved. flagged is correctly False for this case either way (a model
quoting material it was given is not hallucinating) — what must change is
whether the status line is still allowed to claim "全數可回溯至資料庫" while
that citation's own content was never checked. Graded on the STATUS LINE, not
on .flagged (verify_answer's `_quoted_in_retrieved` branch is deliberately
untouched by this file — that would be a verifier.py change).

NOTE ON SEQUENCING: the eight NEW "must-flag" classes above test axes
(A1/A3/A4/A5/A7/A8) that ship in legal_agent/anti_hallucination/verifier.py —
a SEPARATE file, out of this module's remit. Until those land, this file
correctly and honestly reports those classes as MISSES (see RESULTS.md for
the measured per-class numbers) — that is the verifier under-catching, not a
bug in the mutant generator. Every new class here was hand-probed against the
CURRENT verifier.py before being written down, specifically so a miss here
never gets mis-attributed to a mutation.py defect.

Run:  python -m legal_agent.evaluation.mutation [--semantic] [--retrieval-first]
      --semantic wires a local Ollama (fmt=json) as the 4th-axis checker and
      plants the subject_swap cases, so the LLM axis is GRADED, not trusted.
      --retrieval-first re-runs EVERY class through
      verify_answer(answer, retrieved_context=[Statute(*row)], conn=None,
      corpus_conn=conn) — the production call shape (dialogue/stage3.py:377)
      — and additionally plants retrieval_miss_quoted, which is structurally
      unreachable when a class builds retrieved_context by SQL-selecting the
      target row (every other class here still does exactly that, by design:
      it is testing the axis, not the retriever).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from legal_agent.anti_hallucination.verifier import (
    _ALIASES,
    _amounts,
    _parse_number,
    _period_label,
    _periods,
    verification_status_line,
    verify_answer,
)
from legal_agent.data.models import Statute

_ARTICLE_NUM_RE = re.compile(r"第(\d+)條")
_FAKE_ANSWER = "依台灣安寧保障法第3條,住戶應保持安寧。"
# Suffix-form amount + direction word, as statutes write penalty bounds.
_AMOUNT_DIR_RE = re.compile(
    r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩]+)\s*元(以上|以下|以內|未滿)?"
)
_DOWNWARD = {"以下", "以內", "未滿"}

# Full 7-column row shape (legal_agent.data.models.Statute field order) — the
# precondition for building Statute(*row) objects for --retrieval-first
# (B1). Kept as one constant so the SELECT used by _condition_articles() and
# the ad hoc lookups below (alias_typo's base row, prefixed_statute_control's
# regression rows) can never drift out of column-order sync with each other.
_ROW_COLS = "statute_id, article_no, content, effective_from, effective_to, hierarchy_level, source_url"

# ── B2 generation-side helpers ────────────────────────────────────────────
# Local to mutation.py on purpose: verifier.py owns the CHECKING regexes for
# these same shapes (or will, once A3/A4/A7/A8 land there); these are only
# used to pick WHICH mutant to plant. Keeping them independent means a future
# change to the checking axis's internals cannot silently disable the mutant
# generator that is supposed to be testing it — the same reason the existing
# _AMOUNT_DIR_RE above is already a separate copy from verifier.py's.
#
# Item-list marker. MEASURED on the shipped corpus (2,921 current articles):
# 416 rows contain at least one 「一、」-shaped item marker; of those, 392 rows
# contain the token 「一」 EXACTLY ONCE (a single, trustworthy numbered list —
# its highest item number is a real upper bound) and 24 contain it 2+ times
# (two or more SEPARATE lists in one article body — 民法§129, 中華民國刑法
# §10/§74, 道路交通管理處罰條例§7-2 among them — no single "max item" is safe
# to trust there, so ghost_item/real_item_ref never touch that population).
_ITEM_RE = re.compile(r"(?:^|\n)([一二三四五六七八九十百]+)、", re.MULTILINE)
# 「X分之Y」— MEASURED: 82 current articles state at least one fraction.
_FRACTION_RE = re.compile(
    r"([0-9０-９零〇一二三四五六七八九十百千兩]+)分之([0-9０-９零〇一二三四五六七八九十百千兩]+)"
)
# Period + direction word, WITHOUT requiring 元 (money has no bare-內 form;
# periods commonly do — 「七日內」 — so 內 is its own alternative, tried after
# 以內 so the longer match wins first). MEASURED: 842 matches / 457 articles.
_PERIOD_DIR_RE = re.compile(
    r"([0-9０-９零〇一二三四五六七八九十百千兩]+)\s*(個月|小時|星期|週|日|天|年)(以上|以下|以內|未滿|內)"
)
_PERIOD_DOWNWARD = {"以下", "以內", "未滿", "內"}
_PERIOD_UNIT_NORM = {"天": "日", "星期": "週", "個月": "月"}
# An article whose OWN text anaphorically cites 本法/同法 (a 辦法/母法 pair —
# 違反社會秩序維護法案件處理辦法 quoting 「本法第八條」 meaning its own parent
# 社會秩序維護法). MEASURED: 15 current articles. Quoting one of these
# VERBATIM must never be flagged just because the back-reference's article
# number cannot be pinned to a statute of its own (verbatim_crossref, B2/B4).
_CROSSREF_ANAPHORA_RE = re.compile(r"本法第|同法第")

# Name-prefix shapes A1 exists to close: foreign (德國), old-law (舊), and
# local-government (臺北市) prefixes glued onto a REAL corpus statute name.
# Naive endswith-suffix resolution launders all three into the real statute
# (measured directly against today's verifier: 「依德國民法第1條」 resolves to
# statute_id="民法", exists=True, flagged=False).
_PREFIX_VARIANTS = (("德國", "foreign"), ("舊", "old-law"), ("臺北市", "local-gov"))

# The 3 hand-picked regression sentences A1/blindspots use as the "this must
# NOT become collateral damage" anchor — genuine prose particles (依/揆諸/上開
# 情形涉及) in front of a REAL corpus statute name. Existence is checked at
# generation time (see run_mutation_test) so a smaller/different corpus (the
# test-suite's 9-article noise fixture) degrades to fewer regression cases
# instead of a spurious false positive for a statute it never loaded.
_PREFIXED_STATUTE_REGRESSIONS = (
    ("依", "違反社會秩序維護法案件處理辦法", "第2條"),
    ("揆諸", "民法", "第184條"),
    ("上開情形涉及", "社會秩序維護法", "第72條"),
)

# ≥30 real Traditional-Chinese ways an answer names its own subject before
# citing a statute (prose_prefix). Tier3's name-resolution gate must resolve
# every one of these to the SAME statute a plain 「依」 would — this list
# doubles as the regression net for the two false-reject shapes a structural
# audit of this repo's own corpus text turned up (「包括民法…」 in 消費者保護
# 法§50, 「被害人因具民法…」 in 家庭暴力防治法§58-2).
_PROSE_PREFIXES = (
    "房東依", "房客依", "警察依", "管委會依", "本件", "系爭", "查", "爰依",
    "經查", "被告依", "原告依", "承租人依", "出租人依", "住戶依", "業者依",
    "雇主依", "勞工依", "消費者依", "企業經營者依", "法院依", "檢察官依",
    "主管機關依", "當事人依", "被害人依", "行為人依", "申請人依", "相對人依",
    "聲請人依", "義務人依", "權利人依", "包括", "被害人因具",
)

# retrieval_miss_quoted's fixed anchor (B4): the ONE corpus row whose own
# text quotes 噪音管制法第8條/第9條 verbatim while itself being a 文號-style
# (article_no == '') 行政實務見解. Excluding 噪音管制法第8條's own row from
# retrieved_context is the whole point — that is what makes the citation
# "quoted in a retrieved source, but its own article unretrieved" instead of
# "the target article was itself retrieved" (which every OTHER class below
# builds, and which structurally cannot reach the _quoted_in_retrieved
# branch this class exists to exercise).
_RETRIEVAL_MISS_STATUTE_ID = "噪音案件主管機關分工及警察受理處理原則（新北市政府警察局）"
_RETRIEVAL_MISS_ANSWER = "依噪音管制法第8條,主管機關應處新臺幣九十萬元以下罰鍰。"


@dataclass(frozen=True)
class MutationOutcome:
    kind: str
    ref: str                # the citation the answer carries
    answer: str
    as_of_date: str | None
    flagged: bool
    expect_flag: bool
    ok: bool                # flagged == expect_flag (or the status-line criterion — see below)
    reason: str             # verifier's reason (or extraction failure note)


@dataclass
class MutationReport:
    outcomes: list[MutationOutcome]
    # Semantic-axis verdicts that were never rendered by a model (server down,
    # unparseable reply). The axis answers 「consistent」 on every failure path,
    # so an outage looks exactly like a clean run — and on 2026-08-06 it did:
    # 0 flags on 9 planted swaps read as a perfect false-positive record until
    # the connection error surfaced. Reported, never silently absorbed.
    semantic_unreached: int = 0

    # "control" is the ONLY kind folded into the headline false-positive bar.
    # Every OTHER expect_flag=False kind — the seven axis-specific positive
    # controls added 2026-08-17, plus prefixed_statute_control's 3 parse-only
    # regressions — gets its OWN denominator, on its OWN report line, and is
    # NEVER silently averaged into "0/2,921". Doing that would have re-created
    # exactly the blind spot this file exists to close: a new axis with zero
    # cases run against it still reads as "0/0 clean" if it shares control's
    # bucket, which is indistinguishable on screen from "2,921/2,921 clean".
    CONTROL_KIND = "control"
    RETRIEVAL_STATUS_KIND = "retrieval_miss_quoted"

    def _bucket(self, kind: str) -> list[MutationOutcome]:
        return [o for o in self.outcomes if o.kind == kind]

    @property
    def kinds(self) -> list[str]:
        seen: list[str] = []
        for o in self.outcomes:
            if o.kind not in seen:
                seen.append(o.kind)
        return seen

    @property
    def mutation_total(self) -> int:
        return sum(
            1 for o in self.outcomes
            if o.expect_flag and o.kind != self.RETRIEVAL_STATUS_KIND
        )

    @property
    def mutation_caught(self) -> int:
        return sum(
            1 for o in self.outcomes
            if o.expect_flag and o.kind != self.RETRIEVAL_STATUS_KIND and o.ok
        )

    @property
    def catch_rate(self) -> float:
        return (self.mutation_caught / self.mutation_total) if self.mutation_total else 0.0

    @property
    def control_total(self) -> int:
        return sum(1 for o in self.outcomes if o.kind == self.CONTROL_KIND)

    @property
    def false_positives(self) -> int:
        return sum(1 for o in self.outcomes if o.kind == self.CONTROL_KIND and not o.ok)

    @property
    def false_positive_rate(self) -> float:
        return (self.false_positives / self.control_total) if self.control_total else 0.0

    @property
    def status_line_total(self) -> int:
        return sum(1 for o in self.outcomes if o.kind == self.RETRIEVAL_STATUS_KIND)

    @property
    def status_line_caught(self) -> int:
        return sum(1 for o in self.outcomes if o.kind == self.RETRIEVAL_STATUS_KIND and o.ok)

    def positive_control_kinds(self) -> list[str]:
        """Every expect_flag=False kind OTHER than 'control' — the axis-
        specific populations that give the new structural axes something
        real to be measured against, not just planted errors to catch."""
        seen: list[str] = []
        for o in self.outcomes:
            if not o.expect_flag and o.kind != self.CONTROL_KIND and o.kind not in seen:
                seen.append(o.kind)
        return seen

    def positive_control_false_positives(self) -> dict[str, tuple[int, int]]:
        """kind -> (false_positive_count, population), one entry per axis-
        specific positive control actually generated this run."""
        return {
            kind: (sum(1 for o in self._bucket(kind) if not o.ok), len(self._bucket(kind)))
            for kind in self.positive_control_kinds()
        }

    def zero_population_kinds(self, expected_kinds: tuple[str, ...]) -> list[str]:
        """Kinds this run was expected to be able to generate but produced
        ZERO outcomes for — the failure mode that let a mis-flagged regex
        run silently disabled behind a clean-looking scorecard (0/0 reads
        identical to "no cases exist" and "the generator is broken"). Only
        meaningful against a corpus with the population this file measured
        (the shipped 2,921-article corpus); a small/synthetic conn (e.g. the
        test suite's 9-article noise fixture) legitimately produces zero
        cases for several axes, so callers using such a conn should not
        treat this as fatal — see __main__ for the one caller that does."""
        present = set(self.kinds)
        return [k for k in expected_kinds if k not in present]

    def render(self) -> str:
        lines = [
            "═══════ Verifier mutation test(植入已知錯誤,量測抓取率) ═══════",
            f"{'type':<26}{'result':<14}note",
        ]
        for kind in self.kinds:
            bucket = self._bucket(kind)
            ok = sum(1 for o in bucket if o.ok)
            if kind == self.RETRIEVAL_STATUS_KIND:
                note = "status-line catch(非 flagged)"
            elif bucket[0].expect_flag:
                note = "必須標記(catch)"
            else:
                note = "不得誤標(false-positive)"
            lines.append(f"{kind:<26}{ok}/{len(bucket):<12}{note}")
        lines.append("")
        lines.append(
            f"mutation catch rate: {self.mutation_caught}/{self.mutation_total}"
            f"({self.catch_rate:.0%})｜control false-positive rate: "
            f"{self.false_positives}/{self.control_total}({self.false_positive_rate:.0%})"
        )
        if self.status_line_total:
            lines.append(
                f"retrieval_miss_quoted status-line catch: "
                f"{self.status_line_caught}/{self.status_line_total}"
                "(graded on verification_status_line, NOT on .flagged — see module docstring)"
            )
        pc = self.positive_control_false_positives()
        if pc:
            lines.append("軸別對照組(每軸獨立分母,不併入 control):")
            for kind, (fp, total) in pc.items():
                lines.append(f"  {kind:<24}{total - fp}/{total} 乾淨" + (f"  ⚠ {fp} 筆誤報" if fp else ""))
        if self.semantic_unreached:
            lines.append(
                f"⚠ 這個數字不是完整的四軸結果:語意軸有 {self.semantic_unreached} 次"
                "沒有拿到模型判讀(伺服器未啟動或回覆無法解析)。該軸在每一條失敗路徑上"
                "都回答「一致」,所以斷線看起來就像零誤報。重跑前先確認 Ollama。"
            )
        misses = [o for o in self.outcomes if not o.ok]
        if misses:
            lines.append("")
            lines.append("⚠ 未如預期的案例:")
            lines.extend(f"  - [{o.kind}] {o.ref}: {o.reason or '(無 reason)'}" for o in misses)
        return "\n".join(lines)


def _condition_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """條-style, currently-in-force corpus rows (文號-style entries have no
    article_no and use a different citation grammar — out of scope here).
    One row per article: historical slices are capped, so effective_to IS NULL
    is unique per (statute_id, article_no) — the ingest guard enforces it.

    Full 7-column shape (B1): the precondition for Statute(*row) under
    --retrieval-first. The first 3 columns are unchanged from before this
    revision, so every existing `row[0], row[1], row[2]` read downstream
    still lines up — this widened the SELECT, not the column order.
    """
    return conn.execute(
        f"SELECT {_ROW_COLS} FROM statutes "
        "WHERE article_no != '' AND effective_to IS NULL ORDER BY statute_id, article_no"
    ).fetchall()


def _single_list_max_item(content: str) -> int | None:
    """The max item number IF `content` contains exactly one item list (the
    token 「一」 occurs exactly once via _ITEM_RE) — the same 392-article
    population verifier.py's item-existence axis (A4) trusts. None for a
    zero- or multi-list article: ghost_item/real_item_ref must never plant or
    restate a claim the axis itself would refuse to judge (the 24-article
    ambiguous population stays untouched, same as the axis's own design)."""
    hits = _ITEM_RE.findall(content)
    if hits.count("一") != 1:
        return None
    values = [_parse_number(h) for h in hits]
    if not values or any(v is None for v in values):
        return None
    return max(values)


def _period_directions_local(content: str) -> dict[tuple[str, int], set[str]]:
    """(unit, value) -> the suffix direction words bound to it in `content`,
    unit-normalized (天->日, 星期->週, 個月->月) so 「七天」 and 「七日」 group
    together. Mirrors _amount_directions' shape in verifier.py, kept as an
    independent copy for the reason given in the B2 helpers' header comment."""
    directions: dict[tuple[str, int], set[str]] = {}
    for m in _PERIOD_DIR_RE.finditer(content):
        value = _parse_number(m.group(1))
        if value is None:
            continue
        unit = _PERIOD_UNIT_NORM.get(m.group(2), m.group(2))
        directions.setdefault((unit, value), set()).add(
            "down" if m.group(3) in _PERIOD_DOWNWARD else "up"
        )
    return directions


def _fractions_local(content: str) -> set[tuple[int, int]]:
    """(denominator, numerator) pairs stated in `content` — 「三分之一」 -> {(3, 1)}."""
    values: set[tuple[int, int]] = set()
    for d, n in _FRACTION_RE.findall(content):
        dv, nv = _parse_number(d), _parse_number(n)
        if dv and nv is not None:
            values.add((dv, nv))
    return values


def _judge(
    kind: str, ref: str, answer: str, expect_flag: bool,
    conn: sqlite3.Connection, as_of_date: str | None = None,
    semantic_llm=None,
    retrieval_first: bool = False,
    retrieved_context: list[Statute] | None = None,
    expect_status_line_catch: bool = False,
) -> MutationOutcome:
    """Run `answer` through the verifier and grade it.

    retrieval_first: call verify_answer the way dialogue/stage3.py does in
    production — retrieved_context carries the candidate rows, conn=None,
    corpus_conn=conn (the corpus may still resolve names and diagnose 「real
    article, just not retrieved」, but existence/content never fall back to it).

    expect_status_line_catch: grade `ok` on whether
    verification_status_line(results) stops claiming full traceability rather
    than on .flagged (the retrieval_miss_quoted kind; see module docstring).
    """
    ctx = retrieved_context or []
    if retrieval_first:
        results = verify_answer(
            answer, ctx, as_of_date=as_of_date, conn=None,
            corpus_conn=conn, semantic_llm=semantic_llm,
        )
    else:
        results = verify_answer(
            answer, ctx, as_of_date=as_of_date, conn=conn, semantic_llm=semantic_llm,
        )
    flagged = any(r.flagged for r in results) if results else False
    status_line = verification_status_line(results)
    full_traceable = "全數可回溯至資料庫" in status_line
    reason = (
        "未抽取到任何引用" if not results
        else "；".join(r.reason for r in results if r.reason)
    )
    ok = (not full_traceable) == expect_flag if expect_status_line_catch else flagged == expect_flag
    return MutationOutcome(
        kind, ref, answer, as_of_date, flagged=flagged, expect_flag=expect_flag,
        ok=ok, reason=reason,
    )


# Subject swaps: the cited article is REAL and every structural axis passes —
# only the 主體 is wrong. Hand-written against hand-verified corpus rows.
#
# Widened 2026-08-06 (3 -> 9 cases: actor swaps + object swaps whose NUMBER
# attaches to the wrong thing). Widened again 2026-08-17 (9 -> 32) as SC#9 of
# the structural-axis hardening — modal-negation flips, proviso deletions,
# and MORE number/fraction-wrong-object cases. Every added case keeps the
# article's real numbers, periods and fractions untouched and swaps only
# WHO/WHAT they attach to or WHETHER the sentence is an obligation or a
# permission — that is deliberate: A8 gave the structural axes a fraction and
# a period-direction check, and a genuinely wrong VALUE in either is no
# longer this axis's job to catch (see fraction_tamper / period_direction_flip
# above). A rule that only fires when the number itself is real is a rule
# this axis's numbers can never accidentally take credit for.
#
# Each case was run through `verify_answer` with the semantic axis OFF and
# had to return flagged=False before being written down — a case
# the structural axes already catch would credit this axis with work it
# never did.
_SUBJECT_SWAPS = [
    # ── actor swaps (existing, 2026-08-06) ──
    ("民法", "第793條",
     "依民法第793條,承租人於他人土地之喧囂侵入時,得禁止之。"),      # 條文主體:土地所有人
    ("公寓大廈管理條例", "第16條",
     "依公寓大廈管理條例第16條,房東不得任意發生喧囂、振動行為。"),   # 條文主體:住戶
    ("噪音管制法", "第6條",
     "依噪音管制法第6條,不具持續性之噪音由環境主管機關依法處理之。"),  # 條文主體:警察機關
    ("民法", "第432條",
     "依民法第432條,出租人應以善良管理人之注意,保管租賃物。"),      # 條文主體:承租人
    ("消費者保護法", "第19條",
     "依消費者保護法第19條,企業經營者得於交付商品後七日內解除契約。"),  # 七日解約權屬消費者
    ("家庭暴力防治法", "第14條",
     "依家庭暴力防治法第14條,警察機關於審理終結後,應核發通常保護令。"),  # 核發者:法院
    # ── object swaps: the number is right, what it attaches to is not (existing) ──
    ("租賃住宅市場發展及管理條例", "第7條",
     "依租賃住宅市場發展及管理條例第7條,出租人自押金扣除之金額,不得逾二個月之租金總額。"),
    ("勞動基準法", "第24條",
     "依勞動基準法第24條,休息日工作在二小時以內者,按平日每小時工資額加給三分之一以上。"),
    ("公寓大廈管理條例", "第10條",
     "依公寓大廈管理條例第10條,專有部分之修繕費用,由公共基金支付。"),
    # ── modal-negation flips (added 2026-08-17): 得/應/不得 swapped, numbers
    # untouched (mostly absent) ──
    ("民法", "第796條",
     "依民法第796條,鄰地所有人如知其越界而不即提出異議,得請求移去或變更其房屋。"),  # 條文:不得
    ("民法", "第774條",
     "依民法第774條,土地所有人經營事業或行使其所有權,得注意防免鄰地之損害。"),  # 條文:應
    ("消費者保護法", "第22條",
     "依消費者保護法第22條,企業經營者得確保廣告內容之真實,其對消費者所負之義務不得低於廣告之內容。"),  # 條文:應
    ("公寓大廈管理條例", "第6條",
     "依公寓大廈管理條例第6條,他住戶因維護、修繕專有部分、約定專用部分或設置管線,"
     "必須進入或使用其專有部分或約定專用部分時,得拒絕。"),  # 條文:不得拒絕
    ("就業服務法", "第5條",
     "依就業服務法第5條,雇主對求職人或所僱用員工,得以種族、階級、語言、思想、宗教、黨派、"
     "籍貫、出生地、性別、性傾向、年齡、婚姻、容貌、五官、身心障礙、星座、血型或以往工會會員身分為由,"
     "予以歧視。"),  # 條文:不得
    ("中華民國刑法", "第320條",
     "依中華民國刑法第320條,意圖為自己或第三人不法之所有而竊取他人之動產者之未遂犯,不罰。"),  # 條文:罰之
    # ── proviso deletions (added 2026-08-17): asserts the OPPOSITE of the
    # article's own 但書, numbers untouched ──
    ("消費者保護法", "第7條",
     "依消費者保護法第7條,企業經營者違反前二項規定,致生損害於消費者或第三人時,應負連帶賠償責任,"
     "即使企業經營者能證明其無過失,法院亦不得減輕其賠償責任。"),  # 條文但書:法院得減輕
    ("個人資料保護法", "第20條",
     "依個人資料保護法第20條,非公務機關對個人資料之利用,應於蒐集之特定目的必要範圍內為之,"
     "縱有法律明文規定之情形,亦不得為特定目的外之利用。"),  # 條文但書列舉:法律明文規定得為特定目的外利用
    ("勞動基準法", "第38條",
     "依勞動基準法第38條,特別休假期日,由勞工排定之,雇主不得以任何理由與勞工協商調整。"),  # 條文但書:雇主得協商調整
    # ── numbers attached to the wrong condition (added 2026-08-17): every
    # number is REAL and taken from the article itself, cross-wired ──
    ("中華民國刑法", "第284條",
     "依中華民國刑法第284條,因過失傷害人者,處三年以下有期徒刑、拘役或三十萬元以下罰金;"
     "致重傷者,處一年以下有期徒刑、拘役或十萬元以下罰金。"),  # 條文:傷害=1年/10萬,重傷=3年/30萬(對調)
    ("勞動基準法", "第16條",
     "依勞動基準法第16條,繼續工作三個月以上一年未滿者,於三十日前預告之;"
     "繼續工作三年以上者,於十日前預告之。"),  # 條文:三個月級距=10日,三年級距=30日(對調)
    ("道路交通管理處罰條例", "第56條",
     "依道路交通管理處罰條例第56條,汽車駕駛人在禁止臨時停車處所停車者,"
     "處新臺幣一千八百元以上三千元以下罰鍰;有併排停車情事者,處新臺幣六百元以上一千二百元以下罰鍰。"),
    ("勞動基準法", "第9條",
     "依勞動基準法第9條,定期契約屆滿後,雖經另訂新約,惟其前後勞動契約之工作期間超過三十日,"
     "前後契約間斷期間未超過九十日者,視為不定期契約。"),  # 條文:工作期間90日/間斷期間30日(對調)
    ("民法", "第425條",
     "依民法第425條,出租人於租賃物交付後,承租人占有中,縱將其所有權讓與第三人,"
     "其租賃契約對於受讓人仍繼續存在;但經公證之不動產租賃契約,其期限逾五年者,不適用之。"),  # 條文:未經公證者不適用
    ("租賃住宅市場發展及管理條例", "第9條",
     "依租賃住宅市場發展及管理條例第9條,出租人應於轉租人簽訂轉租契約後三十日內,以書面通知轉租人。"),  # 條文:轉租人通知出租人
    # ── fraction attached to the wrong condition (added 2026-08-17): every
    # fraction value is REAL and taken from the article itself, cross-wired ──
    ("民法", "第1144條",
     "依民法第1144條,配偶與第一千一百三十八條所定第二順序或第三順序之繼承人同為繼承時,"
     "其應繼分為遺產三分之二;與第四順序之繼承人同為繼承時,其應繼分為遺產二分之一。"),  # 條文:二分之一/三分之二(對調)
    ("中華民國刑法", "第66條",
     "依中華民國刑法第66條,有期徒刑、拘役、罰金減輕者,減輕其刑至三分之二;"
     "但同時有免除其刑之規定者,其減輕得減至二分之一。"),  # 條文:二分之一/三分之二(對調)
    ("性別平等工作法", "第5條",
     "依性別平等工作法第5條,性別平等工作會之女性委員人數應占全體委員人數三分之一以上;"
     "政府機關代表不得逾全體委員人數二分之一。"),  # 條文:二分之一/三分之一(對調)
    ("就業服務法", "第7條",
     "依就業服務法第7條,主管機關遴聘之勞工、雇主及學者專家代表,不得少於三分之一;"
     "其中代表單一性別者,不得少於二分之一。"),  # 條文:二分之一/三分之一(對調)
    ("中華民國刑法", "第77條",
     "依中華民國刑法第77條,受徒刑之執行而有悛悔實據者,有期徒刑逾三分之二、累犯逾二分之一,"
     "由監獄報請法務部,得許假釋出獄。"),  # 條文:二分之一/三分之二(對調)
    # ── more actor swaps (added 2026-08-17) ──
    ("家庭暴力防治法", "第21條",
     "依家庭暴力防治法第21條,其他保護令之執行,由被害人自行為之。"),  # 條文:由警察機關為之
    ("噪音管制法", "第9條",
     "依噪音管制法第9條,噪音管制區內之工廠、娛樂場所、營業場所、營建工程、擴音設施等場所之音量標準,"
     "由地方主管機關定之。"),  # 條文:由中央主管機關定之
    ("性別平等工作法", "第14條",
     "依性別平等工作法第14條,男性受僱者因生理日致工作有困難者,每月得請生理假一日,"
     "全年請假日數未逾三日,不併入病假計算,其餘日數併入病假計算。"),  # 條文主體:女性受僱者
]


def run_mutation_test(
    conn: sqlite3.Connection,
    semantic_llm=None,
    retrieval_first: bool = False,
) -> MutationReport:
    """Run the seeded-error suite. With `semantic_llm` set, the 4th axis is on
    and the subject_swap cases are planted (grading the LLM checker itself).
    With `retrieval_first` set (B3), every class runs through the production
    retrieval-first call shape, and retrieval_miss_quoted (B4) is additionally
    planted."""
    from legal_agent.anti_hallucination.semantic_check import reset_semantic_unreached

    reset_semantic_unreached()
    outcomes: list[MutationOutcome] = []
    # Earliest slice per article: out_of_force must date the citation before
    # the FIRST version ever took effect. The day before the CURRENT slice is
    # not out of force when a capped historical slice covers that date.
    earliest_from = {
        (r[0], r[1]): r[2]
        for r in conn.execute(
            "SELECT statute_id, article_no, MIN(effective_from) FROM statutes "
            "WHERE article_no != '' GROUP BY statute_id, article_no"
        )
    }

    condition_rows = _condition_articles(conn)
    # (statute_id, article_no) -> full 7-col row, and statute_id -> every
    # article_no it has among the condition rows — used by prefixed_statute
    # (one representative article per statute) and anaphora_amount/period
    # (needs a SECOND, different article_no of the same statute to name
    # explicitly before the 同法 back-reference).
    rows_by_key: dict[tuple[str, str], sqlite3.Row] = {}
    articles_by_statute: dict[str, list[str]] = {}
    for r in condition_rows:
        rows_by_key[(r[0], r[1])] = r
        lst = articles_by_statute.setdefault(r[0], [])
        if r[1] not in lst:
            lst.append(r[1])

    for row in condition_rows:
        sid, ano, content = row[0], row[1], row[2]
        ref = f"{sid}{ano}"
        statute_obj = Statute(row[0], row[1], row[2], row[3], row[4], row[5], row[6])
        ctx = [statute_obj] if retrieval_first else None
        num_match = _ARTICLE_NUM_RE.search(ano)
        source_amounts = _amounts(content)
        source_periods = _periods(content)
        period_unit = next((u for u, vs in source_periods.items() if vs), None)

        # control — correct citation; include a REAL amount / period when the
        # article states one, so the false-positive bar exercises both passes.
        claims = []
        if source_amounts:
            claims.append(f"法定金額為{max(source_amounts)}元")
        if period_unit is not None:
            real_period = max(source_periods[period_unit])
            claims.append(f"相關期間為{real_period}{_period_label(period_unit)}")
        if claims:
            control = f"依{ref}," + ",".join(claims) + "。"
        else:
            control = f"依{ref},其規範內容如條文所示。"
        # with the semantic axis on, controls ALSO pass through it — the 0-FP
        # bar applies to the LLM checker too, or it doesn't ship.
        outcomes.append(_judge("control", ref, control, expect_flag=False,
                               conn=conn, semantic_llm=semantic_llm,
                               retrieval_first=retrieval_first, retrieved_context=ctx))

        # nonexistent_article — same statute, shifted article number, VERIFIED
        # absent first: in a 1439-article code (民法), 第X+500條 can be a real
        # article — planting it would grade a correct verifier as a miss.
        if num_match:
            base_no = int(num_match.group(1))
            ghost_no = next(
                (
                    f"第{base_no + off}條" for off in (500, 1000, 5000, 9999)
                    if not conn.execute(
                        "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ?",
                        (sid, f"第{base_no + off}條"),
                    ).fetchone()
                ),
                None,
            )
            if ghost_no:
                ghost = f"{sid}{ghost_no}"
                outcomes.append(_judge(
                    "nonexistent_article", ghost,
                    f"依{ghost},住戶應負相關義務。", expect_flag=True, conn=conn,
                    retrieval_first=retrieval_first, retrieved_context=ctx,
                ))

        # ghost_suffix — a 「之X」 variant that does NOT exist (民法第793條之99).
        # LLMs love inventing 之X sub-articles; a parser that silently drops the
        # suffix launders the ghost into the REAL parent article. Same
        # verified-absent guard: the canonical form 第X-99條 must not be real.
        if num_match and not conn.execute(
            "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ?",
            (sid, f"第{num_match.group(1)}-99條"),
        ).fetchone():
            outcomes.append(_judge(
                "ghost_suffix", f"{ref}之99",
                f"依{ref}之99,住戶得請求排除侵害。", expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # wrong_amount — real citation, unsupported amount in the claim sentence.
        bad_amt = (max(source_amounts) * 10) if source_amounts else 99999
        outcomes.append(_judge(
            "wrong_amount", ref,
            f"依{ref},違者可處新臺幣{bad_amt}元罰鍰。", expect_flag=True, conn=conn,
            retrieval_first=retrieval_first, retrieved_context=ctx,
        ))

        # bare_penalty_amount (NEW, A7 target) — the SAME unsupported amount as
        # wrong_amount, just without the 元 character («處罰鍰十萬», «罰鍰最高
        # 一百萬»-shaped). _amounts()/_YUAN_RE require a trailing 元, so today's
        # verifier is blind to this class until A7's masked bare-amount scanner
        # ships — see module docstring.
        outcomes.append(_judge(
            "bare_penalty_amount", ref,
            f"依{ref},違者得處罰鍰{bad_amt}。", expect_flag=True, conn=conn,
            retrieval_first=retrieval_first, retrieved_context=ctx,
        ))
        # real_bare_amount (positive control) — the REAL amount, still bare.
        if source_amounts:
            outcomes.append(_judge(
                "real_bare_amount", ref,
                f"依{ref},違者得處罰鍰{max(source_amounts)}。", expect_flag=False, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # direction_flip — keep a REAL amount, flip its suffix direction word
        # (「六千元以下罰鍰」 -> claim 「六千元以上」). The amount itself checks
        # out, so an amounts-only content match is blind to this. Only amounts
        # whose direction is UNAMBIGUOUS in the article are planted: in range
        # wording (「六百元以上一千八百元以下…一千八百元以上…」) the same
        # amount legitimately carries BOTH directions, so a flip is consistent
        # and a correct verifier would be graded as a miss.
        amount_dirs: dict[int, set[str]] = {}
        for m in _AMOUNT_DIR_RE.finditer(content):
            value = _parse_number(m.group(1))
            if value is not None and m.group(2):
                amount_dirs.setdefault(value, set()).add(
                    "down" if m.group(2) in _DOWNWARD else "up"
                )
        unique = next((a for a, d in amount_dirs.items() if len(d) == 1), None)
        if unique is not None:
            flipped = "以上" if amount_dirs[unique] == {"down"} else "以下"
            outcomes.append(_judge(
                "direction_flip", ref,
                f"依{ref},違者可處新臺幣{unique}元{flipped}罰鍰。",
                expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # period_swap — real citation, real unit, wrong count (「七日」 claimed
        # as 「十四日」). An amounts-only content match is provably blind to
        # this class — the demo copy almost advertised the catch before it
        # existed (2026-07-19). Planted only when the article states a period,
        # and the fake value is verified absent from that unit's values.
        if period_unit is not None:
            fake_period = max(source_periods[period_unit]) * 2
            while fake_period in source_periods[period_unit]:
                fake_period += 1
            outcomes.append(_judge(
                "period_swap", ref,
                f"依{ref},相關期間為{fake_period}{_period_label(period_unit)}。",
                expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # period_direction_flip (NEW, A8 target) — mirrors direction_flip's
        # unambiguous guard exactly, for period+direction phrases instead of
        # amounts (「七日內」/「一個月以上」-shaped; MEASURED 457 articles carry
        # at least one such phrase, 842 total matches — see _PERIOD_DIR_RE).
        period_dirs = _period_directions_local(content)
        unique_pd = next(((k, d) for k, d in period_dirs.items() if len(d) == 1), None)
        if unique_pd is not None:
            (pd_unit, pd_value), pd_dirset = unique_pd
            pd_flipped = "以上" if pd_dirset == {"down"} else "以下"
            outcomes.append(_judge(
                "period_direction_flip", ref,
                f"依{ref},相關期間為{pd_value}{_period_label(pd_unit)}{pd_flipped}。",
                expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))
        # real_period_direction (positive control) — the FIRST real
        # period+direction phrase in the article, restated correctly. Broader
        # population than the flip above on purpose (not gated on
        # unambiguity): restating a TRUE value+direction pair is safe even
        # when the article states the same unit more than once.
        first_pd = _PERIOD_DIR_RE.search(content)
        if first_pd is not None:
            pdv = _parse_number(first_pd.group(1))
            if pdv is not None:
                pdu = _PERIOD_UNIT_NORM.get(first_pd.group(2), first_pd.group(2))
                outcomes.append(_judge(
                    "real_period_direction", ref,
                    f"依{ref},相關期間為{pdv}{_period_label(pdu)}{first_pd.group(3)}。",
                    expect_flag=False, conn=conn,
                    retrieval_first=retrieval_first, retrieved_context=ctx,
                ))

        # fraction_tamper (NEW, A8 target) — unambiguous guard: only when the
        # article states EXACTLY ONE distinct (denom, numer) pair (82 articles
        # carry >=1 fraction; a 2-distinct-value article like 勞動基準法§24
        # {(3,1),(3,2)} is EXCLUDED here on purpose — tampering "三分之一" into
        # "三分之二" there would be an equivalent mutant, not an error, since
        # both values are genuinely stated).
        frac_values = _fractions_local(content)
        if len(frac_values) == 1:
            (fr_denom, fr_numer), = frac_values
            candidate = fr_denom - fr_numer
            if candidate == fr_numer or candidate <= 0:
                candidate = fr_numer + 1
            outcomes.append(_judge(
                "fraction_tamper", ref,
                f"依{ref},相關比例為{fr_denom}分之{candidate}。",
                expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))
        # real_fraction (positive control) — one REAL fraction restated
        # correctly. Broader population than the tamper above (any article
        # with >=1 fraction, not just the unambiguous single-value ones).
        if frac_values:
            fr_denom, fr_numer = sorted(frac_values)[0]
            outcomes.append(_judge(
                "real_fraction", ref,
                f"依{ref},相關比例為{fr_denom}分之{fr_numer}。",
                expect_flag=False, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # out_of_force — cite the article the day BEFORE its earliest slice.
        day_before = (
            date.fromisoformat(earliest_from[(sid, ano)]) - timedelta(days=1)
        ).isoformat()
        outcomes.append(_judge(
            "out_of_force", f"{ref}@{day_before}", control, expect_flag=True,
            conn=conn, as_of_date=day_before,
            retrieval_first=retrieval_first, retrieved_context=ctx,
        ))

        # ghost_paragraph (NEW, A3 target) — only articles with ZERO newlines
        # (MEASURED 1,433/2,921 — a single, unambiguous paragraph; verifier.py
        # ignores Citation.paragraph entirely today, so this class is a MISS
        # until A3 ships — see module docstring).
        if content.count("\n") == 0:
            outcomes.append(_judge(
                "ghost_paragraph", f"{ref}第2項",
                f"依{ref}第2項,其規範內容如條文所示。", expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))
            outcomes.append(_judge(
                "real_paragraph_ref", ref,
                f"依{ref}第1項,其規範內容如條文所示。", expect_flag=False, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # ghost_item / real_item_ref (NEW, A4 target) — only the 392-article
        # single-list population (see _single_list_max_item).
        max_item = _single_list_max_item(content)
        if max_item is not None:
            outcomes.append(_judge(
                "ghost_item", f"{ref}第{max_item + 1}款",
                f"依{ref}第{max_item + 1}款,其規範內容如條文所示。", expect_flag=True,
                conn=conn, retrieval_first=retrieval_first, retrieved_context=ctx,
            ))
            outcomes.append(_judge(
                "real_item_ref", ref,
                f"依{ref}第{max_item}款,其規範內容如條文所示。", expect_flag=False,
                conn=conn, retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # verbatim_crossref (positive control, B2/B4 prerequisite) — an
        # article whose OWN text anaphorically cites 本法/同法 (a 辦法/母法
        # pair). Quoting it VERBATIM must never be flagged just because the
        # back-reference's article number belongs to a DIFFERENT statute than
        # the one being quoted (MEASURED 15 such articles, all 12 in
        # 違反社會秩序維護法案件處理辦法 plus 消費者保護法§9/勞動基準法§69/
        # 噪音管制法§24 — see module docstring).
        #
        # PRE-EXISTING FINDING (not introduced by this file, not fixable
        # here): 2/15 already fail under TODAY's unpatched verifier — 違反
        # 社會秩序維護法案件處理辦法第11條 (「本法第七十二條…」) and 第13條
        # (「本法第八十四條…」). `_iter_citations`' last_named inheritance
        # resolves 「本法」 to the 辦法 ITSELF (the statute this answer names
        # explicitly), not its 母法 社會秩序維護法 — the 辦法 has no 第72條/
        # 第84條 of its own (MEASURED), so exists=False and the verbatim quote
        # is wrongly flagged. The OTHER 10 辦法 cross-references pass today
        # only by COINCIDENCE (the 辦法 happens to also have an article at
        # that same number, which existence-only checking cannot tell apart
        # from the correct one) — under --retrieval-first, that coincidental
        # rescue disappears entirely (retrieved_context has no article but
        # this one), so 14/15 fail there instead of 2/15. Fix belongs to
        # verifier.py (_resolve_id / _is_anaphoric would need to try
        # stripping a 辦法/細則/規則/準則 suffix to find the 母法 before
        # falling back to the 辦法 itself), out of this file's remit — left
        # as a real, reproducible finding for that workstream.
        if _CROSSREF_ANAPHORA_RE.search(content):
            outcomes.append(_judge(
                "verbatim_crossref", ref, f"依{ref},{content}", expect_flag=False,
                conn=conn, retrieval_first=retrieval_first, retrieved_context=ctx,
            ))

        # anaphora_amount / anaphora_period (NEW, A5+A7/A5 targets) — an
        # EXPLICIT 同法 back-reference (never a bare cross-reference template —
        # a bare template would plant a false positive of its own kind, see
        # module docstring's anaphora_kind note) naming a DIFFERENT article of
        # the SAME statute first, then citing THIS article's number via 同法
        # with an unsupported amount/period. Today's verifier treats every
        # inferred_id citation as content_match=True unconditionally (A5 not
        # yet shipped), so this is a MISS until then — see module docstring.
        #
        # retrieved_context carries BOTH articles (other_ano AND ano) under
        # --retrieval-first — every other class in this file isolates the
        # axis under test by SQL-selecting exactly its target row(s), and
        # this pair is no different: with only `ano` in context, the FIRST
        # citation ({sid}{other_ano}) would itself come back "not retrieved
        # this time" and flag the answer for a reason that has nothing to do
        # with the wrong amount/period this class exists to plant — a catch
        # for the wrong reason is not a catch (MEASURED 2026-08-17: omitting
        # other_ano's row inflated anaphora_amount/period's retrieval-first
        # catch rate through exactly that side door).
        other_ano = next((a for a in articles_by_statute[sid] if a != ano), ano)
        other_row = rows_by_key[(sid, other_ano)]
        anaphora_ctx = (
            [Statute(other_row[0], other_row[1], other_row[2], other_row[3],
                    other_row[4], other_row[5], other_row[6]), statute_obj]
            if retrieval_first else None
        )
        if source_amounts:
            bad_anaphora_amt = max(source_amounts) * 10
            outcomes.append(_judge(
                "anaphora_amount", f"{sid}{other_ano}->同法{ano}",
                f"依{sid}{other_ano},相關規定如前所述。同法{ano},法定金額為{bad_anaphora_amt}元。",
                expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=anaphora_ctx,
            ))
        if period_unit is not None:
            fake_anaphora_period = max(source_periods[period_unit]) * 2
            while fake_anaphora_period in source_periods[period_unit]:
                fake_anaphora_period += 1
            outcomes.append(_judge(
                "anaphora_period", f"{sid}{other_ano}->同法{ano}",
                f"依{sid}{other_ano},相關規定如前所述。同法{ano},"
                f"相關期間為{fake_anaphora_period}{_period_label(period_unit)}。",
                expect_flag=True, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=anaphora_ctx,
            ))

    # prefixed_statute (NEW, A1 target) — one representative real article per
    # statute_id, prefixed 3 ways (德國/舊/臺北市). Population is EVERY
    # statute_id this corpus has a condition article for — dynamic, never
    # hardcoded (16 on the shipped corpus).
    for psid, anos in articles_by_statute.items():
        prow = rows_by_key[(psid, anos[0])]
        pctx = [Statute(prow[0], prow[1], prow[2], prow[3], prow[4], prow[5], prow[6])] \
            if retrieval_first else None
        for prefix, _tag in _PREFIX_VARIANTS:
            fake_name = f"{prefix}{psid}"
            outcomes.append(_judge(
                "prefixed_statute", f"{fake_name}{anos[0]}",
                f"依{fake_name}{anos[0]},其規範內容如條文所示。", expect_flag=True,
                conn=conn, retrieval_first=retrieval_first, retrieved_context=pctx,
            ))

    # prefixed_statute_control (positive control / A1 regression anchor) —
    # existence-checked at generation time so a smaller/different corpus
    # degrades to fewer cases instead of a spurious false positive for a
    # statute it never loaded (see _PREFIXED_STATUTE_REGRESSIONS docstring).
    for particle, rsid, rano in _PREFIXED_STATUTE_REGRESSIONS:
        rrow = conn.execute(
            f"SELECT {_ROW_COLS} FROM statutes WHERE statute_id = ? AND article_no = ? "
            "AND effective_to IS NULL", (rsid, rano),
        ).fetchone()
        if rrow is None:
            continue
        rcontent = rrow[2]
        rctx = [Statute(rrow[0], rrow[1], rrow[2], rrow[3], rrow[4], rrow[5], rrow[6])] \
            if retrieval_first else None
        outcomes.append(_judge(
            "prefixed_statute_control", f"{rsid}{rano}",
            f"{particle}{rsid}{rano},{rcontent}", expect_flag=False,
            conn=conn, retrieval_first=retrieval_first, retrieved_context=rctx,
        ))

    # prose_prefix (positive control, Tier3-gate regression net) — ≥30 real
    # ways an answer names its own subject before 「依」-ing a statute, cycled
    # across every statute_id this corpus has a condition article for. Passes
    # the cited article as retrieved_context under --retrieval-first for the
    # same reason anaphora_amount/period does above: this class tests NAME
    # RESOLUTION (Tier1/2/3), not retrieval completeness — without its target
    # row in context every case would fail on "not retrieved" instead, which
    # is a different axis than the one this class exists to regress-test.
    statute_cycle = list(articles_by_statute.items())
    if statute_cycle:
        for i, prefix in enumerate(_PROSE_PREFIXES):
            psid, anos = statute_cycle[i % len(statute_cycle)]
            prose_row = rows_by_key[(psid, anos[0])]
            prose_ctx = (
                [Statute(prose_row[0], prose_row[1], prose_row[2], prose_row[3],
                        prose_row[4], prose_row[5], prose_row[6])]
                if retrieval_first else None
            )
            outcomes.append(_judge(
                "prose_prefix", f"{prefix}{psid}{anos[0]}",
                f"{prefix}{psid}{anos[0]}主張權利。", expect_flag=False, conn=conn,
                retrieval_first=retrieval_first, retrieved_context=prose_ctx,
            ))

    # fake_statute — one invented statute name (corpus-independent).
    outcomes.append(_judge(
        "fake_statute", "台灣安寧保障法第3條", _FAKE_ANSWER, expect_flag=True, conn=conn,
        retrieval_first=retrieval_first,
    ))

    # alias_typo — the blind spot the live demo exposed on 2026-08-04. An alias
    # that is a SUFFIX of its canonical name (大廈管理條例 ⊂ 公寓大廈管理條例)
    # used to be matched as a suffix, so misspelling the part the alias omits
    # resolved the invented name into the real statute and passed all three
    # axes. One case per suffix-shaped alias, corrupting the omitted prefix.
    for short, canonical in sorted(_ALIASES.items()):
        if short == canonical or not canonical.endswith(short):
            continue                   # 刑法/勞基法-style abbreviations, not suffixes
        prefix = canonical[: -len(short)]
        corrupted = prefix[:-1] + "甲" + short          # 公寓… -> 公甲…
        base_row = conn.execute(
            f"SELECT {_ROW_COLS} FROM statutes WHERE statute_id = ? "
            "AND effective_to IS NULL ORDER BY article_no LIMIT 1", (canonical,),
        ).fetchone()
        if base_row is None:
            continue
        article = base_row[1]
        ref = f"{corrupted}{article}"
        actx = [Statute(base_row[0], base_row[1], base_row[2], base_row[3],
                        base_row[4], base_row[5], base_row[6])] if retrieval_first else None
        outcomes.append(_judge(
            "alias_typo", ref, f"依{ref}規定辦理。", expect_flag=True, conn=conn,
            retrieval_first=retrieval_first, retrieved_context=actx,
        ))

    # retrieval_miss_quoted (NEW, B4 — ONLY under --retrieval-first) — the one
    # case in this whole file where retrieved_context is built to DELIBERATELY
    # EXCLUDE the cited article's own row. Every other class above builds
    # retrieved_context BY SELECTING the target row, which makes the
    # _quoted_in_retrieved false-greenlight branch structurally unreachable —
    # this is the sole case that reaches it. Graded on the status line via
    # expect_status_line_catch, not on .flagged (see module docstring).
    if retrieval_first:
        miss_row = conn.execute(
            f"SELECT {_ROW_COLS} FROM statutes WHERE statute_id = ? AND article_no = ''",
            (_RETRIEVAL_MISS_STATUTE_ID,),
        ).fetchone()
        if miss_row is not None:
            outcomes.append(_judge(
                "retrieval_miss_quoted", "噪音管制法第8條(未檢索,經新北市警局分工原則轉引)",
                _RETRIEVAL_MISS_ANSWER, expect_flag=True, conn=conn,
                retrieval_first=True,
                retrieved_context=[Statute(miss_row[0], miss_row[1], miss_row[2], miss_row[3],
                                           miss_row[4], miss_row[5], miss_row[6])],
                expect_status_line_catch=True,
            ))

    # subject_swap — semantic-axis cases: structurally perfect, wrong 主體.
    if semantic_llm is not None:
        for sid, ano, answer in _SUBJECT_SWAPS:
            present = conn.execute(
                "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ? "
                "AND effective_to IS NULL", (sid, ano),
            ).fetchone()
            if present:
                outcomes.append(_judge(
                    "subject_swap", f"{sid}{ano}", answer,
                    expect_flag=True, conn=conn, semantic_llm=semantic_llm,
                    retrieval_first=retrieval_first,
                ))
    from legal_agent.anti_hallucination.semantic_check import semantic_unreached_count

    return MutationReport(outcomes, semantic_unreached=semantic_unreached_count())


# Kinds this file can ALWAYS generate at least one case for, against a corpus
# with the shape the shipped one has (every population measured in this
# file's comments is non-zero). Used ONLY by __main__'s zero-population check
# against the real production DB — NOT a general assertion, since a small or
# synthetic conn (e.g. the test suite's 9-article noise fixture) legitimately
# produces zero cases for several of these and that is not a bug.
_ALWAYS_NONEMPTY_ON_FULL_CORPUS = (
    "control", "nonexistent_article", "ghost_suffix", "wrong_amount",
    "bare_penalty_amount", "out_of_force", "period_swap", "direction_flip",
    "ghost_paragraph", "real_paragraph_ref", "ghost_item", "real_item_ref",
    "verbatim_crossref", "prefixed_statute", "prefixed_statute_control",
    "prose_prefix", "fake_statute", "alias_typo",
    "anaphora_amount", "anaphora_period", "real_bare_amount",
    "period_direction_flip", "real_period_direction",
    "fraction_tamper", "real_fraction",
)


if __name__ == "__main__":  # python -m legal_agent.evaluation.mutation [--semantic] [--retrieval-first]
    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()
    import argparse

    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    _parser = argparse.ArgumentParser(prog="python -m legal_agent.evaluation.mutation")
    _parser.add_argument(
        "--semantic", action="store_true",
        help="開啟第四軸語意檢查(本地 Ollama, fmt=json, temperature=0)並種入 subject_swap 錯",
    )
    _parser.add_argument(
        "--model", default=None, metavar="OLLAMA_MODEL",
        help="語意軸用的 Ollama 模型(預設 config.OLLAMA_MODEL)— 讓不同模型考同一份考卷",
    )
    _parser.add_argument(
        "--retrieval-first", action="store_true",
        help="以生產呼叫形狀(retrieved_context=[Statute(*row)], conn=None, corpus_conn=conn)"
             "重跑全部類別,並額外種入 retrieval_miss_quoted",
    )
    _args = _parser.parse_args()

    _semantic_llm = None
    if _args.semantic:
        from legal_agent.dialogue.ollama_llm import ollama_available, ollama_llm

        if not ollama_available():
            raise SystemExit("Ollama 未啟動 — 語意軸需要本地模型(先 `ollama serve`)")
        _semantic_llm = ollama_llm(model=_args.model, fmt="json", temperature=0.0)

    _conn = connect(DB_PATH)
    try:
        _report = run_mutation_test(_conn, semantic_llm=_semantic_llm,
                                    retrieval_first=_args.retrieval_first)
        print(_report.render())

        _problems: list[str] = []
        if not _args.retrieval_first:
            if _report.catch_rate < 1.0:
                _problems.append(
                    f"catch rate {_report.mutation_caught}/{_report.mutation_total}"
                    f"({_report.catch_rate:.0%}) < 100%"
                )
            if _report.false_positive_rate > 0.0:
                _problems.append(
                    f"control false-positive rate {_report.false_positives}/"
                    f"{_report.control_total} > 0"
                )
            for _kind, (_fp, _total) in _report.positive_control_false_positives().items():
                if _fp:
                    _problems.append(f"{_kind} 對照組誤報 {_fp}/{_total}")
            for _kind in _report.zero_population_kinds(_ALWAYS_NONEMPTY_ON_FULL_CORPUS):
                _problems.append(f"⚠ 此軸在正式 corpus 上無對照母體(0 案例):{_kind}")
        else:
            if _report.status_line_total == 0:
                _problems.append("retrieval_miss_quoted 類別未生成(0 案例) — corpus 中找不到錨定列")
            elif _report.status_line_caught < _report.status_line_total:
                _problems.append(
                    f"retrieval_miss_quoted status-line catch "
                    f"{_report.status_line_caught}/{_report.status_line_total} < 100%"
                    "(這是已知落差,見 module docstring — 需 verifier.py A2/A5 落地)"
                )
        if _problems:
            print()
            for _p in _problems:
                print(f"FAIL: {_p}")
            raise SystemExit(1)
    finally:
        _conn.close()
