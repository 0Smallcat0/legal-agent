"""Gate 2 — citation verifier (spec §2.3). Independent second gate; also the
§4.2 Tier-2 evaluation tool.

Extracts BOTH citation forms and checks each against the corpus:
  (1) 條-style: 法規名稱 + 第X條 [+ 第X項/第X款]
  (2) 文號-style: ...第X號 (函釋 / 行政實務見解 / 具名實務見解), keyed by 文號
Three axes per citation: (a) exists, (b) content-match, (c) in-force. PLUS a
位階誤植 check: a 實務見解-tier source (rank 4-5) presented inside the 「法律明文」
section is flagged. On ANY failure -> flag + attach the corpus verbatim; never
delete/regenerate (spec §2.3). PURE function; structural checks need no LLM.

Each result also carries `unverified`, distinct from `flagged`: `flagged` =
checked and found wrong or unsupported; `unverified` = not confidently
checkable either way (an anaphoric reference with nothing to inherit, a
文號 this corpus does not index, a cross-reference seen only inside a
retrieved source's text, a 項/款 claim whose ceiling cannot be bounded).
`verification_status_line` claims full traceability only when both are empty.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from legal_agent.anti_hallucination.answer_structure import (
    _LAW_HEADING_RE,
    ANALYSIS_HEADING,
    PRACTICE_HEADING,
)
from legal_agent.data.models import Statute


@dataclass(frozen=True)
class Citation:
    raw: str
    statute_id: str
    article_no: str               # "第X條" for 條-style; "" for 文號-style
    paragraph: str | None = None
    item: str | None = None
    # True when the statute name was not written here and was inherited from
    # the previous named citation (「雇主依第三十二條第一項…」 inside a quoted
    # article). Gets the exists axis but not the content axis: the surrounding
    # sentence is the OTHER article's text.
    inferred_id: bool = False
    # "" (named directly) / "explicit" (ends in 同法/本法/該法/…) / "bare"
    # (unnamed prose such as 「雇主依」). Independent of `inferred_id`, which
    # records whether inheritance succeeded. See `_anaphora_kind`.
    anaphora_kind: str = ""


@dataclass(frozen=True)
class VerificationResult:
    citation: Citation
    exists: bool
    content_match: bool
    in_force: bool
    verbatim_source: str | None
    flagged: bool
    reason: str
    semantic_ok: bool = True     # optional 4th axis; True when the axis is off
    # Never True together with `flagged`: the citation was not independently
    # confirmed against the corpus (see module docstring for the cases). Not a
    # synonym for "probably fine".
    unverified: bool = False


# ── what the reader is told the check did, and did not, cover ───────────────
# Printed on every path, including the clean one: silence reads as
# endorsement, and the axes do not check applicability or reasoning
# direction (a run over eight decided rental disputes reasoned opposite to
# the outcome in four, with 0 flags in all eight).
VERIFIED_SCOPE_NOTE = (
    "查核的是條號存在、當時仍有效、內容與資料庫逐字條文相符。"
    "沒有查核這些條文是否適用於你的處境,也沒有查核推論方向是否正確 —— "
    "查核全綠不等於結論對你有利。"
)


def verification_status_line(verifications) -> str:
    """One line saying what the citation check found AND what it never looks at.

    Shared by the CLI and the web so the two cannot drift. Always returns a
    sentence: the green path is the one that most needs saying out loud.

    Three mutually exclusive buckets, in priority order: FLAGGED; else
    UNVERIFIED (`unverified` or `exists=False` without a flag); else CLEAN,
    the only case that says 「全數可回溯至資料庫」.
    """
    if not verifications:
        return f"引用查核:本回答未含條號引用。{VERIFIED_SCOPE_NOTE}"
    flagged = [v for v in verifications if v.flagged]
    if flagged:
        return (
            f"引用查核:{len(verifications)} 筆引用中 {len(flagged)} 筆有疑慮,逐筆如下。"
            f"{VERIFIED_SCOPE_NOTE}"
        )
    unverified = [v for v in verifications if v.unverified or not v.exists]
    if unverified:
        return (
            f"引用查核:{len(verifications)} 筆引用中 {len(unverified)} 筆未查核"
            f"(本庫未收錄該法源／該文號,或系統無法確認其歸屬),其餘 "
            f"{len(verifications) - len(unverified)} 筆可回溯至資料庫。{VERIFIED_SCOPE_NOTE}"
        )
    return (
        f"引用查核:{len(verifications)} 筆引用全數可回溯至資料庫。"
        f"{VERIFIED_SCOPE_NOTE}"
    )


# ── numerals: Arabic / full-width / Chinese (incl. accounting/uppercase) ────
_FULLWIDTH = {ord("０") + i: ord("0") + i for i in range(10)}
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
             # Accounting-form (大寫) digits: 69/386 shipped judgments state
             # amounts this way (「新臺幣壹拾萬伍仟伍佰伍拾陸元」).
             "壹": 1, "貳": 2, "參": 3, "肆": 4, "伍": 5,
             "陸": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_SMALL = {"十": 10, "百": 100, "千": 1000, "拾": 10, "佰": 100, "仟": 1000}
_CN_BIG = {"萬": 10000, "億": 100000000}
_CN_UPPER = "壹貳參肆伍陸柒捌玖拾佰仟"


def _parse_number(text: str) -> int | None:
    s = text.strip().translate(_FULLWIDTH).replace(",", "").replace("，", "")
    if s.isdigit():
        return int(s)
    # No digit character at all (e.g. a lone comma left by masking) -> None;
    # 「零元」/「〇元」 still parse to 0.
    if not s or not any(
        ch.isdigit() or ch in _CN_DIGIT or ch in _CN_SMALL or ch in _CN_BIG
        for ch in s
    ):
        return None
    total = section = number = 0
    prev_digit = False
    cn_run = 0      # consecutive non-zero Chinese digits
    for ch in s:
        if ch.isdigit() or ch in _CN_DIGIT:
            digit = int(ch) if ch.isdigit() else _CN_DIGIT[ch]
            # Two digits in a row are positional (一〇〇〇〇, 二〇二三), not a
            # replacement; after a unit (一千零五) `number` is 0 and this is a no-op.
            number = number * 10 + digit if prev_digit else digit
            prev_digit = True
            cn_run = cn_run + 1 if (ch in _CN_DIGIT and digit) else 0
            continue
        prev_digit = False
        if cn_run >= 2:
            return None     # 「三四千」「一兩萬」: an approximate range, not one amount
        cn_run = 0
        if ch in _CN_SMALL:
            section += (number or 1) * _CN_SMALL[ch]
            number = 0
        elif ch in _CN_BIG:
            if not (total or section or number):
                return None       # a bare 「萬」/「億」 (數萬元) states no amount
            total += (section + number) * _CN_BIG[ch]
            section = number = 0
        else:
            return None
    return total + section + number


# ── citation extraction ──────────────────────────────────────────────────────
_NUM = r"[0-9０-９〇零一二三四五六七八九十百千萬兩" + _CN_UPPER + r"]+"
# (1) 法名 + 第X[-Y]條 [之Z] [+ 項/款]. 之Z is a DISTINCT article (民法第800條之1
# ≠ 第800條) and must survive into article_no, or a ghost 之X launders into its
# real parent. The name may be closed by a bracket or followed by whitespace
# (「《民法》第440條」, 「民法 第440條」); without that, 《民法》第9999條 was
# not extracted at all.
_NAME_CLOSE = r"[》」』】〕）)]?\s*"
_CITATION_RE = re.compile(
    r"(?P<name>[一-鿿]+?)" + _NAME_CLOSE
    + r"第(?P<article>" + _NUM + r"(?:-" + _NUM + r")?)條"
    r"(?:之(?P<suffix>" + _NUM + r"))?"
    r"(?:第(?P<paragraph>" + _NUM + r")項)?"
    r"(?:第(?P<item>" + _NUM + r")款)?"
)
# (2) 文號式: ...第X號 (函釋 / 行政實務見解). Bounded by punctuation (class excludes
# 、,。) and by 條, so 「…法第72條及內政部…第123號」 cannot swallow the 條 citation.
_DOCNUM_RE = re.compile(r"(?:(?!條)[一-鿿0-9０-９A-Za-z()（）]){2,40}?第" + _NUM + r"號")
# 「第X條」 immediately after a statute name — used to recognise a cross-reference
# that a retrieved source states in its own text.
_CROSSREF_RE = re.compile(r"第(" + _NUM + r")條")
# 「第X條/項/款/目」 generally — used only to MASK a structural reference out of
# the bare-penalty-amount scan (`_bare_penalty_amounts`); a 項/款/目 number is
# not a citation on its own and is never yielded as one.
_STRUCT_REF_RE = re.compile(r"第" + _NUM + r"(?:條|項|款|目)")

# 實務見解-tier levels (rank >= 4): must NOT be presented as 「法律明文」.
_PRACTICE_TIER_LEVELS = {"函釋", "行政實務見解"}
_HEADINGS_AFTER_LAW = (PRACTICE_HEADING, ANALYSIS_HEADING)

# ── monetary amounts (for the conservative content-match pass) ───────────────
_YUAN_RE = re.compile(
    r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩" + _CN_UPPER + r"]+)\s*元"
)
_CURRENCY_RE = re.compile(r"(?:新臺幣|新台幣|NT\$|NTD|＄|\$)\s*([0-9０-９,，]+)")
# Suffix-form direction word bound to an amount (「六千元以下」). Only the
# suffix form is checked — prefix forms (逾/未滿 X 元) are rarer and riskier
# to attribute, and a conservative pass must never flag a good answer.
_AMOUNT_DIR_RE = re.compile(
    r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩" + _CN_UPPER + r"]+)"
    r"\s*元(以上|以下|以內|未滿)"
)
# Bare (no-comma) numeral class for the masked bare-penalty scan and 「X分之Y」.
# Masking a citation out of 「依中華民國刑法第223條,其…」 leaves an isolated 「,」,
# which a comma-bearing class parses as a phantom 0 amount (169/2,921 corpus
# control sentences false-positived that way).
_BARE_NUM_CLASS = r"[0-9０-９零〇一二三四五六七八九十百千萬億兩" + _CN_UPPER + r"]+"
_BARE_NUM_RE = re.compile(_BARE_NUM_CLASS)
_FRACTION_RE = re.compile("(" + _BARE_NUM_CLASS + r")分之(" + _BARE_NUM_CLASS + ")")
# 款 marker at the start of a line: 「一、」「二、」…. MULTILINE is redundant with
# `(?:^|\n)` (identical 2,037 hits / 417 rows on the corpus); kept for clarity.
_ITEM_MARKER_RE = re.compile(r"(?:^|\n)([一二三四五六七八九十百]+)、", re.MULTILINE)
_DOWNWARD = {"以下", "以內", "內", "未滿"}
_SENTENCE_BOUNDARY = "。！？!?\n；;"
# Clause separators — used only to keep two citations in ONE sentence from
# being graded on each other's numbers.
_CLAUSE_BOUNDARY = "，,、"


def _amounts(text: str) -> set[int]:
    values: set[int] = set()
    for group in _YUAN_RE.findall(text) + _CURRENCY_RE.findall(text):
        value = _parse_number(group)
        if value is not None:
            values.add(value)
    return values


# ── bare (no-「元」) penalty amounts — the wrong_amount blind spot that drops
# the currency character entirely (「處罰鍰十萬」) instead of inflating it ────────
_BARE_PENALTY_WORDS = ("罰鍰", "罰金", "罰款")
# A CLOSED filler set between a penalty word and its figure, not an N-char
# window: a window false-positives on 「…罰鍰：」 followed by a list item and on
# counts like 「受罰鍰處分三次」.
_BARE_PENALTY_BEFORE_RE = re.compile(
    r"(?:罰鍰|罰金|罰款|科處|併科)"
    r"(?:最高|最多|上限|至多|不得逾|不逾|得處|處|得科|科)?"
    r"[：:，,、]?[ \t]*$"
)
# Never whitespace: a space mask lets the `[ \t]*$` tail above see through a
# masked span (「罰金：」 + masked 「一、」 + 「三人以上…」 on 刑法第302-1條).
# `\x00` matches none of this module's character classes.
_MASK_CHAR = "\x00"


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` with every [start, end) span overwritten by `_MASK_CHAR` — same
    length, same positions, so every OTHER match's `.start()`/`.end()` in the
    masked copy still indexes correctly into the original."""
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = _MASK_CHAR
    return "".join(chars)


