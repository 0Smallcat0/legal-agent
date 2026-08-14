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
from dataclasses import dataclass

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

# Every harvested judgment opens the same way, and both lines are verbatim:
#   line 1  臺灣宜蘭地方法院民事簡易判決      <- court + what kind of ruling it is
#   line 2  114年度宜簡字第406號              <- the 案號 a person can actually look up
# The API's jid (「LTEV,114,羅簡,192,20260630,2」) is a database key; showing it
# to a user beside an answer told them nothing and hid the 判決/裁定 distinction.
_COURT_LINE_RE = re.compile(r"^\s*(\S*法院\S*)\s*$", re.MULTILINE)
_CASE_NO_RE = re.compile(r"^\s*(\S*年度\S*第\s*\d+\s*號)\s*$", re.MULTILINE)


def citation(full_text: str | None) -> str | None:
    """The judgment's own header — 「法院＋裁判種類 案號」 — read verbatim from its
    first lines, or None when the text does not carry them."""
    if not full_text:
        return None
    head = full_text[:400]
    court = _COURT_LINE_RE.search(head)
    case_no = _CASE_NO_RE.search(head)
    if not court and not case_no:
        return None
    parts = [m.group(1).strip() for m in (court, case_no) if m]
    return " ".join(parts)


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


# ── who got what: the 主文 read one SENTENCE at a time ───────────────────────
# The obvious ruler — test the whole 主文 block for 「之訴駁回」 — measures about
# 12% false positives on the shipped 386, and every one of them labels a WIN as
# a loss. That is the worst direction of error for a block whose purpose is to
# tell a reader that someone lost. The known shapes it gets wrong, all pinned as
# regression cases in tests/test_judgment_outcome.py:
#
#   「原告先位之訴駁回」 followed by 確認…特留分存在 and 命被告塗銷 — the primary
#      claim failed and the alternative one succeeded;
#   「原判決廢棄。被上訴人在第一審之訴駁回」 — the APPELLANT won outright, and the
#      dismissal falls on the other side;
#   「緊急處置之聲請駁回」 beside two granted injunctions — one sub-application
#      refused, the main relief given;
#   「其餘上訴駁回」 after a 廢棄 — the appellate wording for a partial loss, which
#      a 「其餘之訴駁回」 test never sees;
#   「再審之訴駁回」 — procedural, and says nothing about the underlying case.
#
# The cause is a LEVEL error, not a shortage of markers: `award_amounts` above
# already decides sentence by sentence, and the outcome has to keep the same
# discipline. A 主文 is a list of operative orders; the case-level result is a
# function of that list, never a substring test on the block.
#
# And an appellate 主文 is relative to the parties' POSITIONS: one sentence is a
# win for the appellant and a loss for the respondent. An outcome that does not
# name WHO is misleading on its own, so `Outcome` carries the role words
# verbatim from the 主文 and refuses to render a verdict without them.

# Role words, most specific first: 再審原告 must be matched before 原告, and the
# mover in an appeal is 上訴人 even though 原告 may also appear in the text.
# Matched on the ROLE WORDS, not on the proceeding noun — a first-instance 主文
# routinely ends 「原告其餘假執行之聲請駁回」, and testing for a bare 「聲請」 read
# that as a petition and named the wrong mover.
_ROLES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("再審原告", "再審被告", "再審之訴"), "再審原告", "再審被告"),
    (("上訴人", "被上訴人"), "上訴人", "被上訴人"),
    (("聲請人", "相對人"), "聲請人", "相對人"),
    (("原告", "被告"), "原告", "被告"),
)
_RESPONDENTS = ("被上訴人", "再審被告", "相對人", "被告")

# Relief that needs no obligor: 確認 is declaratory, 准 allows an application,
# 不得 is a prohibition order (every 保護令 in the corpus is written this way).
# 「不准」 is the opposite and must not be swept up by 「准」.
_RELIEF_RE = re.compile(r"確認|不得|(?<!不)准")
_DISMISS_RE = re.compile(r"駁回")
_VACATE_RE = re.compile(r"廢棄")
# Costs decide nothing on the merits; a clerical correction decides nothing at
# all. Both routinely carry 駁回 or 廢棄 in the same sentence.
_NOT_OPERATIVE = ("訴訟費用", "程序費用", "裁判費", "更正為", "補充為")
# 「原告應於本裁定送達後十日內補正…，逾期未補正，即駁回原告之訴」 is an order to
# cure a defect. Read literally it carries both an 應-order and a 駁回, so it
# was landing in `granted` and in `denied` depending on which clause won — a
# procedural 裁定 scoring as a merits result in BOTH directions. It decides
# nothing: the dismissal is conditional and in the future.
_CONDITIONAL_RE = re.compile(r"逾期.{0,8}(?:即)?駁回|補正")


