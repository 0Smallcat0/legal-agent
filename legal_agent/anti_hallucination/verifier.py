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
    # True when the statute name was NOT written at this citation and had to be
    # inherited from the previous named one (「雇主依第三十二條第一項…」 inside a
    # quoted article). Such a reference still gets the exists axis, but not the
    # content axis: its surrounding sentence is the OTHER article's text, so a
    # content comparison would measure the wrong thing.
    inferred_id: bool = False


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
# (1) 統名 + 第X[-Y]條 [之Z] [+ 項/款]. The 之Z suffix is a DISTINCT article
# (民法第800條之1 ≠ 第800條) — it must survive into article_no, never be
# silently dropped, or a ghost 之X citation gets laundered into its real parent.
# The statute name may be closed by a bracket or separated by whitespace before
# 第X條 — 「根據《民法》第440條」 and 「民法 第440條」 are how models actually write.
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

# 實務見解-tier levels (rank >= 4): must NOT be presented as 「法律明文」.
_PRACTICE_TIER_LEVELS = {"函釋", "行政實務見解"}
_LAW_HEADING_RE = re.compile(r"(?<!非)法律明文")   # heading, not the "非法律明文" disclaimer
_HEADINGS_AFTER_LAW = ("實務見解", "分析研判")

# ── monetary amounts (for the conservative content-match pass) ───────────────
_YUAN_RE = re.compile(r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩]+)\s*元")
_CURRENCY_RE = re.compile(r"(?:新臺幣|新台幣|NT\$|NTD|＄|\$)\s*([0-9０-９,，]+)")
# Suffix-form direction word bound to an amount (「六千元以下」). Only the
# suffix form is checked — prefix forms (逾/未滿 X 元) are rarer and riskier
# to attribute, and a conservative pass must never flag a good answer.
_AMOUNT_DIR_RE = re.compile(
    r"([0-9０-９,，零〇一二三四五六七八九十百千萬億兩]+)\s*元(以上|以下|以內|未滿)"
)
_DOWNWARD = {"以下", "以內", "未滿"}
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


# ── time periods (for the period-swap content pass) ──────────────────────────
# A numeral bound to a period unit: 「七日內」「二年以下有期徒刑」「六個月」.
# 日/天 and 週/星期 normalize to one unit. Bare 「月」 is deliberately NOT a
# unit — 「三月」 is a date (March); only the 「X個月」 form counts. 「半年」
# (no numeral) is skipped — conservative pass, misses documented in RESULTS.
_PERIOD_RE = re.compile(
    r"([0-9０-９零〇一二三四五六七八九十百千兩]+)\s*(個月|小時|星期|週|日|天|年)"
)
_PERIOD_UNIT_NORM = {"天": "日", "星期": "週", "個月": "月"}


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


def _sentence_around(text: str, start: int, end: int,
                     floor: int | None = None, ceiling: int | None = None) -> str:
    """The sentence containing [start, end), clipped to (floor, ceiling).

    The clip is what keeps citations from being graded on each other's words.
    「依社維法第72條處一萬元以下罰鍰,依民法第195條得請求非財產上之損害賠償」 is ONE
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
    claimed = _amounts(claim_scope)
    supported = _amounts(verbatim)
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
        unsupported = claim_values - source_values
        if unsupported:
            label = _period_label(unit)
            return False, (
                f"主張期間 {sorted(unsupported)[0]}{label} 未見於條文"
                f"(條文期間 {sorted(source_values)}{label})"
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
# Sentence particles that glue onto a statute name in prose.
_LEADING_PARTICLES = ("依據", "根據", "依照", "按照", "參照", "違反",
                      "依", "按", "及", "與", "和", "另", "並", "或", "暨")


def _strip_particle(name_run: str) -> str:
    """The name without the prose particle glued to its front (依/按/及…)."""
    for particle in _LEADING_PARTICLES:
        if name_run.startswith(particle) and len(name_run) > len(particle):
            return name_run[len(particle):]
    return name_run


def _resolve_id(name_run: str, known_ids: set[str]) -> str:
    # A full corpus id may still be matched as a suffix: to end with the whole
    # canonical name, the run has to spell every character of it correctly, so a
    # typo inside the name cannot survive this test.
    matches = [kid for kid in known_ids if name_run.endswith(kid)]
    if matches:
        return max(matches, key=len)
    # An alias is shorter than what it stands for, so the same test would accept
    # anything ending in it — including a misspelling of the part it omits. It
    # must therefore match the whole name. See the note above _ALIASES.
    stripped = _strip_particle(name_run)
    canonical = _ALIASES.get(stripped)
    if canonical is not None and canonical in known_ids:
        return canonical
    # Unresolved: return the particle-stripped name so the warning reads
    # 「corpus 查無此法源:台灣安寧保障法第3條」 rather than 「…:依台灣安寧保障法第3條」.
    return stripped


def _is_anaphoric(name_run: str, resolved: str, known_ids: set[str]) -> bool:
    """True when this citation names no statute of its own: either an explicit
    back-reference (同法/本法) or a run of ordinary prose (「雇主依」)."""
    if resolved in known_ids:
        return False
    if name_run.endswith(_ANAPHORA_NAMES):
        return True
    return not _STATUTE_SHAPE_RE.search(name_run)


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
        inferred = False
        if _is_anaphoric(name_run, statute_id, known_ids) and last_named is not None:
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
        slices = _slices(citation.statute_id, citation.article_no, retrieved_context, conn)
        if not slices and _quoted_in_retrieved(citation, retrieved_context):
            # The reference appears VERBATIM inside a retrieved source's own text
            # (the 警察分工原則 names 噪音管制法第8條/第9條 in its body). The model
            # copied it from material it was given, so 「模型可能憑記憶補充」 is
            # false — but the referenced article itself was not retrieved, so its
            # content stays unchecked and unrelied-upon. Say exactly that.
            results.append(VerificationResult(
                citation, exists=False, content_match=False, in_force=False,
                verbatim_source=None, flagged=False,
                reason=(f"{citation.statute_id}{citation.article_no} "
                        "係檢索到的法源內文中的交叉引用(逐字出現於檢索結果),"
                        "本次未另行檢索該條,故未核對其內容"),
            ))
            continue
        if not slices:
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

        if citation.inferred_id:
            # Unnamed back-reference: the sentence around it belongs to the
            # article being QUOTED, not to this one. Existence and in-force
            # still apply; comparing content would grade the wrong text.
            claim_scope = ""
            content_match, cm_reason = True, ""
        else:
            claim_scope = _sentence_around(
                answer_text, pos, pos + len(citation.raw),
                floor=prev_end, ceiling=next_start,
            )
            content_match, cm_reason = _content_consistent(claim_scope, source.content)

        # 位階誤植: 實務見解-tier source presented inside the 「法律明文」 section.
        misplaced = (
            law_span is not None
            and law_span[0] <= pos < law_span[1]
            and source.hierarchy_level in _PRACTICE_TIER_LEVELS
        )

        # Optional 4th axis — only spend the model on structurally clean citations.
        semantic_ok, sem_reason = True, ""
        if semantic_llm is not None and content_match and in_force and not citation.inferred_id:
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
        flagged = (not (content_match and in_force and semantic_ok)) or misplaced
        results.append(VerificationResult(
            citation, exists=True, content_match=content_match, in_force=in_force,
            verbatim_source=source.content, flagged=flagged, reason="；".join(reasons),
            semantic_ok=semantic_ok,
        ))

    return results