def _bare_penalty_amounts(text: str) -> set[int]:
    """Penalty amounts stated WITHOUT a trailing 「元」 — 「處罰鍰十萬」 instead of
    「處罰鍰十萬元」. `_amounts`/`_YUAN_RE` cannot see these at all: they require
    the 元 suffix.

    Citations, 條/項/款/目 references, fractions and 款 markers are masked
    out first, then a bare numeral run is accepted only when anchored right
    before or after a penalty word (`_BARE_PENALTY_BEFORE_RE`). Measured
    0/2,921 false positives on corpus control sentences.
    """
    spans = [
        m.span()
        for pat in (_CITATION_RE, _STRUCT_REF_RE, _FRACTION_RE, _ITEM_MARKER_RE)
        for m in pat.finditer(text)
    ]
    masked = _mask(text, spans)
    values: set[int] = set()
    for m in _BARE_NUM_RE.finditer(masked):
        start, end = m.span()
        if masked[end:end + 1] == "元":
            continue   # already counted by `_amounts`/`_YUAN_RE` — no double count
        before = masked[max(0, start - 10):start]
        after = masked[end:end + 2]
        anchored = (
            _BARE_PENALTY_BEFORE_RE.search(before) is not None
            or any(after.startswith(w) for w in _BARE_PENALTY_WORDS)
        )
        if not anchored:
            continue
        value = _parse_number(m.group(0))
        if value is not None:
            values.add(value)
    return values


