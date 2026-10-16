"""paragraph_bounds_audit.py -- upgrade path for the 款 (item) existence
axis, NOT a judging criterion. It changes nothing in verifier.py.

The verifier trusts one max 款 number for the 392 single-list articles; on
the 24 with two or more lists it flags only a 款 above every list and marks
the rest unverified (a single max would let a citation into the first 項's
list validate against a later, higher one). This script explores bounding
those 24 per block, and cross-checks against every item-numbered reference
the corpus makes to itself.

A block boundary is placed wherever the 款 marker sequence stops increasing
(民法第129條: 一,二,三 | 一,…,五); each block's bound is its own max.

"矛盾" = another article's text cites this one with a 款 above every derived
block. That is INTERNAL consistency only (no external feed), so zero
contradictions makes an article a CANDIDATE for upgrade, not a proof.

Reference resolution heuristics (read a contradiction as "worth a human
look", not a proven defect):
  * A BARE unnamed continuation (道交條例第7-2條's 「…及第九十二條第七項第六
    款」) is attributed to the citing article's own statute.
  * An explicit anaphora (「同法」「本法」「該法」…) is attributed to the
    citing statute, UNLESS its name contains exactly one other corpus id
    (違反社會秩序維護法案件處理辦法 ⊃ 社會秩序維護法): then that enabling law.
    E.g. that 辦法's §14 「本法第四十三條第一項第一款」 means 社會秩序維護法§43,
    not the 辦法's own §43. On the 17-id corpus exactly one such pair exists.

Exit code: 0 unless the scan finds zero 款 markers (assert_nonzero_scan);
contradictions and heuristic mismatches are reported, never gated.

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

# 款 marker at the start of a line: 「一、」「二、」… (re.MULTILINE is redundant
# with `(?:^|\n)` -- same counts either way -- and kept only for readability.)
_ITEM_MARKER_RE = re.compile(r"(?:^|\n)([一二三四五六七八九十百]+)、", re.MULTILINE)
_ONE_MARKER_RE = re.compile(r"(?:^|\n)一、", re.MULTILINE)

# Multi-list articles printed with a full, human-readable derivation.
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
    """Split the 款 marker sequence wherever it fails to keep increasing, so
    民法第129條's first 項 (max 三) is not bounded by the second's 五."""
    blocks: list[Block] = []
    current: list[int] = []
    prev: int | None = None
    for raw in _ITEM_MARKER_RE.findall(content):
        n = _parse_number(raw)
        if n is None:
            continue  # unreachable for this marker class; kept as a guard
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
    `statute_id`: the one other known id its name contains (a 辦法 wrapping
    its enabling law's name), else `statute_id` itself -- including when
    two or more candidates make it ambiguous."""
    parents = [kid for kid in known_ids if kid != statute_id and kid in statute_id]
    return parents[0] if len(parents) == 1 else statute_id


def _extract_cross_refs(
    statute_id: str, article_no: str, content: str, known_ids: set[str]
) -> list[CrossRef]:
    """Every item-numbered citation inside one article's own text, resolved
    to (target_statute_id, target_article_no, item) per the module
    docstring's heuristics. A name resolving to no corpus statute is dropped:
    this checks item BOUNDS, not existence.
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

        # Cross-check against the verifier's coarser 「一、」-count split --
        # informational; disagreement is surfaced, never auto-resolved.
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
        "目前判準:款軸「一、恰1次 -> 392 條信任全域最大款號 / 一、≥2次 -> 24 條只抓"
        "超過所有清單的款號,範圍內標為未查核」;本腳本列出這 24 條逐區塊上限,"
        "供日後判斷能否進一步逐項查核,不改變判準。"
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