@dataclass(frozen=True)
class Outcome:
    """What a 主文 ordered, and for WHOM.

    `verdict` is about the MOVER — the party who brought this proceeding
    (原告 / 上訴人 / 聲請人 / 再審原告). Saying it without saying whose it is
    would invert on appeal, where the same sentence is a win for one side and a
    loss for the other.
    """

    verdict: str            # granted | partly | denied | denied_procedurally | unreadable
    mover: str = ""
    respondent: str = ""
    grants: tuple[str, ...] = ()     # sentences read as relief for the mover
    denials: tuple[str, ...] = ()    # sentences read as refusal of the mover

    def describe(self) -> str:
        """A sentence naming who, or 「無法判讀」. Never a bare 勝訴/敗訴."""
        if self.verdict == "unreadable" or not self.mover:
            return "此判決主文無法判讀勝敗"
        return {
            "granted": f"此判決主文的請求由{self.mover}全部獲准",
            "partly": f"此判決主文{self.mover}的請求一部獲准、一部駁回",
            "denied": f"此判決主文駁回{self.mover}的請求",
            "denied_procedurally": f"此判決以程序理由駁回{self.mover},未及於本案勝敗",
        }[self.verdict]


def _is_relief(sentence: str, mover: str, respondent: str) -> bool:
    """Does this sentence give the MOVER something?

    An 「應…」 order is relief only when the party ordered to act is the other
    side. That is not pedantry: on appeal the roles swap, so 「被告應給付原告」
    and 「上訴人應給付被上訴人」 are the same grammar pointing opposite ways, and
    a rule that reads 應 as a win regardless would invert every cross-appeal.
    The obligor is the role word NEAREST to 應 on its left — IPCV's injunctions
    open 「聲請人…為相對人供擔保後，相對人應將…」, where the first role word in the
    sentence is the mover and the obligor is the one after it.
    """
    if _RELIEF_RE.search(sentence):
        return True
    at = sentence.find("應")
    if at < 0:
        return False
    if not mover:
        # 「兩造共有…應合併分割如附圖」 — a partition names no mover at all, and
        # there is no side for the order to point away from.
        return True
    head = sentence[:at]
    # The obligor sits in the clause 應 belongs to, not merely nearest to it:
    # 「被告對於原告所有坐落…之假扣押登記應予塗銷」 has 原告 closer, but only as
    # the owner of the land. Fall back to the first role word when the clause
    # carries none, which is the plain 「被告應給付原告…」 shape.
    clause = head.rsplit("，", 1)[-1]
    for scope in (clause, head):
        found = [(scope.find(role), role) for role in (mover, respondent) if role in scope]
        if found:
            return min(found)[1] != mover
    return True


def _roles(block: str) -> tuple[str, str]:
    """The mover and the respondent, as the 主文 itself names them."""
    for markers, mover, respondent in _ROLES:
        if any(marker in block for marker in markers):
            return mover, respondent
    return "", ""


def outcome(full_text: str | None) -> Outcome:
    """Read the 主文 sentence by sentence and say what the mover got.

    Same slicing and the same `_sentences` as `award_amounts`, deliberately: a
    second, looser reader of the same text is how the two drift apart.
    """
    block = main_text(full_text)
    if not block:
        return Outcome("unreadable")
    mover, respondent = _roles(block)
    grants: list[str] = []
    denials: list[str] = []
    procedural_only = True
    for sentence in _sentences(block):
        if any(marker in sentence for marker in _NOT_OPERATIVE):
            continue
        if _CONDITIONAL_RE.search(sentence):
            continue
        dismissed = bool(_DISMISS_RE.search(sentence))
        if _VACATE_RE.search(sentence) or _is_relief(sentence, mover, respondent):
            # 「原判決…廢棄」 is ground won by whoever appealed; an 應/確認 order is
            # relief. Either way the mover gained something here.
            grants.append(sentence)
            procedural_only = False
            if not dismissed:
                continue
        if not dismissed:
            continue
        # A dismissal aimed at the OTHER side is relief for the mover — this is
        # the shape 「被上訴人在第一審之訴駁回」 takes, and reading it as a loss is
        # how a whole-block test inverts an outright appellate win.
        head = sentence[: sentence.index("駁回")]
        if any(role in head for role in _RESPONDENTS):
            if sentence not in grants:
                grants.append(sentence)
            procedural_only = False
            continue
        denials.append(sentence)
        if "再審之訴" not in head:
            procedural_only = False
    if not grants and not denials:
        return Outcome("unreadable", mover, respondent)
    if denials and procedural_only:
        return Outcome("denied_procedurally", mover, respondent, (), tuple(denials))
    if grants and denials:
        verdict = "partly"
    elif grants:
        verdict = "granted"
    else:
        verdict = "denied"
    return Outcome(verdict, mover, respondent, tuple(grants), tuple(denials))


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
