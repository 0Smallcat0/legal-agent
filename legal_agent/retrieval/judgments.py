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


def related_judgments(
    retrieved: list[Statute],
    conn: sqlite3.Connection | None = None,
    limit: int = 3,
) -> list[JudgmentRef]:
    """Judgments whose extracted citations overlap the retrieved statutes,
    ranked by overlap count, then by jid (its 5th segment is the 裁判日期, so
    a descending jid within the same court sorts newer first). Returns [] when
    nothing overlaps or the judgments table is empty — the pipeline degrades
    to exactly its old behaviour."""
    if not retrieved:
        return []
    wanted = {(s.statute_id, s.article_no) for s in retrieved}
    sids = sorted({sid for sid, _ano in wanted})

    own = connect(DB_PATH) if conn is None else None
    active = conn if own is None else own
    try:
        rows = active.execute(
            "SELECT j.jid, j.court, j.case_type, "
            "json_extract(c.value, '$.statute_id'), "
            "json_extract(c.value, '$.article_no') "
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
    for jid, court, case_type, sid, ano in rows:
        if (sid, ano) not in wanted:
            continue
        entry = by_jid.setdefault(
            jid, {"court": court, "case_type": case_type, "matched": []}
        )
        ref = f"{sid}{ano}"
        if ref not in entry["matched"]:
            entry["matched"].append(ref)

    items = sorted(by_jid.items(), key=lambda kv: kv[0], reverse=True)   # newer jid first
    items.sort(key=lambda kv: len(kv[1]["matched"]), reverse=True)       # overlap wins
    return [
        JudgmentRef(
            jid=jid,
            court=meta["court"],
            case_type=meta["case_type"],
            matched=tuple(meta["matched"]),
        )
        for jid, meta in items[:limit]
    ]


def render_block(refs: list[JudgmentRef]) -> str:
    """Terminal/text block for the reference judgments; '' when none."""
    if not refs:
        return ""
    lines = [DISCLAIMER]
    for r in refs:
        title = r.case_type or "(案由不明)"
        lines.append(f"・{r.jid}({title})— 同引 {'、'.join(r.matched)}")
    return "\n".join(lines)
