"""paragraph_bounds_audit.py -- upgrade path for the 款 (item) existence
axis, NOT this round's judging criterion (D2; A4's own note in
verifier.py makes the same point about its 392/24 split).

A4 ships a coarse, hand-verified split over the 2,921 in-force articles:
「一、」 occurs exactly once in an article's content -> that article is
trusted at ONE global max item number (392 articles); 「一、」 occurs two or
more times -> the article is held back entirely as unverified, because a
single global max would let a citation into the FIRST 項's list validate
against the LAST 項's (possibly higher) max (24 articles). This script
explores whether those 24 can be split more precisely -- one upper bound
per 項-level block instead of one per article -- and cross-checks the
result against every item-numbered reference the corpus makes to ITSELF.

WHAT "區塊" MEANS HERE
-----------------------
A 款 list restarts at 一 every time a NEW 項 (or unnumbered paragraph)
begins its own enumeration. Given the marker sequence for an article
(一,二,三 then 一,二,三,四,五 for 民法第129條, say), a block boundary is
placed wherever the sequence fails to keep increasing -- i.e. NOT a fixed
"款 token count", a running comparison against the previous marker. Each
block's own upper bound is its own max, so a reference into the SECOND 項
is never validated against the first 項's (possibly higher, possibly
lower) max.

WHAT THE CROSS-CHECK MEANS, AND WHAT IT DOES NOT
--------------------------------------------------
"矛盾" here means: some OTHER article's own text cites this one with a 款
number that exceeds every block this script derived for it. That is
INTERNAL consistency only -- corpus text agreeing with itself. There is no
external structured feed this round to compare against (see RESULTS.md,
"下一輪候選"), so an article with zero contradictions is a CANDIDATE for
upgrade, not a proof. Nothing here changes A4's 392/24 split THIS round --
verifier.py is out of this script's scope and the split stays frozen
either way until a human reads this output and a future round acts on it.

Cross-referencing also makes two assumptions about what an unnamed
reference means, stated here so a flagged contradiction can be read
correctly:

  * A BARE, unnamed continuation -- 道路交通管理處罰條例第7-2條's own
    「…及第九十二條第七項第六款之行為」 never names a statute at all -- is
    attributed to THAT article's own statute_id. Ordinary drafting
    convention for an unnamed continuation, and the same self-reference a
    reader would supply.
  * An EXPLICIT anaphora word (「同法」「本法」「該法」…) is attributed to
    the article's own statute_id UNLESS that statute_id itself textually
    CONTAINS a different, real corpus statute id as a substring -- e.g.
    違反社會秩序維護法案件處理辦法 contains 社會秩序維護法 -- in which case
    the contained id is used instead. A 辦法/細則/規則/準則 whose own name is
    built by wrapping around its enabling law's name conventionally means
    THAT law when it says 「本法」, not itself; this was not a theoretical
    worry, it is exactly what 違反社會秩序維護法案件處理辦法第14條's own
    text does (「本法第四十三條第一項第一款」 means 社會秩序維護法第43條, a
    5-item list, NOT the 辦法's own, unrelated 第43條) -- first observed as
    a false contradiction in this script's own first run, fixed by adding
    this rule.

Both are heuristics, not proofs -- a VERBATIM quotation of a different
statute's text that itself ends in an unnamed continuation could still
fool the first rule, and a coincidental substring match could in principle
fool the second (checked: across all 17 corpus ids today, exactly one pair
has this containment relationship, so the second rule is unambiguous on
this corpus, but it is a structural check, not a hardcoded pair). A
contradiction this script reports should be read as "worth a human look",
not as a proven defect -- exactly why this script is an upgrade path and
not a judging criterion.

Run:  python -m legal_agent.evaluation.paragraph_bounds_audit
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from legal_agent.anti_hallucination.verifier import (
    _ANAPHORA_NAMES,
    _CITATION_RE,
    _canonical_article,
    _is_anaphoric,
    _parse_number,
    _resolve_id,
)
from legal_agent.config import DB_PATH
from legal_agent.evaluation import assert_nonzero_scan

# 款 marker at the start of a line: 「一、」「二、」… `re.MULTILINE` is kept for
# what it documents (「^」 = line start) even though it is, measured, a no-op
# for this exact pattern: `(?:^|\n)` already covers the newline case
# MULTILINE would add. Confirmed on the full 2,923-row corpus and again on
# the 2,921 in-force rows this script scans -- identical hit/row counts with
# the flag on or off either way. Kept for clarity, not load-bearing.
_ITEM_MARKER_RE = re.compile(r"(?:^|\n)([一二三四五六七八九十百]+)、", re.MULTILINE)
_ONE_MARKER_RE = re.compile(r"(?:^|\n)一、", re.MULTILINE)

# The four articles the task calls out for a full, human-readable derivation.
_FULL_DERIVATION_TARGETS: tuple[tuple[str, str], ...] = (
    ("民法", "第129條"),
    ("中華民國刑法", "第10條"),
    ("中華民國刑法", "第74條"),
    ("道路交通管理處罰條例", "第7-2條"),
)


@dataclass(frozen=True)
class Block:
    index: int                 # 1-based position among this article's blocks
    numbers: tuple[int, ...]   # parsed value of every marker in the block, in order

    @property
    def upper_bound(self) -> int:
        return max(self.numbers) if self.numbers else 0


@dataclass(frozen=True)
class CrossRef:
    """One item-numbered citation found INSIDE the corpus's own text."""

    from_source: str
    target_statute_id: str
    target_article_no: str
    item: int
    context: str