# ── time periods (for the period-swap content pass) ──────────────────────────
# A numeral bound to a period unit: 「七日內」「二年以下有期徒刑」「六個月」.
# 日/天 and 週/星期 normalize to one unit. Bare 「月」 is NOT a unit (「三月」 is
# March); only 「X個月」 counts. 「半年」 (no numeral) is skipped.
_PERIOD_RE = re.compile(
    r"([0-9０-９零〇一二三四五六七八九十百千兩" + _CN_UPPER + r"]+)"
    r"\s*(個月|小時|星期|週|日|天|年)"
)
_PERIOD_UNIT_NORM = {"天": "日", "星期": "週", "個月": "月"}
# Suffix-form direction word bound to a period (「七日內」「二年以上」). Periods,
# unlike amounts, may end in a bare 「內」. Requiring it right after the unit
# excludes 「境內」/「國內」 (842 corpus matches, all genuine periods).
_PERIOD_DIR_RE = re.compile(
    r"([0-9０-９零〇一二三四五六七八九十百千兩" + _CN_UPPER + r"]+)"
    r"\s*(個月|小時|星期|週|日|天|年)(以上|以下|以內|內|未滿)"
)


def _period_label(unit: str) -> str:
    return "個月" if unit == "月" else unit


def _periods(text: str) -> dict[str, set[int]]:
    """unit -> numeric values bound to it (「七日內」 -> {"日": {7}})."""
    values: dict[str, set[int]] = {}
    for m in _PERIOD_RE.finditer(text):
        value = _parse_number(m.group(1))
        if value is not None:
            unit = _PERIOD_UNIT_NORM.get(m.group(2), m.group(2))
            values.setdefault(unit, set()).add(value)
    return values


def _period_directions(text: str) -> dict[tuple[str, int], set[str]]:
    """(unit, value) -> direction words bound to it (「七日內」 ->
    {("日", 7): {"內"}}). Catches 「七日內」 -> 「七日以上」, which `_periods`
    misses because the number is unchanged."""
    directions: dict[tuple[str, int], set[str]] = {}
    for m in _PERIOD_DIR_RE.finditer(text):
        value = _parse_number(m.group(1))
        if value is not None:
            unit = _PERIOD_UNIT_NORM.get(m.group(2), m.group(2))
            directions.setdefault((unit, value), set()).add(m.group(3))
    return directions


