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
    nothing overlaps or the judgments table is empty."""
    if not retrieved:
        return []
    wanted = {(s.statute_id, s.article_no) for s in retrieved}
    # `focus` = the articles the ANSWER relies on: a judgment should accompany
    # the law being cited, not every article in the window (a stray 民法§144
    # once surfaced a 本票 case under a noise question). Falls back to the full
    # window when the answer cites nothing verifiable.
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

    # A judgment is the SAME KIND of case as an article it shares when its 案由
    # names that article's dispute (§179 under 「返還不當得利」, not under
    # 「給付修繕費」). Among equal overlap, those go first; they also keep their
    # seats against the sums-first sort below (judgment_qa, RESULTS §11).
    from legal_agent.retrieval.families import case_type_family, statute_family

    for meta in by_jid.values():
        kind = case_type_family(meta["case_type"])
        meta["same_kind"] = kind is not None and any(
            statute_family(ref) == kind for ref in meta["matched"])

    items = sorted(by_jid.items(), key=lambda kv: kv[0], reverse=True)   # newer jid first
    items.sort(key=lambda kv: (len(kv[1]["matched"]), kv[1]["same_kind"]),
               reverse=True)                                            # overlap, then kind

    # 主文 and the header are parsed only for the few judgments actually shown —
    # verbatim slices, no LLM; an unreadable one simply yields nothing.
    from legal_agent.data.judgment_text import awards as _awards
    from legal_agent.data.judgment_text import citation as _citation

    # The reader asks 「我能拿回多少」, so within each kind, judgments stating a sum
    # go first. Parse a few more candidates than are shown; the stable sort keeps
    # overlap order inside each group.
    widened = [
        (jid, meta, _awards(meta.get("full_text")), _citation(meta.get("full_text")))
        for jid, meta in items[: limit * 3]
    ]
    widened.sort(key=lambda row: (not row[1]["same_kind"], not row[2]))
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

    The sums-first sort would otherwise hide every dismissal (原告之訴駁回 has
    no award), implying nobody lost under these articles. The seat is not
    classified as a loss: the obvious win/loss ruler measures ~12% false
    positives. LAST rather than first, because `judgment_relevance` grades the
    first judgment shown. With no sum-less candidate the ordinary rule fills
    it; never left blank.
    """
    shown = widened[:limit]
    if any(not row[2] for row in shown):
        return shown
    silent = next((row for row in widened[limit:] if not row[2]), None)
    return shown if silent is None else [*shown[:-1], silent]


# A checkable fact about the 主文 (shown verbatim next), not 「敗訴」 — there is
# no graded ruler for that claim.
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
        # The 案號 is what a person can look up; the jid is only a fallback for
        # headerless texts (調解筆錄, 宣示判決筆錄).
        label = r.cite or r.jid
        lines.append(f"・{label}({title})— {money}同引 {'、'.join(r.matched)}")
        if not r.awards and r.main_text:
            # Rejoin wrapped lines (whitespace only); never truncate — an
            # elided 主文 is no longer verbatim.
            verbatim = "".join(part.strip() for part in r.main_text.splitlines())
            lines.append(f"  {NO_AWARD_NOTE}{verbatim}")
    return "\n".join(lines)
