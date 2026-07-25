"""裁判主文 extraction — verbatim slice + the awarded amount.

Same discipline as the statutes corpus: VERBATIM or nothing. 主文 (the
operative order) is STRUCTURALLY delimited in Taiwanese judgments, so slicing
it out is not an NLP guess — it is bounded by its own heading line and the
next section heading. 爭點/裁判要旨 stay unparsed (judicial_json.py keeps them
NULL): summarising reasoning IS an NLP task, and faking it would poison every
consumer downstream.

Three properties of real judgment text drove this design (measured against the
harvested corpus, 2026-07-23):

  1. The heading is written 「主　　　文」 / 「主　文」 — IDEOGRAPHIC SPACES
     between the characters, so a plain "主文" search misses it entirely. It
     also appears INSIDE body text quoting 民訴§436-18 (「判決書得僅記載主
     文」), so the heading must be anchored as a standalone line.
  2. The block wraps at a fixed width with indented continuation lines; a
     per-line scan splits sentences (and amounts) in half. Lines are rejoined
     before sentences are split.
  3. 主文 carries THREE kinds of money: the award (應給付), 訴訟費用 (court
     costs) and 假執行擔保 (security for provisional execution). Reporting any
     of them as "the award" would be a lie, so only 給付 sentences that carry
     neither of the other two markers are read.

Small-claims judgments (小額) write amounts in 大寫 numerals
(貳萬伍仟玖佰肆拾伍元); those are normalised to the standard forms and parsed
by the SAME numeral parser the verifier uses — one implementation, not two.
"""
from __future__ import annotations

import re

from legal_agent.anti_hallucination.verifier import _parse_number

# Standalone heading lines. \s matches U+3000 (IDEOGRAPHIC SPACE) in Unicode
# mode, which is exactly how courts pad these headings.
_MAIN_HEADING_RE = re.compile(r"^\s*主\s*文\s*$", re.MULTILINE)
_SECTION_AFTER_MAIN_RE = re.compile(
    r"^\s*(?:事\s*實\s*及\s*理\s*由|事\s*實|理\s*由\s*要\s*領|理\s*由|"
    r"犯\s*罪\s*事\s*實|附\s*表)\s*.{0,6}$",
    re.MULTILINE,
)

# 大寫 (anti-tamper) numerals -> the standard forms the shared parser knows.
_FORMAL_DIGITS = str.maketrans({
    "壹": "一", "貳": "二", "參": "三", "肆": "四", "伍": "五",
    "陸": "六", "柒": "七", "捌": "八", "玖": "九",
    "拾": "十", "佰": "百", "仟": "千",
})
_AMOUNT_RE = re.compile(
    r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩"
    r"壹貳參肆伍陸柒捌玖拾佰仟]+)\s*元"
)

# A 主文 sentence states the award only when it ORDERS payment and is not
# about costs or security — both of which also carry 元 amounts.
_AWARD_MARKERS = ("給付", "賠償")
_NOT_AWARD_MARKERS = ("訴訟費用", "程序費用", "擔保", "假執行", "免為")


def main_text(full_text: str | None) -> str | None:
    """The 主文 block, verbatim, or None when the judgment has no such heading
    (some 裁定 and older formats do not). Never guesses a boundary: without a
    following section heading the block runs to the end of the document."""
    if not full_text:
        return None
    heading = _MAIN_HEADING_RE.search(full_text)
    if heading is None:
        return None
    start = heading.end()
    end_match = _SECTION_AFTER_MAIN_RE.search(full_text, start)
    block = full_text[start: end_match.start() if end_match else len(full_text)]
    return block.strip() or None


def _sentences(block: str) -> list[str]:
    """Rejoin wrapped lines, then split on the sentence terminator. Court text
    wraps mid-sentence with indented continuations, so a line is NOT a
    sentence."""
    joined = "".join(line.strip() for line in block.splitlines())
    return [s for s in re.split(r"[。；]", joined) if s.strip()]


def award_amounts(block: str | None) -> list[int]:
    """Amounts (in 元) ordered to be PAID by the 主文 — costs and security
    excluded. Empty when the block orders no payment (e.g. 原告之訴駁回) or
    when no amount can be parsed: silence beats a wrong number."""
    if not block:
        return []
    amounts: list[int] = []
    for sentence in _sentences(block):
        if not any(m in sentence for m in _AWARD_MARKERS):
            continue
        if any(m in sentence for m in _NOT_AWARD_MARKERS):
            continue
        for raw in _AMOUNT_RE.findall(sentence):
            value = _parse_number(raw.translate(_FORMAL_DIGITS))
            if value is not None and value not in amounts:
                amounts.append(value)
    return amounts


def awards(full_text: str | None) -> tuple[int, ...]:
    """Every amount the judgment's 主文 orders paid, ascending. () when it
    orders none that can be read — the reference block then omits the figure
    instead of guessing."""
    return tuple(sorted(award_amounts(main_text(full_text))))


def format_awards(amounts) -> str:
    """Human label for the ordered payments. Deliberately NOT a single
    headline number: 29% of the harvested awards order SEVERAL payments (one
    real case orders six defendants 16.5萬–167.2萬 separately), and printing
    the largest as 「判賠 X 元」 would misstate the case. One amount is
    reported exactly; several are reported as their range, marked 多筆."""
    values = sorted(set(amounts or ()))
    if not values:
        return ""
    if len(values) == 1:
        return f"判賠 {values[0]:,} 元"
    return f"判賠 {values[0]:,}–{values[-1]:,} 元(多筆)"
