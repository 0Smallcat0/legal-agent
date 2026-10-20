"""Gate 2 — citation verifier (spec §2.3). Independent second gate; also the
§4.2 Tier-2 evaluation tool.

Extracts BOTH citation forms and checks each against the corpus:
  (1) 條-style: 法規名稱 + 第X條 [+ 第X項/第X款]
  (2) 文號-style: ...第X號 (函釋 / 行政實務見解 / 具名實務見解), keyed by 文號
Three axes per citation: (a) exists, (b) content-match, (c) in-force. PLUS a
位階誤植 check: a 實務見解-tier source (rank 4-5) presented inside the 「法律明文」
section is flagged. On ANY failure -> flag + attach the corpus verbatim; never
delete/regenerate (spec §2.3). PURE function; structural checks need no LLM.

Every `VerificationResult` carries a THIRD state alongside `flagged`, added
2026-08-17 (blind-spot round): `unverified`. `flagged` means "checked and
found wrong or unsupported"; `unverified` means "not confidently checkable
either way" — an anaphoric reference with nothing to inherit from, a
文號-style citation this corpus does not index at all, a cross-reference only
confirmed by appearing inside a retrieved source's own text, or a
paragraph/item claim this system's structural rules cannot bound. Neither
state implies the other, and `verification_status_line` only claims full
traceability when BOTH are empty. See each function's docstring below for the
specific measured failure it closes.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from legal_agent.data.models import Statute
from legal_agent.evaluation import assert_nonzero_scan


@dataclass(frozen=True)
class Citation:
    raw: str
    statute_id: str
    article_no: str               # "第X條" for 條-style; "" for 文號-style
    paragraph: str | None = None
    item: str | None = None
    # True when the statute name was NOT written at this citation and had to be
    # inherited from the previous named one (「雇主依第三十二條第一項…」 inside a
    # quoted article). Such a reference still gets the exists axis, but not the
    # content axis: its surrounding sentence is the OTHER article's text, so a
    # content comparison would measure the wrong thing.
    inferred_id: bool = False
    # "" (a directly named citation) / "explicit" (ends in 同法/本法/該法/…, a
    # confident back-reference to "the same law") / "bare" (unnamed
    # continuation prose — 「雇主依」「違反第十六條第一項」 — anaphoric for a reason
    # OTHER than an explicit back-reference word). Computed independently of
    # whether `inferred_id` ended up True: a bare fragment at the very start
    # of an isolated quote (no NAMED citation anywhere before it in the
    # answer) is exactly as unnamed as one later on — only inheritance
    # SUCCESS differs, and that is `inferred_id`'s job, not this field's. See
    # `_anaphora_kind`.
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
    # Narrower than `flagged`, never both at once by construction: "this
    # citation was not independently confirmed against the corpus" — a
    # 文號-style reference this corpus does not index, a bare/no-antecedent
    # anaphoric fragment, a citation confirmed only by appearing inside a
    # retrieved source's own quoted text, or a paragraph/item claim whose
    # ceiling this system's structural rules cannot bound. Not a synonym for
    # "probably fine" — `verification_status_line` treats it as distinct from
    # "traceable".
    unverified: bool = False


# ── what the reader is told the check did, and did not, cover ───────────────
# The clean path used to render NOTHING at all in the CLI: `run.py._format_result`
# printed the verification block only when something was flagged, so a run with
# no flags showed no verification section, and silence reads as endorsement. A
# full pipeline run over eight already-decided rental disputes reasoned OPPOSITE
# to the recorded outcome in four of them, and `flagged_count` was 0 in all
# eight. Nothing on screen was wrong; the axes had certified exactly what they
# certify. What was missing is the sentence saying what they do not.
VERIFIED_SCOPE_NOTE = (
    "查核的是條號存在、當時仍有效、內容與資料庫逐字條文相符。"
    "沒有查核這些條文是否適用於你的處境,也沒有查核推論方向是否正確 —— "
    "查核全綠不等於結論對你有利。"
)


def verification_status_line(verifications) -> str:
    """One line saying what the citation check found AND what it never looks at.

    Shared by the CLI and the web so the two cannot drift. Always returns a
    sentence: the green path is the one that most needs saying out loud.

    Three mutually-exclusive buckets, computed in priority order so they sum
    to `len(verifications)`: FLAGGED (checked, wrong/unsupported) first —
    whether or not some of the other citations are merely unverified does not
    change how this sentence reads when at least one is flagged, exactly as
    it read before this field existed. Otherwise UNVERIFIED (not flagged, but
    either explicitly `unverified` or `exists=False` without being flagged —
    the retrieval-quoted-crossref and 文號 cases). Otherwise CLEAN — the ONLY
    case that gets to say "全數可回溯至資料庫".
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
             # Accounting-form (大寫) digits — measured 2026-08-17: 69/386
             # shipped judgments state an amount this way (「新臺幣壹拾萬伍仟伍佰
             #伍拾陸元」), and _parse_number silently read every one of them as
             # 0 (only "萬" survived the old digit table, the rest fell into
             # the "unknown char -> None" branch mid-string... no: the OLD
             # digit table simply had no entry for 壹, so `_parse_number`
             # returned None the moment it hit the leading 壹). Judgment award
             # amounts are the load-bearing use of this table outside statute
             # citations, so this is not a theoretical gap.
             "壹": 1, "貳": 2, "參": 3, "肆": 4, "伍": 5,
             "陸": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_SMALL = {"十": 10, "百": 100, "千": 1000, "拾": 10, "佰": 100, "仟": 1000}