def _fractions(text: str) -> set[tuple[int, int]]:
    """(denominator, numerator) pairs stated as 「X分之Y」(三分之二 -> (3, 2)).
    No other axis extracts fractions, so 「三分之一」 -> 「三分之二」 needs this."""
    values: set[tuple[int, int]] = set()
    for m in _FRACTION_RE.finditer(text):
        d = _parse_number(m.group(1))
        n = _parse_number(m.group(2))
        if d is not None and n is not None:
            values.add((d, n))
    return values


def _sentence_around(text: str, start: int, end: int,
                     floor: int | None = None, ceiling: int | None = None) -> str:
    """The sentence containing [start, end), clipped to (floor, ceiling).

    The clip is what keeps citations from being graded on each other's words.
    「依社維法第72條處一萬元以下罰鍰,依民法第195條得請求非財產上之損害賠償」 是 ONE
    sentence, and unclipped, §195 gets checked against 「一萬元」 — a flag on a
    correct answer. Chinese legal prose puts the claim AFTER its citation, so:
      * right bound: the next citation (claims stop where the next one starts);
      * left bound: when another citation precedes this one in the same
        sentence, the nearest clause comma — otherwise the sentence start, which
        keeps 「處999999元罰鍰,依社維法第72條」 (claim before citation) checkable.
    """
    crowded = floor is not None
    sentence_floor = 0 if floor is None else floor
    left = sentence_floor - 1
    for ch in _SENTENCE_BOUNDARY + (_CLAUSE_BOUNDARY if crowded else ""):
        left = max(left, text.rfind(ch, sentence_floor, start))
    limit = len(text) if ceiling is None else ceiling
    rights = [pos for pos in (text.find(ch, end, limit) for ch in _SENTENCE_BOUNDARY)
              if pos != -1]
    right = min(rights) + 1 if rights else limit
    return text[left + 1: right]


def _amount_directions(text: str) -> dict[int, set[str]]:
    """amount -> the suffix direction words bound to it (「六千元以下」-> {以下})."""
    directions: dict[int, set[str]] = {}
    for match in _AMOUNT_DIR_RE.finditer(text):
        value = _parse_number(match.group(1))
        if value is not None:
            directions.setdefault(value, set()).add(match.group(2))
    return directions


def _dir_class(word: str) -> str:
    return "down" if word in _DOWNWARD else "up"


