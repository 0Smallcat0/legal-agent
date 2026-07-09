"""Gate 2 — citation verifier (spec §2.3). Independent second gate; also the
§4.2 Tier-2 evaluation tool.

Extracts BOTH citation forms and checks each against the corpus:
  (1) 條-style: 法規名稱 + 第X條 [+ 第X項/第X款]
  (2) 文號-style: ...第X號 (函釋 / 行政實務見解 / 具名實務見解), keyed by 文號
Three axes per citation: (a) exists, (b) content-match, (c) in-force. PLUS a
位階誤植 check: a 實務見解-tier source (rank 4-5) presented inside the 「法律明文」
section is flagged. On ANY failure -> flag + attach the corpus verbatim; never
delete/regenerate (spec §2.3). PURE function; structural checks need no LLM.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from legal_agent.data.models import Statute


@dataclass(frozen=True)
class Citation:
    raw: str
    statute_id: str
    article_no: str               # "第X條" for 條-style; "" for 文號-style
    paragraph: str | None = None
    item: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    citation: Citation
    exists: bool
    content_match: bool
    in_force: bool
    verbatim_source: str | None
    flagged: bool
    reason: str


# ── numerals: Arabic / full-width / Chinese ──────────────────────────────────
_FULLWIDTH = {ord("０") + i: ord("0") + i for i in range(10)}
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_SMALL = {"十": 10, "百": 100, "千": 1000}
_CN_BIG = {"萬": 10000, "億": 100000000}


def _parse_number(text: str) -> int | None:
    s = text.strip().translate(_FULLWIDTH).replace(",", "").replace("，", "")
    if s.isdigit():
        return int(s)
    total = section = number = 0
    for ch in s:
        if ch.isdigit():
            number = number * 10 + int(ch)
        elif ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_SMALL:
            section += (number or 1) * _CN_SMALL[ch]
            number = 0
        elif ch in _CN_BIG:
            total += (section + number) * _CN_BIG[ch]
            section = number = 0
        else:
            return None
    return total + section + number


# ── citation extraction ──────────────────────────────────────────────────────
_NUM = r"[0-9０-９〇零一二三四五六七八九十百千萬兩]+"
# (1) 統名 + 第X條 [+ 項/款]
_CITATION_RE = re.compile(
    r"(?P<name>[一-鿿]+?)第(?P<article>" + _NUM + r")條"
    r"(?:之" + _NUM + r")?"
    r"(?:第(?P<paragraph>" + _NUM + r")項)?"
    r"(?:第(?P<item>" + _NUM + r")款)?"
)
# (2) 文號式: ...第X號 (函釋 / 行政實務見解). Bounded by punctuation (class excludes 、,。).
_DOCNUM_RE = re.compile(r"[一-鿿0-9０-９A-Za-z()（）]{2,40}?第" + _NUM + r"號")

# 實務見解-tier levels (rank >= 4): must NOT be presented as 「法律明文」.
_PRACTICE_TIER_LEVELS = {"函釋", "行政實務見解"}
_LAW_HEADING_RE = re.compile(r"(?<!非)法律明文")   # heading, not the "非法律明文" disclaimer
_HEADINGS_AFTER_LAW = ("實務見解", "分析研判")

# ── monetary amounts (for the conservative content-match pass) ───────────────
_YUAN_RE = re.compile(r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩]+)\s*元")
_CURRENCY_RE = re.compile(r"(?:新臺幣|新台幣|NT\$|NTD|＄|\$)\s*([0-9０-９,，]+)")
_SENTENCE_BOUNDARY = "。！？!?\n；;"


def _amounts(text: str) -> set[int]:
    values: set[int] = set()
    for group in _YUAN_RE.findall(text) + _CURRENCY_RE.findall(text):
        value = _parse_number(group)
        if value is not None:
            values.add(value)
    return values


def _sentence_around(text: str, start: int, end: int) -> str:
    left = -1
    for ch in _SENTENCE_BOUNDARY:
        left = max(left, text.rfind(ch, 0, start))
    rights = [pos for pos in (text.find(ch, end) for ch in _SENTENCE_BOUNDARY) if pos != -1]
    right = min(rights) if rights else len(text) - 1
    return text[left + 1: right + 1]


def _content_consistent(claim_scope: str, verbatim: str) -> tuple[bool, str]:
    claimed = _amounts(claim_scope)
    supported = _amounts(verbatim)
    unsupported = claimed - supported
    if unsupported:
        return False, (
            f"主張金額 {sorted(unsupported)} 元未見於條文"
            f"(條文金額 {sorted(supported) if supported else '無'})"
        )
    return True, ""


def _law_section_span(text: str) -> tuple[int, int] | None:
    m = _LAW_HEADING_RE.search(text)
    if not m:
        return None
    start = m.start()
    ends = [text.find(h, start + 4) for h in _HEADINGS_AFTER_LAW]
    ends = [e for e in ends if e != -1]
    return (start, min(ends) if ends else len(text))


# ── corpus lookup ────────────────────────────────────────────────────────────
_COLS = "statute_id, article_no, content, effective_from, effective_to, hierarchy_level, source_url"


def _known_ids(retrieved_context: list[Statute], conn: sqlite3.Connection | None) -> set[str]:
    if conn is not None:
        return {row[0] for row in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    return {s.statute_id for s in retrieved_context}


def _resolve_id(name_run: str, known_ids: set[str]) -> str:
    matches = [kid for kid in known_ids if name_run.endswith(kid)]
    return max(matches, key=len) if matches else name_run


def _slices(statute_id, article_no, retrieved_context, conn):
    if conn is not None:
        rows = conn.execute(
            f"SELECT {_COLS} FROM statutes WHERE statute_id = ? AND article_no = ?",
            (statute_id, article_no),
        ).fetchall()
        return [Statute(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]
    return [s for s in retrieved_context
            if s.statute_id == statute_id and s.article_no == article_no]


def _in_force(s: Statute, as_of_date: str | None) -> bool:
    if as_of_date is None:
        return s.effective_to is None
    return s.effective_from <= as_of_date and (
        s.effective_to is None or as_of_date < s.effective_to
    )


def _fmt(group: str | None, suffix: str) -> str | None:
    if group is None:
        return None
    n = _parse_number(group)
    return f"第{n}{suffix}" if n is not None else None


def _iter_citations(answer_text: str, known_ids: set[str]):
    """Yield (Citation, start_pos) for both 條-style and 文號-style references."""
    for m in _CITATION_RE.finditer(answer_text):
        article_num = _parse_number(m.group("article"))
        if article_num is None:
            continue
        yield (
            Citation(
                raw=m.group(0),
                statute_id=_resolve_id(m.group("name"), known_ids),
                article_no=f"第{article_num}條",
                paragraph=_fmt(m.group("paragraph"), "項"),
                item=_fmt(m.group("item"), "款"),
            ),
            m.start(),
        )
    for m in _DOCNUM_RE.finditer(answer_text):
        raw = m.group(0)
        yield (
            Citation(raw=raw, statute_id=_resolve_id(raw, known_ids), article_no=""),
            m.start(),
        )


def verify_answer(
    answer_text: str,
    retrieved_context: list[Statute],
    as_of_date: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[VerificationResult]:
    """Verify every citation (條式 + 文號式) in `answer_text` against the corpus.
    Also flags a 實務見解-tier source placed inside the 「法律明文」 section (位階誤植).
    """
    if as_of_date is not None:
        try:
            date.fromisoformat(as_of_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"as_of_date must be ISO 'YYYY-MM-DD', got {as_of_date!r}"
            ) from exc

    known = _known_ids(retrieved_context, conn)
    law_span = _law_section_span(answer_text)
    results: list[VerificationResult] = []

    for citation, pos in _iter_citations(answer_text, known):
        slices = _slices(citation.statute_id, citation.article_no, retrieved_context, conn)
        if not slices:
            results.append(VerificationResult(
                citation, exists=False, content_match=False, in_force=False,
                verbatim_source=None, flagged=True,
                reason=f"corpus 查無此法源:{citation.statute_id}{citation.article_no}",
            ))
            continue

        in_force_slices = [s for s in slices if _in_force(s, as_of_date)]
        in_force = bool(in_force_slices)
        source = in_force_slices[0] if in_force else max(slices, key=lambda s: s.effective_from)

        claim_scope = _sentence_around(answer_text, pos, pos + len(citation.raw))
        content_match, cm_reason = _content_consistent(claim_scope, source.content)

        # 位階誤植: 實務見解-tier source presented inside the 「法律明文」 section.
        misplaced = (
            law_span is not None
            and law_span[0] <= pos < law_span[1]
            and source.hierarchy_level in _PRACTICE_TIER_LEVELS
        )

        reasons: list[str] = []
        if not content_match:
            reasons.append(cm_reason)
        if not in_force:
            reasons.append(
                f"引用非現行有效版本(as_of={as_of_date or '現行'}; "
                f"effective_to={source.effective_to})"
            )
        if misplaced:
            reasons.append(
                f"位階誤植:{source.hierarchy_level}(實務見解層級)不應列於「法律明文」"
            )
        flagged = (not (content_match and in_force)) or misplaced
        results.append(VerificationResult(
            citation, exists=True, content_match=content_match, in_force=in_force,
            verbatim_source=source.content, flagged=flagged, reason="；".join(reasons),
        ))

    return results
