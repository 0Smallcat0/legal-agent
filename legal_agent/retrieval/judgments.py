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
    return [
        JudgmentRef(
            jid=jid,
            court=meta["court"],
            case_type=meta["case_type"],
            matched=tuple(meta["matched"]),
            awards=_awards(meta.get("full_text")),
            cite=_citation(meta.get("full_text")),
        )
        for jid, meta in items[:limit]
    ]


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
    return "\n".join(lines)