_CN_BIG = {"萬": 10000, "億": 100000000}
_CN_UPPER = "壹貳參肆伍陸柒捌玖拾佰仟"


def _parse_number(text: str) -> int | None:
    s = text.strip().translate(_FULLWIDTH).replace(",", "").replace("，", "")
    if s.isdigit():
        return int(s)
    # A masked/clipped scan can leave a lone punctuation mark or an empty
    # string behind (see `_bare_penalty_amounts`'s docstring for the measured
    # failure this closes: reusing a comma-bearing digit class on masked text
    # parsed the isolated clause comma it left behind as a bare {0} amount).
    # Any non-empty input containing at least one real digit character still
    # legitimately parses to 0 (「零元」, 「〇元」) — only the ABSENCE of every
    # digit character returns None here, not a computed-zero result.
    if not s or not any(
        ch.isdigit() or ch in _CN_DIGIT or ch in _CN_SMALL or ch in _CN_BIG
        for ch in s
    ):
        return None
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
_NUM = r"[0-9０-９〇零一二三四五六七八九十百千萬兩" + _CN_UPPER + r"]+"
# (1) 統名 + 第X[-Y]條 [之Z] [+ 項/款]. The 之Z suffix is a DISTINCT article
# (民法第800條之1 ≠ 第800條) — it must survive into article_no, never be
# silently dropped, or a ghost 之X citation gets laundered into its real parent.
# The statute name may be closed by a bracket or separated by whitespace before
# 第X條 — 「根據《民法》」第440條」 and 「民法 第440條」 are how models actually write.
# Measured on a lived session: WITHOUT this, 《民法》第9999條 (a pure fabrication)
# was extracted as nothing at all, so the citation verifier never saw it. A gate
# that silently skips a whole writing style is worse than a noisy one.
_NAME_CLOSE = r"[》」』】〕）)]?\s*"
_CITATION_RE = re.compile(
    r"(?P<name>[一-鿿]+?)" + _NAME_CLOSE
    + r"第(?P<article>" + _NUM + r"(?:-" + _NUM + r")?)條"
    r"(?:之(?P<suffix>" + _NUM + r"))?"
    r"(?:第(?P<paragraph>" + _NUM + r")項)?"
    r"(?:第(?P<item>" + _NUM + r")款)?"
)
# (2) 文號式: ...第X號 (函釋 / 行政實務見解). Bounded by punctuation (class excludes 、,。).
_DOCNUM_RE = re.compile(r"[一-鿿0-9０-９A-Za-z()（）]{2,40}?第" + _NUM + r"號")
# 「第X條」 immediately after a statute name — used to recognise a cross-reference
# that a retrieved source states in its own text.
_CROSSREF_RE = re.compile(r"第(" + _NUM + r")條")
# 「第X條/項/款/目」 generally — used only to MASK a structural reference out of
# the bare-penalty-amount scan (`_bare_penalty_amounts`); a 項/款/目 number is
# not a citation on its own and is never yielded as one.
_STRUCT_REF_RE = re.compile(r"第" + _NUM + r"(?:條|項|款|目)")