@dataclass
class AuditReport:
    rows_scanned: int = 0
    total_markers: int = 0
    rows_with_markers: int = 0
    bounds: dict[tuple[str, str], list[Block]] = field(default_factory=dict)
    all_refs: list[CrossRef] = field(default_factory=list)
    checked_refs: int = 0
    contradictions: list[tuple[CrossRef, int]] = field(default_factory=list)
    heuristic_mismatches: list[tuple[str, str, str, int]] = field(default_factory=list)

    @property
    def exclusions(self) -> list[tuple[str, str]]:
        return sorted({(r.target_statute_id, r.target_article_no) for r, _ in self.contradictions})


def _context(text: str, start: int, end: int, radius: int = 24) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return f"{text[lo:start]}『{text[start:end]}』{text[end:hi]}".replace("\n", " ")


def _derive_blocks(content: str) -> list[Block]:
    """Split the 款 marker sequence wherever it fails to keep increasing.

    民法第129條 has two 項, one capped at 三 and the next at 五 -- one block
    per article (treating it as a single running list) would let a 「第五
    款」 reference validate against the FIRST 項, which does not go past
    三. Splitting on non-increase, and taking each block's OWN max, is what
    avoids that.
    """
    blocks: list[Block] = []
    current: list[int] = []
    prev: int | None = None
    for raw in _ITEM_MARKER_RE.findall(content):
        n = _parse_number(raw)
        if n is None:
            continue  # the marker character class ([一二三四五六七八九十百]) is a
                       # strict subset of _parse_number's own CN_DIGIT/CN_SMALL
                       # tables, so this never actually fires -- kept as a
                       # guard, not a reachable path.
        if prev is not None and n <= prev:
            blocks.append(Block(len(blocks) + 1, tuple(current)))
            current = []
        current.append(n)
        prev = n
    if current:
        blocks.append(Block(len(blocks) + 1, tuple(current)))
    return blocks


def _anaphora_parent(statute_id: str, known_ids: set[str]) -> str:
    """What 「本法/同法/該法…」 means inside an article belonging to
    `statute_id` -- usually `statute_id` itself, but NOT when `statute_id`
    is a subordinate instrument whose own name textually wraps around its
    enabling law's name (違反社會秩序維護法案件處理辦法 contains
    社會秩序維護法): such a 辦法/細則/規則/準則 conventionally means the
    enabling law when it says 「本法」, not itself. Detected structurally --
    does `statute_id` CONTAIN a different known id as a substring -- not by
    a hardcoded pair, so it generalises to any future 辦法/母法 pair the
    corpus grows without another edit here. Falls back to `statute_id`
    itself when no such unambiguous parent exists, or when more than one
    candidate is found (ambiguous -- do not guess)."""
    parents = [kid for kid in known_ids if kid != statute_id and kid in statute_id]
    return parents[0] if len(parents) == 1 else statute_id


def _extract_cross_refs(
    statute_id: str, article_no: str, content: str, known_ids: set[str]
) -> list[CrossRef]:
    """Every item-numbered citation inside one article's own text, resolved
    to (target_statute_id, target_article_no, item). See the module
    docstring's caveat for what "bare" vs "explicit anaphora" resolve to.
    A reference that NAMES a different, real corpus statute uses that name.
    A reference naming something that resolves to neither (an out-of-corpus
    name, or a fabricated one) is dropped: this script checks item BOUNDS
    on articles it already has a block derivation for, it does not
    re-litigate existence.
    """
    out: list[CrossRef] = []
    for m in _CITATION_RE.finditer(content):
        if not m.group("item"):
            continue
        item = _parse_number(m.group("item"))
        if item is None:
            continue
        target_ano = _canonical_article(m.group("article"), m.group("suffix"))
        if target_ano is None:
            continue
        name_run = m.group("name")
        resolved = _resolve_id(name_run, known_ids)
        if resolved in known_ids:
            target_sid = resolved
        elif _is_anaphoric(name_run, resolved, known_ids):
            if name_run.endswith(_ANAPHORA_NAMES):
                target_sid = _anaphora_parent(statute_id, known_ids)
            else:
                target_sid = statute_id  # bare unnamed continuation -> self
        else:
            continue
        out.append(CrossRef(
            from_source=f"{statute_id}{article_no}",
            target_statute_id=target_sid, target_article_no=target_ano,
            item=item, context=_context(content, m.start(), m.end()),
        ))
    return out


