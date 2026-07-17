"""司法院裁判書 importer (spec §1.2) — open-data JSON → `judgments` rows.

Source: the 裁判書開放API (opendata.judicial.gov.tw) — `JList` gives the 7-day
JID change list, `JDoc/{jid}` a single judgment. This module fetches NOTHING:
the owner downloads the JSON (one object or a list) and points the CLI at it.

Field mapping (官方規格): JID → jid (PRIMARY KEY; court = first comma-segment
of the JID), JYEAR → year (ROC year, integer), JTITLE → case_type (案由),
JFULL → full_text. JDATE (西元 YYYYMMDD) is inside the JID/full text and the
schema carries no date column — not stored.

Honesty split (spec §1.3 trap 2 — judgment text is semi-structured):
  * `issues` / `holding` stay NULL. Parsing 爭點/要旨 out of free text is its
    own NLP task; pretending a regex did it would poison later consumers.
  * `cited_articles` IS extracted — citation grammar is the one thing this
    project genuinely owns. It reuses the verifier's extractor (single source
    of truth, incl. 之X → 「第X-Y條」 normalization), emitting the schema's
    documented JSON shape: [{"statute_id", "article_no"}, ...].

Unlike statutes (moj_xml → human-reviewed proposal → validated ingest),
judgments load directly: they are REFERENCE material — never retrieval
candidates, never citable law — so the human-verification gate that protects
the statutes corpus does not apply. Idempotent: duplicate jid is skipped.

Run:  python -m legal_agent.data.judicial_json FILE.json [FILE2.json ...]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

# Deliberate reuse of the verifier's private extractor: 條號 parsing (incl. the
# ghost-suffix normalization) must have exactly one implementation.
from legal_agent.anti_hallucination.verifier import _iter_citations


def _cited_articles_json(full_text: str, known_ids: set[str]) -> str:
    """Extract citations from 判決全文 into the schema's JSON-array shape."""
    seen: list[tuple[str, str]] = []
    for citation, _pos in _iter_citations(full_text or "", known_ids):
        key = (citation.statute_id, citation.article_no)
        if citation.article_no and key not in seen:
            seen.append(key)
    return json.dumps(
        [{"statute_id": s, "article_no": a} for s, a in seen], ensure_ascii=False
    )


def parse_judgment(
    record: dict, known_ids: set[str]
) -> tuple[dict | None, list[str]]:
    """One API record → a judgments row dict, or (None, warnings) if unusable."""
    jid = str(record.get("JID") or "").strip()
    if not jid:
        return None, ["有一筆判決缺 JID — 已略過"]

    warnings: list[str] = []
    court = jid.split(",")[0] if "," in jid else ""
    if not court:
        warnings.append(f"「{jid}」JID 非逗號分段格式 — court 留空")

    year: int | None = None
    raw_year = str(record.get("JYEAR") or "").strip()
    if raw_year.isdigit():
        year = int(raw_year)
    elif raw_year:
        warnings.append(f"「{jid}」JYEAR 非數字: {raw_year!r} — year 留空")

    full_text = str(record.get("JFULL") or "")
    return {
        "jid": jid,
        "court": court or None,
        "year": year,
        "case_type": (str(record.get("JTITLE") or "").strip() or None),
        "issues": None,                       # NLP task — never faked (§1.3)
        "cited_articles": _cited_articles_json(full_text, known_ids),
        "holding": None,                      # ditto
        "full_text": full_text or None,
    }, warnings


def parse_file(path: str | Path, known_ids: set[str]) -> tuple[list[dict], list[str]]:
    """A downloaded JSON file (single object or list) → (rows, warnings)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    records = data if isinstance(data, list) else [data]
    rows: list[dict] = []
    warnings: list[str] = []
    for record in records:
        row, row_warnings = parse_judgment(record, known_ids)
        warnings.extend(row_warnings)
        if row is not None:
            rows.append(row)
    return rows, warnings


def load_judgments(rows: list[dict], conn: sqlite3.Connection) -> tuple[int, int]:
    """Insert rows; duplicate jid (PK) is skipped. Returns (inserted, skipped)."""
    inserted = skipped = 0
    for row in rows:
        try:
            conn.execute(
                "INSERT INTO judgments (jid, court, year, case_type, issues, "
                "cited_articles, holding, full_text) VALUES "
                "(:jid, :court, :year, :case_type, :issues, :cited_articles, "
                ":holding, :full_text)",
                row,
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1
    conn.commit()
    return inserted, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m legal_agent.data.judicial_json",
        description="司法院裁判書開放API JSON → judgments 表(參考層,直接入庫,冪等)",
    )
    parser.add_argument("json_paths", nargs="+", help="下載好的裁判書 JSON 檔")
    args = parser.parse_args(argv)

    from legal_agent import config
    from legal_agent.data.database import connect, init_db

    init_db(config.DB_PATH)
    conn = connect(config.DB_PATH)
    try:
        known_ids = {r[0] for r in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
        total_inserted = total_skipped = 0
        for path in args.json_paths:
            rows, warnings = parse_file(path, known_ids)
            inserted, skipped = load_judgments(rows, conn)
            total_inserted += inserted
            total_skipped += skipped
            for w in warnings:
                print(f"警告:{w}")
        print(f"inserted {total_inserted} / skipped {total_skipped}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