# 實務見解-tier levels (rank >= 4): must NOT be presented as 「法律明文」.
_PRACTICE_TIER_LEVELS = {"函釋", "行政實務見解"}
_LAW_HEADING_RE = re.compile(r"(?<!非)法律明文")   # heading, not the "非法律明文" disclaimer
_HEADINGS_AFTER_LAW = ("實務見解", "分析研判")

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
# Bare (no comma) numeral class — for the masked bare-penalty-amount scan and
# for 「X分之Y」 fractions. A comma-bearing class is deliberately NOT reused
# here: masking a citation/crossref/fraction span out of a control sentence
# like 「依中華民國刑法第223條,其規範內容如條文所示。」 leaves an isolated 「,」
# behind, and `_YUAN_RE`'s comma-bearing class parses that lone comma as a
# phantom {0} amount (measured: 169/2,921 real corpus control sentences
# false-positive this way before the comma was dropped from this class).
_BARE_NUM_CLASS = r"[0-9０-９零〇一二三四五六七八九十百千萬億兩" + _CN_UPPER + r"]+"
_BARE_NUM_RE = re.compile(_BARE_NUM_CLASS)
_FRACTION_RE = re.compile("(" + _BARE_NUM_CLASS + r")分之(" + _BARE_NUM_CLASS + ")")
# 款 marker at the start of a line: 「一、」「二、」… `re.MULTILINE` is kept for
# what it documents (「^」 = line start) even though it is, measured, a no-op
# for this exact pattern: `(?:^|\n)` already covers the newline case
# MULTILINE would add — confirmed identical hit/row counts (2,037 hits / 417
# rows) across the full 2,923-row corpus with the flag on or off. Kept for
# clarity, not load-bearing (matches `paragraph_bounds_audit.py`'s own note).
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
# Tight, CLOSED filler set between a penalty word and the number it governs —
# not "any N characters" (measured to false-positive on real corpus text: a
# numbered list's own item-1 text starting with a numeral right after a
# colon-terminated 「…罰鍰：」 clause, and 「受罰鍰處分三次」 where the number is a
# COUNT, not an amount — both sit within any small fixed window). Anchored
# instead on the actual small vocabulary Chinese legal prose uses between a
# penalty word and its figure.
_BARE_PENALTY_BEFORE_RE = re.compile(
    r"(?:罰鍰|罰金|罰款|科處|併科)"
    r"(?:最高|最多|上限|至多|不得逾|不逾|得處|處|得科|科)?"
    r"[：:，,、]?[ \t]*$"
)
# A placeholder that is NEVER whitespace: masking with spaces lets the BEFORE
# anchor above "see through" a masked span via its own `[ \t]*$` tail (「…罰
# 金：」 + a masked 「一、」 item marker + 「三人以上…」 reads as "罰金：" immediately
# followed by whitespace followed by "三" once the marker becomes two spaces —
# a real, measured false positive on 中華民國刑法第302-1條). `\x00` cannot
# appear in real legal text and matches none of this module's character
# classes, so a masked run can never look "adjacent" to what preceded it.
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
    the 元 suffix, so a claim that drops it sails through the existing
    content-match check with an empty claimed-amounts set.

    Masks out every citation (`_CITATION_RE`), 條/項/款/目 cross-reference
    (`_STRUCT_REF_RE`), fraction (`_FRACTION_RE`), and 款 list marker
    (`_ITEM_MARKER_RE`) span first — a real article's own article/paragraph/
    item numbers and enumerated-list markers are not penalty amounts — then
    scans what is left for a bare numeral run anchored immediately before or
    after one of 罰鍰/罰金/罰款/科處/併科 (see `_BARE_PENALTY_BEFORE_RE`'s
    docstring for why the anchor is a closed filler set, not a character
    window). Sequenced deliberately narrow: measured 0/2,921 false positives
    on the full corpus's own real control-shaped sentences AND 0/2,921 hits
    scanning every current article's own verbatim content before being wired
    into `_content_consistent`.
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
# 日/天 and 週/星期 normalize to one unit. Bare 「月」 is deliberately NOT a
# unit — 「三月」 is a date (March); only the 「X個月」 form counts. 「半年」
# (no numeral) is skipped — conservative pass, misses documented in RESULTS.
_PERIOD_RE = re.compile(
    r"([0-9０-９零〇一二三四五六七八九十百千兩" + _CN_UPPER + r"]+)"
    r"\s*(個月|小時|星期|週|日|天|年)"
)
_PERIOD_UNIT_NORM = {"天": "日", "星期": "週", "個月": "月"}
# Suffix-form direction word bound to a period (「七日內」「二年以上」). Periods
# can end in a BARE 「內」 with no 「以」 prefix — amounts cannot (`_AMOUNT_DIR_RE`
# has no bare-內 alternative) — so `_DOWNWARD` above carries both forms. The
# regex requires the direction word to sit immediately after the unit, which
# by construction excludes 「境內」/「國內」 (nothing period-shaped precedes
# 「內」 there): measured 842 matches across the full corpus, all clean period
# phrases, 0 contamination from those two words.
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
    {("日", 7): {"內"}}). Same conservative shape as `_amount_directions`:
    only pairs a direction word to a period value already anchored to it in
    THIS text — a period-axis twin of the existing amount-direction check,
    closing the period_direction_flip blind spot (「七日內」 flipped to 「七日
    以上」: `_periods` above compares only the NUMBER, 7, so a flipped
    direction word passes it silently)."""
    directions: dict[tuple[str, int], set[str]] = {}
    for m in _PERIOD_DIR_RE.finditer(text):
        value = _parse_number(m.group(1))
        if value is not None:
            unit = _PERIOD_UNIT_NORM.get(m.group(2), m.group(2))
            directions.setdefault((unit, value), set()).add(m.group(3))
    return directions


def _fractions(text: str) -> set[tuple[int, int]]:
    """(denominator, numerator) pairs stated as 「X分之Y」(三分之二 -> (3, 2)).
    Closes the fraction_tamper blind spot: no existing axis extracts a
    fraction at all, so 「三分之一」 tampered into 「三分之二」 or 「二分之一」 is
    invisible to `_amounts`/`_periods`/direction checks alike."""
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

    # Direction check (the mutation test's direction_flip blind spot): the
    # amount is real, but 以下 was flipped to 以上 (or vice versa). Only fires
    # when BOTH sides bind a direction word to the SAME amount and the
    # direction classes share nothing — paraphrases without a direction word
    # are left alone.
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

    # Period check (the period_swap blind spot, found 2026-07-19 when the demo
    # copy almost advertised a catch that did not exist): same conservative
    # shape as the direction pass — only fires when BOTH sides state a value
    # in the SAME unit. A cross-unit paraphrase (「一個月」 restated as
    # 「三十日」) is left alone: the source has no 日-value to judge against.
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

    # Period DIRECTION check (period_direction_flip blind spot): same shape
    # as the amount-direction pass, for periods — 「七日內」 flipped to 「七日以
    # 上」 keeps the same value (7) so the period check above cannot see it.
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

    # Fraction check (fraction_tamper blind spot): 「三分之一」 tampered into
    # 「三分之二」 or 「二分之一」 — invisible to every check above.
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
    exists, so a claimed 「第N項」 with N>1 is checkable as fabricated (民法
    第793條: single sentence, 0 newlines, no 「第2項」 anywhere — 「第793條第99
    項」 is provably a ghost). None when it has line breaks: this system does
    not parse where 「第N項」 boundaries fall inside multi-paragraph content
    (the source's own paragraph indentation is not preserved through
    ingestion), so it genuinely cannot say where the true ceiling is — the
    axis stands down (unverified) rather than guess. See
    `paragraph_axis_population` for the corpus-wide split this produces."""
    return 1 if content.count("\n") == 0 else None


