"""Related-judgment lookup — reference material BESIDE a statute answer.

Judgments are REFERENCE tier (spec §1.2): never retrieval candidates, never
citable law. This module therefore does NOT retrieve judgments by query text.
It JOINs the judgments' extracted 引用法條 (cited_articles) against the
statutes the pipeline ALREADY retrieved — a judgment can only surface because
the law surfaced first. Deterministic: no LLM, no embeddings, and the rendered
block is generated code-side, so the model can never invent a case number.

Extraction noise in judgment prose (「同法第X條」 anaphora, non-corpus statute
names keeping their particles) self-filters here: the join keys are the
retrieved statutes' exact (statute_id, article_no) pairs, and junk keys like
「同法」 simply never match.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from legal_agent.config import DB_PATH
from legal_agent.data.database import connect
from legal_agent.data.models import Statute

DISCLAIMER = "以下為引用相同法條之裁判(個案見解,非法律明文,僅供參考):"


@dataclass(frozen=True)
class JudgmentRef:
    jid: str
    court: str | None
    case_type: str | None                 # 案由
    matched: tuple[str, ...]              # 「民法第184條」-style refs shared with the answer
    awards: tuple[int, ...] = ()          # amounts the 主文 orders paid (verbatim-derived)
    cite: str | None = None               # 「法院＋裁判種類 案號」, verbatim from the header
    main_text: str | None = None          # the 主文 verbatim; carried only when awards is ()


def related_judgments(
    retrieved: list[Statute],
    conn: sqlite3.Connection | None = None,
    limit: int = 3,
    focus: set[tuple[str, str]] | None = None,
) -> list[JudgmentRef]:
    """Judgments whose extracted citations overlap the retrieved statutes,
    ranked by overlap count, then by jid (its 5th segment is the 裁判日期, so
    a descending jid within the same court sorts newer first). Returns [] when
    nothing overlaps or the judgments table is empty — the pipeline degrades
    to exactly its old behaviour."""
    if not retrieved:
        return []
    wanted = {(s.statute_id, s.article_no) for s in retrieved}
    # `focus` = the articles the ANSWER actually relies on. Joining on the whole
    # retrieved window surfaced a 本票 case under a noise question, because 民法
    # §144 (時效) happened to sit in the window and one judgment cited it. A
    # reference judgment should accompany the law being cited, not everything the
    # retriever considered. Falls back to the full window when the answer cites
    # nothing verifiable, so the layer never goes silent by accident.
    if focus:
        narrowed = wanted & set(focus)
        if narrowed:
            wanted = narrowed
    sids = sorted({sid for sid, _ano in wanted})

    own = connect(DB_PATH) if conn is None else None
    active = conn if own is None else own
    try:
        rows = active.execute(
            "SELECT j.jid, j.court, j.case_type, "
            "json_extract(c.value, '$.statute_id'), "
            "json_extract(c.value, '$.article_no'), j.full_text "
            "FROM judgments j, json_each(j.cited_articles) c "
            f"WHERE json_extract(c.value, '$.statute_id') IN ({','.join('?' * len(sids))})",
            sids,
        ).fetchall()
    except sqlite3.OperationalError:      # judgments table absent (old DB)
        return []
    finally:
        if own is not None:
            own.close()

    by_jid: dict[str, dict] = {}
    for jid, court, case_type, sid, ano, full_text in rows:
        if (sid, ano) not in wanted:
            continue
        entry = by_jid.setdefault(
            jid,
            {"court": court, "case_type": case_type, "matched": [],
             "full_text": full_text},
        )
        ref = f"{sid}{ano}"
        if ref not in entry["matched"]:
            entry["matched"].append(ref)

    items = sorted(by_jid.items(), key=lambda kv: kv[0], reverse=True)   # newer jid first
    items.sort(key=lambda kv: len(kv[1]["matched"]), reverse=True)       # overlap wins

    # 主文 and the header are parsed only for the few judgments actually shown —
    # verbatim slices, no LLM; an unreadable one simply yields nothing.
    from legal_agent.data.judgment_text import awards as _awards
    from legal_agent.data.judgment_text import citation as _citation

    # The reader's question is 「我能拿回多少」, so a judgment that states a sum goes
    # first. Measured on the 婚攝 session: of the three shown, the only one carrying
    # 判賠 260,000 元 was listed third, under two with no figure at all. Parsing is
    # widened to a few more candidates than are shown — still verbatim slices of the
    # 主文, still no LLM — and the sort is stable, so overlap ordering survives
    # inside each group.
    widened = [
        (jid, meta, _awards(meta.get("full_text")), _citation(meta.get("full_text")))
        for jid, meta in items[: limit * 3]
    ]
    widened.sort(key=lambda row: not row[2])
    shown = _reserve_a_seat_without_a_sum(widened, limit)

    from legal_agent.data.judgment_text import main_text as _main_text

    return [
        JudgmentRef(
            jid=jid,
            court=meta["court"],
            case_type=meta["case_type"],
            matched=tuple(meta["matched"]),
            awards=award,
            cite=cite,
            # Only where there is no sum to show. That is the seat whose label
            # has to be justified, and the 主文 verbatim is the justification.
            main_text=None if award else _main_text(meta.get("full_text")),
        )
        for jid, meta, award, cite in shown
    ]


def _reserve_a_seat_without_a_sum(widened: list, limit: int) -> list:
    """Give the LAST seat to a judgment whose 主文 states no sum, if the run
    would otherwise show none.

    `widened.sort(key=lambda row: not row[2])` floats every judgment carrying a
    figure above every judgment carrying none — `not ()` is True, `not (260000,)`
    is False, and False sorts first. Candidates are widened only to `limit * 3`,
    so as soon as three of those nine parse a sum, all three seats a reader sees
    carry one. Meanwhile `judgment_text.award_amounts` returns an empty list for
    a 主文 that reads 原告之訴駁回. Multiply the two and the code was actively
    sorting the losses out of sight.

    Cheap on purpose: the reserved seat is not classified as a loss, and no
    dismissal marker is computed. A win/loss classifier needs a ruler that has
    itself been graded, and the obvious substring ruler already measures about
    12% false positives — all of them labelling wins as losses. The price of
    staying cheap is that this cannot tell the reader 「N people lost under these
    same articles」; it can only stop the block from implying nobody did.

    LAST rather than first, because `judgment_relevance` grades 「the judgment
    the reader would see first」 and `CaseJudgment.shown` is the first
    judgment's 案由. Seat 3 leaves both published figures untouched; seat 1
    would break 「first judgment states a sum」 by definition.

    When no candidate lacks a sum, the seat is filled by the ordinary rule.
    Never left blank — a missing row says nothing a reader can check.
    """
    shown = widened[:limit]
    if any(not row[2] for row in shown):
        return shown
    silent = next((row for row in widened[limit:] if not row[2]), None)
    return shown if silent is None else [*shown[:-1], silent]


# What a no-sum judgment is allowed to say. 「未載明給付金額」 is a fact about the
# 主文 that the next line lets the reader check for themselves. 「敗訴」 would be
# a claim about the case, and this module has no graded ruler for that — see
# `_reserve_a_seat_without_a_sum`.
NO_AWARD_NOTE = "此判決主文未載明給付金額,主文逐字:"


def render_block(refs: list[JudgmentRef]) -> str:
    """Terminal/text block for the reference judgments; '' when none."""
    if not refs:
        return ""
    from legal_agent.data.judgment_text import format_awards

    lines = [DISCLAIMER]
    for r in refs:
        title = r.case_type or "(案由不明)"
        money = format_awards(r.awards)
        money = f"{money}｜" if money else ""
        # The 案號 is what a person can look up on 司法院裁判書系統; the jid is a
        # database key. Fall back to it only when the header is unparseable
        # (調解筆錄 and 宣示判決筆錄 do not carry one).
        label = r.cite or r.jid
        lines.append(f"・{label}({title})— {money}同引 {'、'.join(r.matched)}")
        if not r.awards and r.main_text:
            # Wrapped continuation lines are rejoined, which is whitespace only
            # — the same treatment `judgment_text._sentences` applies. Not
            # truncated: an elided 主文 is no longer verbatim.
            verbatim = "".join(part.strip() for part in r.main_text.splitlines())
            lines.append(f"  {NO_AWARD_NOTE}{verbatim}")
    return "\n".join(lines)