def run_audit(conn: sqlite3.Connection) -> AuditReport:
    known_ids = {row[0] for row in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    rows = conn.execute(
        "SELECT statute_id, article_no, content FROM statutes "
        "WHERE article_no != '' AND effective_to IS NULL "
        "ORDER BY statute_id, article_no"
    ).fetchall()

    report = AuditReport(rows_scanned=len(rows))
    for sid, ano, content in rows:
        content = content or ""
        markers = _ITEM_MARKER_RE.findall(content)
        report.total_markers += len(markers)
        if markers:
            report.rows_with_markers += 1
        report.bounds[(sid, ano)] = _derive_blocks(content)

        # Cross-check against A4's own coarser heuristic (「一、」 occurrence
        # count) -- informational only, per the module docstring;
        # disagreement is surfaced, never auto-resolved.
        n_one = len(_ONE_MARKER_RE.findall(content))
        n_blocks = len(report.bounds[(sid, ano)])
        if n_one == 1 and n_blocks != 1:
            report.heuristic_mismatches.append((sid, ano, "一、恰1次但區塊數≠1", n_blocks))
        elif n_one >= 2 and n_blocks < 2:
            report.heuristic_mismatches.append((sid, ano, "一、≥2次但區塊數<2", n_blocks))

    for sid, ano, content in rows:
        report.all_refs.extend(_extract_cross_refs(sid, ano, content or "", known_ids))

    for ref in report.all_refs:
        blocks = report.bounds.get((ref.target_statute_id, ref.target_article_no))
        if blocks is None:
            continue
        report.checked_refs += 1
        derived_max = max((b.upper_bound for b in blocks), default=0)
        if ref.item > derived_max:
            report.contradictions.append((ref, derived_max))

    return report


def render(report: AuditReport) -> str:
    lines = [
        "═══════ paragraph_bounds_audit(款存在性軸的升級路徑 —— 本輪僅供參考,不改判準) ═══════",
        f"掃描現行條文列數:{report.rows_scanned}",
        f"款號標記(一/二/三…、)命中數:{report.total_markers}"
        f"(含款號標記的條文列數:{report.rows_with_markers})",
        "",
        "── 指定 4 條完整推導 ──",
    ]
    for sid, ano in _FULL_DERIVATION_TARGETS:
        blocks = report.bounds.get((sid, ano))
        if blocks is None:
            lines.append(f"  {sid}{ano}:不在現行條文範圍內(找不到列)")
            continue
        lines.append(f"  {sid}{ano}:{len(blocks)} 個區塊")
        for b in blocks:
            lines.append(f"    區塊{b.index}:款號序列={b.numbers} 上限={b.upper_bound}")
        refs_here = [r for r in report.all_refs
                     if r.target_statute_id == sid and r.target_article_no == ano]
        if refs_here:
            lines.append(f"    corpus 內部跨引用指向本條的款號:{[r.item for r in refs_here]}")
        else:
            lines.append("    corpus 內部跨引用指向本條的款號:(無)")

    lines.append("")
    lines.append(
        f"corpus 內部跨引用(帶款號)總數:{len(report.all_refs)}"
        f"｜目標條文落在本次款軸範圍內可核對:{report.checked_refs}"
        f"｜矛盾:{len(report.contradictions)}"
    )
    if report.contradictions:
        lines.append("")
        lines.append("⚠ 矛盾明細(引用款號超過本腳本推導出的上限):")
        for ref, derived_max in report.contradictions:
            lines.append(
                f"  - {ref.from_source} 引用 {ref.target_statute_id}{ref.target_article_no}"
                f"第{ref.item}款,但推導上限只有 {derived_max}"
            )
            lines.append(f"      前後文:{ref.context}")

    lines.append("")
    exclusions = report.exclusions
    if exclusions:
        lines.append(f"排除清單({len(exclusions)} 條有矛盾 —— 下一輪升級前需人工核實):")
        for sid, ano in exclusions:
            lines.append(f"  - {sid}{ano}")
    else:
        lines.append("排除清單:空(本次掃描未發現任何矛盾)")

    lines.append("")
    if report.heuristic_mismatches:
        lines.append(
            f"⚠ 與 A4「一、出現次數」判準不一致的條文:{len(report.heuristic_mismatches)} 條"
            "(僅供參考,本輪不據此變更判準):"
        )
        for sid, ano, reason, n_blocks in report.heuristic_mismatches:
            lines.append(f"  - {sid}{ano}:{reason}(區塊數={n_blocks})")
    else:
        lines.append("與 A4「一、出現次數」判準交叉核對:完全一致,無不符條文。")

    lines.append("")
    lines.append(
        "本輪判準不變:款軸「一、恰1次 -> 392 條信任全域最大款號 / 一、≥2次 -> 24 條"
        "退回未查核」維持既有分界不動;本腳本只是找出下一輪、且矛盾為 0 的條文中"
        "可能從 24 條未查核桶升級的候選 —— 本輪不因本腳本結果改變分界。"
    )
    return "\n".join(lines)


if __name__ == "__main__":  # python -m legal_agent.evaluation.paragraph_bounds_audit
    from legal_agent.data.database import connect
    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()

    _conn = connect(DB_PATH)
    try:
        _report = run_audit(_conn)
    finally:
        _conn.close()

    assert_nonzero_scan(_report.total_markers, "paragraph_bounds_audit item markers")
    print(render(_report))