def _item_ceiling(content: str) -> int | None:
    """The largest 款 number `content`'s OWN numbered list reaches, trusted
    ONLY when a marker matching EXACTLY 「一」 — counted from
    `_ITEM_MARKER_RE`'s own REGEX MATCHES, not a raw substring count of
    「一、」 — occurs exactly once. A raw substring count over-counts: 「十一、」
    /「二十一、」/… also contain 「一、」 as their tail, so counting substrings
    wrongly disqualified 23 of 392 genuinely single-list articles as
    "ambiguous" (measured against mutation.py's independently-generated
    ghost_item population, e.g. 中華民國刑法第5條 whose list runs 一 through
    十一 — 「十一、」's own trailing 「一、」 made the raw count 2). A second
    GENUINE 「一」 marker (by regex match) means either a second, separate
    enumerated list inside the same article or true nesting (民法第129條 has
    two 項, one capped at 三, the next at 五 — treating the whole article as a
    single running list would let a fabricated 「第五款」 reference to the
    FIRST 項 pass). The flat "take the max digit found" rule cannot tell
    which run of markers bounds a given citation in that case, so it stands
    down (None = unverified) rather than guess. See
    `paragraph_bounds_audit.py` for the per-block upgrade path this round
    does not use, and `item_axis_population` for the corpus-wide split."""
    markers = _ITEM_MARKER_RE.findall(content)
    if markers.count("一") != 1:
        return None
    numbers = [n for n in (_parse_number(g) for g in markers) if n is not None]
    return max(numbers) if numbers else None