def _content_consistent(claim_scope: str, verbatim: str) -> tuple[bool, str]:
    claimed = _amounts(claim_scope) | _bare_penalty_amounts(claim_scope)
    supported = _amounts(verbatim) | _bare_penalty_amounts(verbatim)
    unsupported = claimed - supported
    if unsupported:
        return False, (
            f"主張金額 {sorted(unsupported)} 元未見於條文"
            f"(條文金額 {sorted(supported) if supported else '無'})"
        )

    # Direction: the amount is real but 以下 was flipped to 以上 (or back).
    # Fires only when both sides bind a direction to the SAME amount.
    claim_dirs = _amount_directions(claim_scope)
    source_dirs = _amount_directions(verbatim)
    for amount, claim_words in claim_dirs.items():
        source_words = source_dirs.get(amount)
        if not source_words:
            continue
        if {_dir_class(w) for w in claim_words} & {_dir_class(w) for w in source_words}:
            continue
        return False, (
            f"方向詞不符:主張 {amount}元{sorted(claim_words)[0]},"
            f"條文為 {amount}元{sorted(source_words)[0]}"
        )

    # Period: fires only when both sides state a value in the SAME unit; a
    # cross-unit paraphrase (「一個月」 as 「三十日」) is left alone.
    claim_periods = _periods(claim_scope)
    source_periods = _periods(verbatim)
    for unit, claim_values in claim_periods.items():
        source_values = source_periods.get(unit)
        if not source_values:
            continue
        unsupported_p = claim_values - source_values
        if unsupported_p:
            label = _period_label(unit)
            return False, (
                f"主張期間 {sorted(unsupported_p)[0]}{label} 未見於條文"
                f"(條文期間 {sorted(source_values)}{label})"
            )

    # Period direction: same shape as the amount-direction pass.
    claim_pdirs = _period_directions(claim_scope)
    source_pdirs = _period_directions(verbatim)
    for key, claim_words in claim_pdirs.items():
        source_words = source_pdirs.get(key)
        if not source_words:
            continue
        if {_dir_class(w) for w in claim_words} & {_dir_class(w) for w in source_words}:
            continue
        unit, value = key
        label = _period_label(unit)
        return False, (
            f"期間方向詞不符:主張 {value}{label}{sorted(claim_words)[0]},"
            f"條文為 {value}{label}{sorted(source_words)[0]}"
        )

    # Fraction: 「三分之一」 tampered into 「三分之二」 or 「二分之一」.
    claim_fracs = _fractions(claim_scope)
    source_fracs = _fractions(verbatim)
    unsupported_f = claim_fracs - source_fracs
    if unsupported_f:
        d, n = sorted(unsupported_f)[0]
        return False, (
            f"主張分數 {d}分之{n} 未見於條文"
            f"(條文分數 {sorted(source_fracs) if source_fracs else '無'})"
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


# ── paragraph(項) / item(款) existence axes ──────────────────────────────────
def _paragraph_ceiling(content: str) -> int | None:
    """1 when `content` has zero newlines — exactly one, unnumbered paragraph
    exists, so 「第N項」 with N>1 is a ghost. None with line breaks: paragraph
    boundaries are not preserved through ingestion, so the axis stands down."""
    return 1 if content.count("\n") == 0 else None


def _item_upper_bound(content: str) -> int | None:
    """The largest 款 number ANY list reaches, for an article with two or more
    lists (two regex-matched 「一」 markers). Which list a citation means is
    undecidable there, but a claimed 款 above every list is absent from all of
    them. None for zero or one list: the single-list case is `_item_ceiling`'s,
    and an article with no 「一」 marker was never measured for this rule."""
    markers = _ITEM_MARKER_RE.findall(content)
    if markers.count("一") < 2:
        return None
    numbers = [n for n in (_parse_number(g) for g in markers) if n is not None]
    return max(numbers) if numbers else None


def _item_ceiling(content: str) -> int | None:
    """The largest 款 number `content`'s own list reaches, trusted only when
    exactly one regex-matched 「一」 marker occurs. Counting raw 「一、」
    substrings over-counts (「十一、」 ends in it) and wrongly disqualified 23
    of 392 single-list articles. A second genuine 「一」 means a second list or
    nesting (民法第129條), where the max digit cannot bound a citation, so
    return None (unverified). See `paragraph_bounds_audit.py`."""
    markers = _ITEM_MARKER_RE.findall(content)
    if markers.count("一") != 1:
        return None
    numbers = [n for n in (_parse_number(g) for g in markers) if n is not None]
    return max(numbers) if numbers else None


# ── corpus lookup ────────────────────────────────────────────────────────────
_COLS = "statute_id, article_no, content, effective_from, effective_to, hierarchy_level, source_url"


def _known_ids(retrieved_context: list[Statute], conn: sqlite3.Connection | None) -> set[str]:
    if conn is not None:
        return {row[0] for row in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    return {s.statute_id for s in retrieved_context}


# Everyday short names (刑法, not 中華民國刑法 ...) for corpus statutes; each must
# point at an id that exists. Lookup is whole-name equality, never a suffix
# test: several aliases are suffixes of their canonical name, and a suffix test
# laundered the invented 公寀大廈管理條例 into 公寓大廈管理條例.
_ALIASES = {
    "刑法": "中華民國刑法",
    "勞基法": "勞動基準法",
    "社維法": "社會秩序維護法",
    "消保法": "消費者保護法",
    "公寓大廈條例": "公寓大廈管理條例",
    "大廈管理條例": "公寓大廈管理條例",
    "租賃住宅條例": "租賃住宅市場發展及管理條例",
    "道交條例": "道路交通管理處罰條例",
    "道路交通處罰條例": "道路交通管理處罰條例",
    "家暴法": "家庭暴力防治法",
    "噪音法": "噪音管制法",
}
# Shapes a Taiwanese statute name can end with. An unresolved run that looks
# like this is a NAMED source the corpus does not have (flag it — this is how
# the fake_statute mutations get caught). An unresolved run that does not is
# prose (「雇主依」、「或使勞工於」), i.e. an anaphoric reference.
_STATUTE_SHAPE_RE = re.compile(
    r"(法|條例|辦法|規則|準則|細則|通則|標準|要點|綱要|公約|自治條例|處理原則)$"
)
# Explicit back-references. They end in 法/條例 but name nothing.
_ANAPHORA_NAMES = ("同法", "本法", "該法", "前法", "同條例", "本條例", "該條例",
                   "同辦法", "本辦法", "該辦法")
# Sentence particles that glue onto a statute name in prose. Longer particles
# that are themselves prefixes of a shorter one (依據/依照/按照 vs 依/按) are
# listed FIRST so the longer, more specific strip always wins.
_LEADING_PARTICLES = ("依據", "根據", "依照", "按照", "參照", "違反",
                      "前開", "上開", "揆諸",
                      "依", "按", "及", "與", "和", "另", "並", "或", "暨")

# Tier-3 reject-list: the leftover prefix after an endswith match is refused
# only when it IS a name-type qualifier (nation/region, era marker, local-
# government suffix) — the shapes laundering uses (德國民法/舊民法/臺北市噪音
# 管制法). See `_resolve_id` for why this is a reject-list.
_TIER3_NATION_OR_REGION = (
    "德國", "美國", "日本", "法國", "中國", "大陸", "韓國", "英國", "香港",
    "澳門", "台灣", "臺灣", "新加坡",
)
# Anchored at both ends, so `.match` requires the WHOLE prefix to be the era
# token: 「原民法」 is rejected, 「原告依民法」 is not.
_TIER3_ERA_PREFIX_RE = re.compile(r"^(舊|新|前|原|現行|修正前|日治|清朝)$")
# A short (<=4 char) prefix ending in a local-government suffix — covers any
# Taiwanese administrative region (臺北市/新北市/桃園市/…縣/…鄉/…鎮/…區) by SHAPE
# rather than an exhaustive city/county list.
_TIER3_REGION_SUFFIX_RE = re.compile(r"(市|縣|鄉|鎮|區)$")


def _is_name_qualifier(prefix: str) -> bool:
    """True when `prefix` — what is left after Tier 3 strips a matched
    known_id suffix off a candidate — is a name-type qualifier rather than
    prose. Measured on 31 real legal sentences + 2 verbatim corpus articles
    (0 false rejects) and 12 laundering probes (12/12 rejected)."""
    if not prefix:
        return False
    if prefix.endswith(_TIER3_NATION_OR_REGION):
        return True
    if _TIER3_ERA_PREFIX_RE.match(prefix):
        return True
    return len(prefix) <= 4 and bool(_TIER3_REGION_SUFFIX_RE.search(prefix))


def _strip_particle(name_run: str) -> str:
    """The name without the prose particle glued to its front (依/按/及…)."""
    for particle in _LEADING_PARTICLES:
        if name_run.startswith(particle) and len(name_run) > len(particle):
            return name_run[len(particle):]
    return name_run


def _resolve_id(name_run: str, known_ids: set[str]) -> str:
    """Turn a raw citation prefix into a corpus statute_id, in three tiers.

    Tier 1 — exact match before stripping: 「違反社會秩序維護法案件處理辦法」
    is a real id, and stripping 「違反」 would turn it into a different law.

    Tier 2 — strip leading particles one at a time, checking known_ids after
    each (prose stacks them: 「並依據」), then try `_ALIASES` once.

    Tier 3 — longest known_id suffix, unless the leftover prefix is a
    name-type qualifier (`_is_name_qualifier`). A reject-list, because the
    allow-list of acceptable lead-in prose tried first rejected 24 of 31 real
    sentences (「房東依民法」「爰依民法」…) plus two verbatim corpus articles;
    acceptable prose is unbounded, name qualifiers are a small closed set.
    """
    if name_run in known_ids:
        return name_run
    current = name_run
    while True:
        if current in known_ids:
            return current
        stripped = _strip_particle(current)
        if stripped == current:
            break
        current = stripped
    canonical = _ALIASES.get(current)
    if canonical is not None and canonical in known_ids:
        return canonical
    matches = [kid for kid in known_ids if current.endswith(kid)]
    if matches:
        best = max(matches, key=len)
        prefix = current[: -len(best)]
        if not _is_name_qualifier(prefix):
            return best
    # Unresolved: return the particle-stripped name so the warning reads
    # 「corpus 查無此法源:台灣安寧保障法第3條」 rather than 「…:依台灣安寧保障法第3條」.
    return current


def _is_anaphoric(name_run: str, resolved: str, known_ids: set[str]) -> bool:
    """True when this citation names no statute of its own: either an explicit
    back-reference (同法/本法) or a run of ordinary prose (「雇主依」)."""
    if resolved in known_ids:
        return False
    if name_run.endswith(_ANAPHORA_NAMES):
        return True
    return not _STATUTE_SHAPE_RE.search(name_run)


def _anaphora_kind(name_run: str, resolved: str, known_ids: set[str]) -> str:
    """"" (a directly named citation — resolved, or unresolved-but-shaped-
    like-a-statute-name, e.g. a fabrication) / "explicit" (ends in 同法/本法/
    該法/… — a confident back-reference to "the same law") / "bare" (unnamed
    continuation prose — 「雇主依」「違反第十六條第一項」 — anaphoric for a reason
    OTHER than an explicit back-reference word). Uses `_is_anaphoric`'s
    precedence (named > explicit > shape) so the two never disagree."""
    if resolved in known_ids:
        return ""
    if name_run.endswith(_ANAPHORA_NAMES):
        return "explicit"
    if _is_anaphoric(name_run, resolved, known_ids):
        return "bare"
    return ""


def _anaphora_parent(statute_id: str, known_ids: set[str]) -> str:
    """What 「本法/同法/該法…」 means inside an article belonging to
    `statute_id` — usually `statute_id` itself, but NOT when `statute_id` is
    a subordinate instrument whose name wraps a different known id
    (違反社會秩序維護法案件處理辦法 ⊃ 社會秩序維護法): its 「本法第七十二條」
    means the enabling law. Without this, verbatim quotes of such an article
    came back flagged (2/15 verbatim_crossref articles have this shape).

    Detected structurally (substring containment), not a hardcoded pair.
    Returns `statute_id` itself when zero or several candidates exist. Used
    only as a fallback for explicit anaphora's exists/content axes; the 項/款
    axis stands down for every inherited citation regardless.
    """
    parents = [kid for kid in known_ids if kid != statute_id and kid in statute_id]
    return parents[0] if len(parents) == 1 else statute_id


def _slices(statute_id, article_no, retrieved_context, conn):
    if conn is not None:
        rows = conn.execute(
            f"SELECT {_COLS} FROM statutes WHERE statute_id = ? AND article_no = ?",
            (statute_id, article_no),
        ).fetchall()
        return [Statute(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]
    return [s for s in retrieved_context
            if s.statute_id == statute_id and s.article_no == article_no]


def _quoted_in_retrieved(citation: Citation, retrieved_context: list[Statute]) -> bool:
    """True when 「法名第X條」 occurs verbatim inside a retrieved article's text.

    A model quoting a retrieved source reproduces its cross-references; those
    are not memory-sourced citations.
    """
    if not citation.article_no:
        return False
    want = _parse_number(citation.article_no.strip("第條"))
    if want is None:
        return False
    for statute in retrieved_context:
        content = statute.content or ""
        at = content.find(citation.statute_id)
        while at != -1:
            # 「噪音管制法第8條」 and 「噪音管制法第九條」 must both count: compare the
            # PARSED number, not the glyphs.
            window = content[at + len(citation.statute_id): at + len(citation.statute_id) + 12]
            m = _CROSSREF_RE.match(window)
            if m and _parse_number(m.group(1)) == want:
                return True
            at = content.find(citation.statute_id, at + 1)
    return False


def _missing_reason(citation: Citation, corpus_conn: sqlite3.Connection | None) -> str:
    """Why a citation failed the exists axis, told accurately.

    Without a corpus connection the verifier genuinely cannot tell a fabricated
    article from a real one the retriever missed, so it says the weaker thing.
    """
    ref = f"{citation.statute_id}{citation.article_no}"
    if corpus_conn is not None and corpus_conn.execute(
        "SELECT 1 FROM statutes WHERE statute_id = ? AND article_no = ?",
        (citation.statute_id, citation.article_no),
    ).fetchone():
        return (
            f"{ref} 未出現在本次檢索結果中 — 模型可能憑記憶補充。"
            "該條文確實存在於資料庫,但本次未被檢索到,故不採信此段引用"
        )
    return f"未出現在本次檢索結果中,且 corpus 查無此法源:{ref}"


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


def _canonical_article(article: str, suffix: str | None) -> str | None:
    """Normalize a cited 條號 to the corpus form (data/moj_xml.py convention):
    「第800條之1」 and 「第800-1條」 both -> 「第800-1條」; plain -> 「第X條」.
    A malformed double form (「第800-1條之2」) keeps every part — it can only
    fail lookup, never collapse into a real article. None = unparseable."""
    main, _, hyphen_sub = article.partition("-")
    main_n = _parse_number(main)
    if main_n is None:
        return None
    subs = [p for p in (hyphen_sub, suffix) if p]
    sub_ns = [_parse_number(p) for p in subs]
    if any(n is None for n in sub_ns):
        return None
    if not sub_ns:
        return f"第{main_n}條"
    return f"第{main_n}-{'-'.join(str(n) for n in sub_ns)}條"


def _iter_citations(answer_text: str, known_ids: set[str]):
    """Yield (Citation, start_pos) for both 條-style and 文號-style references.

    Citations are walked in document order so an unnamed reference can inherit
    the statute named before it (勞基法§32-1's own text says
    「雇主依第三十二條第一項…」, which would otherwise read as a statute
    called 「雇主依」).
    """
    last_named: str | None = None
    for m in _CITATION_RE.finditer(answer_text):
        article_no = _canonical_article(m.group("article"), m.group("suffix"))
        if article_no is None:
            continue
        name_run = m.group("name")
        statute_id = _resolve_id(name_run, known_ids)
        kind = _anaphora_kind(name_run, statute_id, known_ids)
        inferred = False
        if kind and last_named is not None:
            # Inherit the statute as named; `verify_answer` falls back to
            # `_anaphora_parent` only when this fails to resolve.
            statute_id, inferred = last_named, True
        elif statute_id in known_ids:
            last_named = statute_id
        yield (
            Citation(
                raw=m.group(0),
                statute_id=statute_id,
                article_no=article_no,
                paragraph=_fmt(m.group("paragraph"), "項"),
                item=_fmt(m.group("item"), "款"),
                inferred_id=inferred,
                anaphora_kind=kind,
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
    semantic_llm=None,
    corpus_conn: sqlite3.Connection | None = None,
) -> list[VerificationResult]:
    """Verify every citation (條式 + 文號式) in `answer_text` against the corpus.
    Also flags a 實務見解-tier source placed inside the 「法律明文」 section (位階誤植).

    `semantic_llm` (optional, Callable[[str], str]): enables the 4th axis —
    semantic consistency of the claim sentence against the verbatim article
    (subject swaps, dropped preconditions). None = pure-code verifier,
    behaviour unchanged. Runs only on citations the structural axes passed.
    """
    if as_of_date is not None:
        try:
            date.fromisoformat(as_of_date)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"as_of_date must be ISO 'YYYY-MM-DD', got {as_of_date!r}"
            ) from exc

    # Name resolution may use the corpus even in retrieval-first mode: knowing
    # which statute names EXIST only helps strip leading particles (依/按/及)
    # correctly. It never makes an un-retrieved citation count as retrieved.
    known = _known_ids(retrieved_context, conn or corpus_conn)
    law_span = _law_section_span(answer_text)
    results: list[VerificationResult] = []

    # Sorted by position so each citation's claim scope can be clipped to its
    # neighbours (the two extractors below run in separate passes, so document
    # order is not the yield order).
    found = sorted(_iter_citations(answer_text, known), key=lambda cp: cp[1])
    # Only 條 citations clip each other's claim scope: a 文號 carries no amount
    # or period to grade, so 「第72條及某函第123號,處九萬元」 still belongs to 第72條.
    article_positions = [(pos, pos + len(c.raw)) for c, pos in found if c.article_no]
    for citation, pos in found:
        prev_end = max((e for s, e in article_positions if s < pos), default=None)
        next_start = min((s for s, _ in article_positions if s > pos), default=None)

        # An anaphoric citation with no named citation before it to inherit
        # from: its statute_id is a prose fragment (「法院依」), not a claimed
        # law, so a lookup would either fail falsely (four such fragments in
        # 家庭暴力防治法§61's own text) or hit an unrelated id. Not checked.
        if citation.anaphora_kind and not citation.inferred_id:
            results.append(VerificationResult(
                citation, exists=False, content_match=True, in_force=False,
                verbatim_source=None, flagged=False, unverified=True,
                reason=(f"「{citation.raw}」前面沒有可承接的具名法規引用,"
                        "系統無法確認其歸屬法規,不予查核(非造假,亦非已驗證)"),
            ))
            continue

        slices = _slices(citation.statute_id, citation.article_no, retrieved_context, conn)
        if not slices and citation.inferred_id and citation.anaphora_kind == "explicit":
            # Fallback, not a redirect: the as-named statute is right in the
            # common case (a 辦法 citing 同法 about its own articles). Redirecting
            # unconditionally regressed anaphora_period 707/707 -> 701/707.
            parent = _anaphora_parent(citation.statute_id, known)
            if parent != citation.statute_id:
                parent_slices = _slices(parent, citation.article_no, retrieved_context, conn)
                if parent_slices:
                    citation = Citation(
                        raw=citation.raw, statute_id=parent, article_no=citation.article_no,
                        paragraph=citation.paragraph, item=citation.item,
                        inferred_id=citation.inferred_id, anaphora_kind=citation.anaphora_kind,
                    )
                    slices = parent_slices
        if not slices and _quoted_in_retrieved(citation, retrieved_context):
            # Quoted verbatim inside a retrieved source (the 警察分工原則 names
            # 噪音管制法第8條), so not from memory — but the article itself was
            # not retrieved, so its content is unchecked: unverified.
            results.append(VerificationResult(
                citation, exists=False, content_match=False, in_force=False,
                verbatim_source=None, flagged=False, unverified=True,
                reason=(f"{citation.statute_id}{citation.article_no} "
                        "係檢索到的法源內文中的交叉引用(逐字出現於檢索結果),"
                        "本次未另行檢索該條,故未核對其內容"),
            ))
            continue
        if not slices:
            if citation.article_no == "":
                # The corpus indexes no rows by 文號, so "not found" says
                # nothing about whether the 函釋 is real: unverified, not flagged.
                results.append(VerificationResult(
                    citation, exists=False, content_match=True, in_force=False,
                    verbatim_source=None, flagged=False, unverified=True,
                    reason=f"{citation.raw} 此文號未收錄於本系統資料庫,不代表該函釋不存在或造假",
                ))
                continue
            # Still flagged (retrieval-first), but the reason says whether the
            # article exists in the corpus or not at all.
            results.append(VerificationResult(
                citation, exists=False, content_match=False, in_force=False,
                verbatim_source=None, flagged=True,
                reason=_missing_reason(citation, corpus_conn),
            ))
            continue

        in_force_slices = [s for s in slices if _in_force(s, as_of_date)]
        in_force = bool(in_force_slices)
        source = in_force_slices[0] if in_force else max(slices, key=lambda s: s.effective_from)

        # An explicit back-reference (本法/同法) is confident about its law, so
        # its claim is checked. A bare continuation only inherited by proximity
        # and its sentence is the other article's text: content unverified.
        axis_unverified = False
        if citation.inferred_id and citation.anaphora_kind != "explicit":
            claim_scope = ""
            content_match, cm_reason = True, ""
            axis_unverified = True
        else:
            claim_scope = _sentence_around(
                answer_text, pos, pos + len(citation.raw),
                floor=prev_end, ceiling=next_start,
            )
            content_match, cm_reason = _content_consistent(claim_scope, source.content)

        # 項/款 existence, only for citations named here: an inherited id may
        # belong to a parent law whose numbering this content cannot speak to.
        ghost_paragraph = ghost_item = False
        claimed_p = claimed_i = item_ceiling = None
        if not citation.inferred_id:
            if citation.paragraph:
                claimed_p = _parse_number(citation.paragraph.strip("第項"))
                if claimed_p is not None:
                    paragraph_ceiling = _paragraph_ceiling(source.content)
                    if paragraph_ceiling is None:
                        axis_unverified = True
                    elif claimed_p > paragraph_ceiling:
                        ghost_paragraph = True
            if citation.item:
                claimed_i = _parse_number(citation.item.strip("第款"))
                if claimed_i is not None:
                    item_ceiling = _item_ceiling(source.content)
                    if item_ceiling is None:
                        # Several lists: only a 款 above all of them is decidable.
                        item_ceiling = _item_upper_bound(source.content)
                        if item_ceiling is not None and claimed_i > item_ceiling:
                            ghost_item = True
                        else:
                            axis_unverified = True
                    elif claimed_i > item_ceiling:
                        ghost_item = True

        # 位階誤植: 實務見解-tier source presented inside the 「法律明文」 section.
        misplaced = (
            law_span is not None
            and law_span[0] <= pos < law_span[1]
            and source.hierarchy_level in _PRACTICE_TIER_LEVELS
        )

        # Optional 4th axis — only spend the model on structurally clean citations.
        semantic_ok, sem_reason = True, ""
        if (semantic_llm is not None and content_match and in_force
                and not ghost_paragraph and not ghost_item
                and not citation.inferred_id):
            from legal_agent.anti_hallucination.semantic_check import semantic_consistent
            semantic_ok, sem_reason = semantic_consistent(
                claim_scope, source.content, semantic_llm
            )

        reasons: list[str] = []
        if not content_match:
            reasons.append(cm_reason)
        if not in_force:
            reasons.append(
                f"引用非現行有效版本(as_of={as_of_date or '現行'}; "
                f"effective_to={source.effective_to})"
            )
        if not semantic_ok:
            reasons.append(sem_reason)
        if misplaced:
            reasons.append(
                f"位階誤植:{source.hierarchy_level}(實務見解層級)不應列於「法律明文」"
            )
        if ghost_paragraph:
            reasons.append(f"主張第{claimed_p}項,但條文內容未分項(僅單一段落)")
        if ghost_item:
            reasons.append(f"主張第{claimed_i}款,但條文本身最大款號僅至第{item_ceiling}款")
        flagged = (
            (not (content_match and in_force and semantic_ok))
            or misplaced or ghost_paragraph or ghost_item
        )
        results.append(VerificationResult(
            citation, exists=True, content_match=content_match, in_force=in_force,
            verbatim_source=source.content, flagged=flagged, reason="；".join(reasons),
            semantic_ok=semantic_ok, unverified=axis_unverified and not flagged,
        ))

    return results
