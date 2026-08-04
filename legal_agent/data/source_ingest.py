"""Layer-2 法源 ingest — persist a HUMAN-VERIFIED proposal file into the corpus.

`load_proposals(path, conn)` reads a JSON list of verified 法源 proposals and
persists each into the `statutes` table (which is now the general 法源 table,
distinguished by hierarchy_level) via the existing cli.insert_statute path.

It ONLY persists a verified file: NO fetching, NO generating, NO tiering
decisions. Idempotent — a duplicate (statute_id, article_no, effective_from) is
skipped (IntegrityError). Every hierarchy_level is validated against
source_hierarchy UP FRONT; an unknown level REJECTS the whole file (ValueError,
not a silent skip). Missing required fields or malformed dates also reject.

Proposal JSON = a list of:
    {
      "statute_id": "社會秩序維護法案件處理辦法" | "司法院(81)廳刑一字第329號" | ...,
      "article_no": "第11條" | "",     # 函釋/實務見解 用文號當 id 時可留空 ""
      "content": "<verbatim>",
      "effective_from": "YYYY-MM-DD",
      "effective_to": null,             # or "YYYY-MM-DD"
      "hierarchy_level": "命令" | "函釋" | "行政實務見解" | ...,   # FK-checked
      "source_url": "..."               # optional
    }
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from legal_agent.cli import insert_statute
from legal_agent.data.models import Statute


def _check_iso(value, label: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 需為 ISO 'YYYY-MM-DD',得到 {value!r}") from exc


def _to_statute(proposal: dict, index: int, valid_levels: set[str]) -> Statute:
    def required(key: str) -> str:
        val = proposal.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ValueError(f"proposal[{index}] 缺少必要欄位 '{key}'")
        return val

    statute_id = required("statute_id")
    content = required("content")
    effective_from = required("effective_from")
    hierarchy_level = required("hierarchy_level")
    article_no = proposal.get("article_no") or ""    # may be empty (文號當 id 時)
    effective_to = proposal.get("effective_to")      # JSON null -> None
    source_url = proposal.get("source_url")

    if hierarchy_level not in valid_levels:
        raise ValueError(
            f"proposal[{index}] 未知的 hierarchy_level '{hierarchy_level}';"
            f"必須是 source_hierarchy 已 seed 的位階之一:{sorted(valid_levels)}"
        )
    _check_iso(effective_from, f"proposal[{index}].effective_from")
    if effective_to is not None:
        _check_iso(effective_to, f"proposal[{index}].effective_to")

    return Statute(
        statute_id=statute_id,
        article_no=article_no,
        content=content,
        effective_from=effective_from,
        effective_to=effective_to,
        hierarchy_level=hierarchy_level,
        source_url=source_url,
    )


def _check_single_open_slice(statutes: list[Statute], conn: sqlite3.Connection) -> None:
    """Time-slice invariant: one article may carry at most ONE open slice
    (effective_to IS NULL). Two open slices make BOTH versions "currently in
    force", so a point-in-time lookup between their effective_from dates hits
    the older one and out-of-force checks silently pass. The importer refuses
    instead of guessing a close date — the reviewer must cap the older slice
    with an explicit effective_to (found live 2026-07-21: a hand-era proposal
    and the official-XML import both shipped the same article open).
    """
    open_in_file: dict[tuple[str, str], str] = {}
    for s in statutes:
        if s.effective_to is not None or not s.article_no:
            continue
        key = (s.statute_id, s.article_no)
        if key in open_in_file and open_in_file[key] != s.effective_from:
            raise ValueError(
                f"{s.statute_id}{s.article_no} 在同一檔內有兩個未封頂版本"
                f"(effective_from {open_in_file[key]} 與 {s.effective_from})——"
                "請為較舊的版本補上 effective_to"
            )
        open_in_file[key] = s.effective_from
        existing = conn.execute(
            "SELECT effective_from FROM statutes WHERE statute_id = ? "
            "AND article_no = ? AND effective_to IS NULL AND effective_from != ?",
            (s.statute_id, s.article_no, s.effective_from),
        ).fetchone()
        if existing:
            raise ValueError(
                f"{s.statute_id}{s.article_no} 已有未封頂版本"
                f"(effective_from {existing[0]}),不得再匯入另一個未封頂版本"
                f"(effective_from {s.effective_from})——"
                "請人工確認何者為現行版,並為較舊的版本補上 effective_to"
            )


def load_proposals(path, conn: sqlite3.Connection) -> tuple[int, int]:
    """Ingest a verified proposal JSON file. Returns (inserted, skipped).

    Validates ALL rows first (fail-fast: an unknown level / bad field / a
    duplicate open slice rejects the whole file with a clear ValueError,
    before any insert), then inserts each via insert_statute, skipping
    duplicates (IntegrityError).
    """
    proposals = json.loads(Path(path).read_text(encoding="utf-8"))
    valid_levels = {row[0] for row in conn.execute("SELECT level FROM source_hierarchy")}

    statutes = [_to_statute(p, i, valid_levels) for i, p in enumerate(proposals)]
    _check_single_open_slice(statutes, conn)

    inserted = skipped = 0
    for statute in statutes:
        try:
            insert_statute(conn, statute)
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1
    return inserted, skipped


def main(argv=None) -> int:
    """Clean loader entry: init_db + seed_source_hierarchy + load_proposals + print.
        python -m legal_agent.data.source_ingest <proposal.json>
    """
    import sys as _sys

    from legal_agent import config
    from legal_agent.data.database import connect, init_db
    from legal_agent.data.seed import seed_source_hierarchy

    argv = _sys.argv[1:] if argv is None else argv
    if not argv:
        print("用法:python -m legal_agent.data.source_ingest <proposal.json>")
        return 2

    db_path = config.DB_PATH
    init_db(db_path)
    conn = connect(db_path)
    try:
        seed_source_hierarchy(conn)
        inserted, skipped = load_proposals(argv[0], conn)
    finally:
        conn.close()
    print(f"inserted {inserted} / skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