def paragraph_axis_population(conn: sqlite3.Connection) -> tuple[int, int]:
    """(checkable, total) current-in-force article rows for the paragraph-
    existence axis — `checkable` is how many have zero newlines
    (`_paragraph_ceiling` returns non-None for them); `total` is every
    current article row. Exposed so mutation.py's ghost_paragraph generator
    and RESULTS.md's coverage line read the SAME population `verify_answer`'s
    own axis trusts, rather than a second, possibly-drifted count computed
    by hand."""
    rows = conn.execute(
        "SELECT content FROM statutes WHERE article_no != '' AND effective_to IS NULL"
    ).fetchall()
    assert_nonzero_scan(len(rows), "paragraph_axis_population: current article rows")
    checkable = sum(1 for (content,) in rows if _paragraph_ceiling(content or "") is not None)
    return checkable, len(rows)


def item_axis_population(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """(checkable, ambiguous, total): `checkable` = current article rows
    where `_item_ceiling` would return non-None (a marker matching exactly
    「一」 occurs exactly once, by REGEX match — see `_item_ceiling`'s
    docstring for why a raw substring count of 「一、」 over-counts);
    `ambiguous` = rows with 2+ such markers (retired to unverified); `total`
    = every current article row."""
    rows = conn.execute(
        "SELECT content FROM statutes WHERE article_no != '' AND effective_to IS NULL"
    ).fetchall()
    assert_nonzero_scan(len(rows), "item_axis_population: current article rows")
    counts = [_ITEM_MARKER_RE.findall(content or "").count("一") for (content,) in rows]
    checkable = sum(1 for c in counts if c == 1)
    ambiguous = sum(1 for c in counts if c >= 2)
    return checkable, ambiguous, len(rows)


def period_direction_axis_coverage(conn: sqlite3.Connection) -> int:
    """How many number+unit+direction-word matches exist across every
    current-in-force article — the population `_period_directions` has
    anything to check against. 0 here means the regex itself broke, not that
    Taiwan statutes stopped writing period bounds (measured: 842)."""
    rows = conn.execute(
        "SELECT content FROM statutes WHERE article_no != '' AND effective_to IS NULL"
    ).fetchall()
    hits = sum(len(_PERIOD_DIR_RE.findall(content or "")) for (content,) in rows)
    assert_nonzero_scan(hits, "period_direction_axis_coverage: matches")
    return hits


def fraction_axis_coverage(conn: sqlite3.Connection) -> int:
    """How many 「X分之Y」 matches exist across every current-in-force
    article (e.g. 民法第1144條's 二分之一/三分之二)."""
    rows = conn.execute(
        "SELECT content FROM statutes WHERE article_no != '' AND effective_to IS NULL"
    ).fetchall()
    hits = sum(len(_FRACTION_RE.findall(content or "")) for (content,) in rows)
    assert_nonzero_scan(hits, "fraction_axis_coverage: matches")
    return hits


def bare_penalty_axis_coverage(conn: sqlite3.Connection) -> tuple[int, int]:
    """(hits, rows_scanned) from applying `_bare_penalty_amounts` to every
    current-in-force article's own verbatim text. Unlike the other three
    axis-coverage functions above, `hits` is EXPECTED to be near zero: real
    statutes almost always write a stated amount WITH a trailing 「元」, so a
    correctly-working masked/anchored scanner finds little to flag in
    genuinely correct text — that is exactly what the 0/2,921 false-positive
    sweep in RESULTS.md measures, and it is the axis working, not broken.
    `assert_nonzero_scan` therefore guards `rows_scanned` (did the query run
    against a real, non-empty corpus) rather than `hits` (which would raise a
    false alarm on a correctly-working axis)."""
    rows = conn.execute(
        "SELECT content FROM statutes WHERE article_no != '' AND effective_to IS NULL"
    ).fetchall()
    assert_nonzero_scan(len(rows), "bare_penalty_axis_coverage: rows scanned")
    hits = sum(len(_bare_penalty_amounts(content or "")) for (content,) in rows)
    return hits, len(rows)


# ── corpus lookup ────────────────────────────────────────────────────────────
_COLS = "statute_id, article_no, content, effective_from, effective_to, hierarchy_level, source_url"


def _known_ids(retrieved_context: list[Statute], conn: sqlite3.Connection | None) -> set[str]:
    if conn is not None:
        return {row[0] for row in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    return {s.statute_id for s in retrieved_context}


# Everyday short names for corpus statutes. A model (and a person) writes 刑法,
# not 中華民國刑法 — and the verifier used to answer 「corpus 查無此法源」 to a
# perfectly correct citation. An alias may only point at an id that EXISTS in
# the corpus.
#
# That rule is NOT sufficient on its own, and the comment here used to claim it
# was ("this can never launder an invented statute into a real one"). Measured
# false on the live demo, 2026-08-04: several aliases are SUFFIXES of their own
# canonical name (大廈管理條例, 道路交通處罰條例), so a suffix test resolved the
# invented 公寀大廈管理條例 into 公寓大廈管理條例 and passed it on all three
# axes. The alias lookup is therefore whole-name equality after the sentence
# particle — never a suffix test.
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

# Tier-3 reject-list: a CLOSED set of NAME-TYPE qualifiers. A prefix left over
# after Tier 3's endswith match is rejected ONLY when it IS one of these —
# nation/region name, era marker, or a short local-government suffix — the
# shapes an actual laundering probe uses (德國民法/舊民法/中國民法/臺北市噪音管制
# 法/美國中華民國刑法). Everything else is accepted. See `_resolve_id`'s
# docstring for why this is a reject-list and not the allow-list of "verb
# characters" that was tried first and measured to reject 24/31 real
# Taiwanese legal sentences plus two verbatim corpus articles.
_TIER3_NATION_OR_REGION = (
    "德國", "美國", "日本", "法國", "中國", "大陸", "韓國", "英國", "香港",
    "澳門", "台灣", "臺灣", "新加坡",
)
# fullmatch, not match/search: the prefix must BE the era token, not merely
# START with one. `.match()` here (this constant's original form) rejected
# 「原告依民法」 as an era-prefixed law name — "原" IS a valid standalone era
# marker (「原民法」= "the former Civil Code"), but 「原告依」("the plaintiff,
# pursuant to,") only happens to start with the same character. Requiring the
# WHOLE prefix to be nothing but the era token (「舊」/「原」/「修正前」…) catches
# the laundering shape without catching an ordinary noun that starts the same
# way (measured false positive, mutation.py's prose_prefix regression net).
_TIER3_ERA_PREFIX_RE = re.compile(r"^(舊|新|前|原|現行|修正前|日治|清朝)$")
# A short (<=4 char) prefix ending in a local-government suffix — covers any
# Taiwanese administrative region (臺北市/新北市/桃園市/…縣/…鄉/…鎮/…區) by SHAPE
# rather than an exhaustive city/county list.
_TIER3_REGION_SUFFIX_RE = re.compile(r"(市|縣|鄉|鎮|區)$")


def _is_name_qualifier(prefix: str) -> bool:
    """True when `prefix` — what is left after Tier 3 strips a matched
    known_id suffix off a candidate — is a closed-list NAME-TYPE qualifier
    (the shape a laundering probe uses) rather than ordinary prose. Measured
    (2026-08-17) against 31 real Taiwanese legal sentences + 2 verbatim
    corpus articles (消保法§50, 家暴法§58-2) + 12 hand-built laundering probes:
    0 false rejects, 12/12 probes correctly rejected."""
    if not prefix:
        return False
    if prefix.endswith(_TIER3_NATION_OR_REGION):
        return True
    if _TIER3_ERA_PREFIX_RE.match(prefix):
        return True
    return len(prefix) <= 4 and _TIER3_REGION_SUFFIX_RE.search(prefix) is not None


def _strip_particle(name_run: str) -> str:
    """The name without the prose particle glued to its front (依/按/及…)."""
    for particle in _LEADING_PARTICLES:
        if name_run.startswith(particle) and len(name_run) > len(particle):
            return name_run[len(particle):]
    return name_run


def _resolve_id(name_run: str, known_ids: set[str]) -> str:
    """Turn a raw citation prefix into a corpus statute_id, in three tiers.

    Tier 1 — exact match, UNSTRIPPED. The raw run is checked against
    known_ids before anything is peeled off it: 「違反社會秩序維護法案件處理辦
    法」 is itself a real corpus id, and stripping its leading 「違反」 (one of
    the particles below) would shear it down into 「社會秩序維護法」 — a
    DIFFERENT, also-real law. Checking the whole string first is the only way
    both survive as themselves.

    Tier 2 — check after EACH strip, not once at the end. Real prose stacks
    particles (「並依」「並依據」), so this loops: strip one leading particle,
    check known_ids immediately (short-circuit on a hit), stop when a strip
    makes no further progress. `_ALIASES` is then tried once against
    whatever the loop settled on (every alias — 刑法, 勞基法… — is a
    whole-name match, never a suffix test: see the note above `_ALIASES` on
    why a suffix alias can launder a typo into a real name).

    Tier 3 — endswith, gated by a REJECT-list, not an allow-list. Plain
    `[kid for kid in known_ids if name_run.endswith(kid)]` (this function's
    entire body until 2026-08-17) accepts the longest suffix match
    unconditionally, which is how 「德國民法」/「舊民法」/「中國民法」/「臺北市噪音
    管制法」/「美國中華民國刑法」 all launder into a real statute and come back
    exists=True, flagged=False.

    The fix is NOT "require the prefix to look like a verb" — an allow-list
    of "acceptable" lead-in characters was tried first and measured to reject
    24 of 31 real Taiwanese legal sentences (「房東依民法」「查民法」「爰依民
    法」…) plus two real, VERBATIM corpus articles (消保法§50's 「…包括民法第一
    百九十四條…」, 家庭暴力防治法§58-2's 「被害人因具民法第一千一百十八條之一…」)
    that CONTRIBUTING.md's "verbatim or nothing" rule guarantees will reach
    this function unparaphrased. An allow-list of acceptable prose is
    unbounded; a reject-list of name-type qualifiers (see `_is_name_qualifier`)
    is closed and small — only a prefix that IS a nation/region/era marker is
    refused; everything else is accepted.
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
    OTHER than an explicit back-reference word). Mirrors `_is_anaphoric`'s own
    three-way precedence (named > explicit > shape-check) so the two never
    disagree about whether a citation is anaphoric at all — this just names
    WHICH kind, for `verify_answer`'s content-check/paragraph-item-axis
    gating and the C3 unverified-before-slices routing."""
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
    a subordinate instrument whose own name textually WRAPS a DIFFERENT
    known id (違反社會秩序維護法案件處理辦法 contains 社會秩序維護法): such a
    辦法/細則/規則/準則 conventionally means its enabling law when it says 「本
    法」, not itself — 違反社會秩序維護法案件處理辦法§11's own text says 「本法第
    七十二條…」 meaning 社會秩序維護法第72條; the 辦法 has no §72 of its own, so
    without this, a VERBATIM quote of the 辦法's own real text comes back
    exists=False, flagged=True on a correct answer (measured: 2/15 corpus
    articles with this exact shape, via mutation.py's verbatim_crossref
    class).

    Detected structurally — does `statute_id` CONTAIN a different known id as
    a substring — not a hardcoded pair, so it generalises to any future
    辦法/母法 pair the corpus grows without another edit here. Falls back to
    `statute_id` itself when no such unambiguous parent exists, or when more
    than one candidate is found (ambiguous — do not guess).

    Used ONLY for EXPLICIT anaphora's exists/content-match resolution — the
    paragraph/item axis still stands down for every `inferred_id` citation
    regardless of what this resolves to (see the A3/A4 note in
    `verify_answer`: even the CORRECT parent's own 項/款 numbering is not
    confidently checkable from an inherited reference). Mirrors
    `paragraph_bounds_audit.py`'s own helper of the same name and contract —
    that module's docstring is explicit that its upgrade path does not change
    this round's judgment standard; this is the same narrow fix applied only
    to the exists/content axes that A5 already governs.
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

    Statutes and 實務見解 cross-reference each other constantly, and a model
    quoting a retrieved source reproduces those references. Treating them as
    unretrieved citations produced three warnings on the best noise answer the
    system has ever given.
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
    the statute named before it — quoted articles are full of them
    (勞基法§32-1's own text says 「雇主依第三十二條第一項…」), and reading each as
    a standalone citation of a statute called 「雇主依」 produced three scary
    「corpus 查無此法源」 warnings on a correct answer in a real session.
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
            # Inherit the statute AS NAMED — a subordinate instrument's
            # (辦法/細則/規則/準則) own "本法/同法" MAY mean its enabling law
            # instead of itself (see `_anaphora_parent`), but not always: the
            # SAME wrapping statute is also cited plenty of times about its
            # OWN other articles. `Citation.statute_id` therefore stays the
            # direct, syntactic inheritance here; `verify_answer` tries this
            # value FIRST and only falls back to `_anaphora_parent` when it
            # fails to resolve — see the comment at that call site for why
            # "always redirect" regressed a real, measured population.
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
    for index, (citation, pos) in enumerate(found):
        prev_end = (
            found[index - 1][1] + len(found[index - 1][0].raw) if index else None
        )
        next_start = found[index + 1][1] if index + 1 < len(found) else None

        # A5/C3: an anaphoric citation (bare OR explicit 「同法/本法…」) that
        # never inherited a real statute_id — no NAMED citation preceded it
        # anywhere earlier in this answer — is routed to "not checked" BEFORE
        # `_slices`/`_quoted_in_retrieved` are even consulted. Its statute_id
        # is a stripped prose fragment (「法院依」、「準用」…), not a claimed law
        # name: looking it up would either fail (today's false 「corpus 查無此
        # 法源」 on 家庭暴力防治法§61's own verbatim text — four such fragments,
        # zero of them a fabricated law) or, worse, coincidentally match an
        # unrelated real id. It is not a fabrication (it never claimed to BE
        # a law) and it is not confirmed-real either.
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
            # Fallback, not a redirect: try the statute AS NAMED first (the
            # syntactic inheritance `_iter_citations` stored) — that is
            # correct for the common case (a 辦法 citing "同法" about its OWN
            # other articles), and trying it FIRST is what keeps that case
            # correct. Only when that article genuinely does not exist under
            # the as-named statute does an "本法/同法" inside a 辦法/細則/規則/
            # 準則 whose name wraps a different real statute retry under that
            # enabling law (`_anaphora_parent`) — fixing a verbatim quote of
            # 違反社會秩序維護法案件處理辦法§11/§13's own real text ("本法第七十
            # 二條…") without touching the far more common self-reference case
            # (measured: redirecting unconditionally at inheritance time
            # regressed anaphora_period's own catch rate from 707/707 to
            # 701/707 — six cases that legitimately meant the 辦法 itself).
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
            # The reference appears VERBATIM inside a retrieved source's own text
            # (the 警察分工原則 names 噪音管制法第8條/第9條 in its body). The model
            # copied it from material it was given, so 「模型可能憑記憶補充」 is
            # false — but the referenced article itself was not retrieved, so its
            # content stays unchecked and unrelied-upon. Say exactly that.
            # B4/unverified: this citation was never independently checked
            # against the corpus, only found quoted inside another source, so
            # `verification_status_line` must not count it as traceable.
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
                # A6: 文號軸 stopped, not deleted. This corpus carries ZERO
                # rows keyed by 文號 today (`statute_id LIKE '%字第%'` = 0), so
                # "not found" here is a fact about THIS corpus's coverage, not
                # evidence the 函釋/文號 is fabricated — a real, uncollected
                # source (「入出國及移民法」-shaped) deserves an honest "not
                # checked" label, not "查無此法源". 位階誤植 is computed in the
                # OTHER branch below, once an article-keyed slice IS found —
                # unaffected by this branch.
                results.append(VerificationResult(
                    citation, exists=False, content_match=True, in_force=False,
                    verbatim_source=None, flagged=False, unverified=True,
                    reason=f"{citation.raw} 此文號未收錄於本系統資料庫,不代表該函釋不存在或造假",
                ))
                continue
            # Retrieval-first is NOT relaxed — exists stays False and the claim
            # stays flagged. But the two failures mean very different things to
            # a reader, so say which one it is instead of always claiming the
            # source does not exist.
            results.append(VerificationResult(
                citation, exists=False, content_match=False, in_force=False,
                verbatim_source=None, flagged=True,
                reason=_missing_reason(citation, corpus_conn),
            ))
            continue

        in_force_slices = [s for s in slices if _in_force(s, as_of_date)]
        in_force = bool(in_force_slices)
        source = in_force_slices[0] if in_force else max(slices, key=lambda s: s.effective_from)

        # A5: an EXPLICIT back-reference ("本法/同法…") is confident about
        # WHICH law it means, so its surrounding claim is checked like a
        # directly-named citation. A BARE, unnamed continuation ("雇主依第三
        # 十二條第一項…") only inherited a statute_id from proximity, with no
        # linguistic signal it belongs there — its surrounding sentence is
        # the OTHER article's text (see the module-level Citation.inferred_id
        # note), so content stays unchecked, and unverified=True says so
        # honestly rather than silently certifying it.
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

        # A3/A4: paragraph/item existence. Only for a citation NAMED at this
        # position — an inherited statute_id (bare OR explicit alike) may
        # belong to a PARENT law whose 第N項/第N款 numbering THIS article's
        # own content cannot speak to (違反社會秩序維護法案件處理辦法§3's own
        # 「本法第八條第二項」 names itself under naive inheritance, not its
        # enabling law 社會秩序維護法 — this axis stands down for ANY
        # `inferred_id` citation rather than risk that class of false
        # positive; see RESULTS.md for the measured count this excludes).
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
