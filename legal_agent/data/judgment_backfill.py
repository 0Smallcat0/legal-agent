"""Fill the dispute families that have fewer than three same-kind judgments.

`evaluation/judgment_coverage.py` measures the gap; this fills it, from the
court's own text only. Nothing here writes a judgment: every row comes from an
official record (a 司法院 bulk JSON file on disk, or the 裁判書開放API) and goes
through the same importer as everything else (`judicial_json.parse_judgment`
-> `load_judgments`), so 案號, 案由 and 主文 are whatever the court published.

Which families, and how many: those `evals/real_sessions.json` asks about whose
stock is below `judgment_coverage.TARGET`, short by exactly the shortfall. A
record is taken only when `judgment_coverage.serves_family` says it serves one
of them — its 案由 names the family and it cites an article of it — so a
backfilled judgment is by construction one the page can reach. Newest first
(the 5th JID segment is the 裁判日期); a jid already in the table is skipped.

Two sources, one selection:

  python -m legal_agent.data.judgment_backfill DIR_OR_FILE [...]
      Local JSON — the open-data bulk files (one judgment per file, or a list),
      or saved JDoc responses. Directories are walked recursively. Offline.

  python -m legal_agent.data.judgment_backfill --api [--limit 3000]
      The nightly API (00:00-06:00 Asia/Taipei, credentials as for
      judicial_api). The change list is one day, seven days ago, and carries
      no 案由, so each candidate must be fetched to be judged; one night fills
      what that day happened to contain. Re-run nightly until --dry-run
      reports nothing missing.

Afterwards the shipped file is re-exported (redaction included) with
`python -m legal_agent.data.judgment_ingest`, and the gap re-measured with
`python -m legal_agent.evaluation.judgment_coverage`.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from legal_agent.data.judicial_api import jdoc_to_record
from legal_agent.data.judicial_json import load_judgments, parse_judgment
from legal_agent.evaluation.judgment_coverage import (
    TARGET,
    nameable,
    serves_family,
    session_families,
    stock_by_family,
)


def deficits(conn: sqlite3.Connection, sessions_path: str | Path,
             target: int = TARGET) -> dict[str, int]:
    """family -> how many judgments it is short, for families sessions ask about."""
    asked: set[str] = set()
    for case in json.loads(Path(sessions_path).read_text(encoding="utf-8")):
        asked.update(session_families(case.get("expected_statutes", [])))
    stock = stock_by_family(conn)
    return {f: target - len(stock.get(f, [])) for f in sorted(asked)
            if len(stock.get(f, [])) < target}


def _as_record(obj: dict) -> dict:
    """Flat bulk record (JFULL) as is; a JDoc response (JFULLX) adapted."""
    return jdoc_to_record(obj) if "JFULLX" in obj else obj


def records_from_paths(paths: Iterable[str | Path]) -> Iterator[dict]:
    """Every judgment record in the given files / directory trees.
    An unreadable file is skipped, not fatal — bulk archives contain a few."""
    for raw in paths:
        p = Path(raw)
        files = sorted(p.rglob("*.json")) if p.is_dir() else [p]
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            for obj in data if isinstance(data, list) else [data]:
                if isinstance(obj, dict):
                    yield _as_record(obj)


def _date_key(jid: str) -> str:
    parts = jid.split(",")
    return parts[4] if len(parts) > 4 else ""


@dataclass
class BackfillResult:
    wanted: dict[str, int]
    chosen: dict[str, list[dict]] = field(default_factory=dict)
    scanned: int = 0
    inserted: int = 0

    def still_missing(self) -> dict[str, int]:
        return {f: n - len(self.chosen.get(f, [])) for f, n in self.wanted.items()
                if n > len(self.chosen.get(f, []))}

    def render(self) -> str:
        lines = [f"掃描 {self.scanned} 筆;寫入 {self.inserted} 筆", "家族      缺  補到  仍缺"]
        missing = self.still_missing()
        for fam, n in self.wanted.items():
            got = self.chosen.get(fam, [])
            lines.append(f"{fam:8s} {n:3d} {len(got):5d} {missing.get(fam, 0):5d}")
            for row in got:
                lines.append(f"    {row['jid']}  {row['case_type']}")
        if not self.wanted:
            lines.append("(每個家族都已達標)")
        return "\n".join(lines)


def select(records: Iterable[dict], wanted: dict[str, int], known_ids: set[str],
           have: set[str]) -> tuple[dict[str, list[dict]], int]:
    """Rows serving a short family, newest first, at most the shortfall each.
    Returns (family -> rows, records scanned)."""
    pool: dict[str, list[dict]] = {}
    scanned = 0
    for record in records:
        scanned += 1
        row, _warnings = parse_judgment(record, known_ids)
        if row is None or row["jid"] in have or not row["full_text"]:
            continue
        family = serves_family(row["case_type"], json.loads(row["cited_articles"]))
        if family in wanted:
            pool.setdefault(family, []).append(row)
    chosen: dict[str, list[dict]] = {}
    for family, rows in pool.items():
        unique = {r["jid"]: r for r in rows}.values()
        ordered = sorted(unique, key=lambda r: (_date_key(r["jid"]), r["jid"]), reverse=True)
        chosen[family] = ordered[: wanted[family]]
    return chosen, scanned


def backfill(conn: sqlite3.Connection, records: Iterable[dict], wanted: dict[str, int],
             dry_run: bool = False) -> BackfillResult:
    known_ids = {r[0] for r in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    have = {r[0] for r in conn.execute("SELECT jid FROM judgments")}
    result = BackfillResult(wanted=dict(wanted))
    result.chosen, result.scanned = select(records, wanted, known_ids, have)
    if not dry_run:
        rows = [row for rows in result.chosen.values() for row in rows]
        result.inserted, _skipped = load_judgments(rows, conn)
    return result


def _api_candidate(jid: str) -> bool:
    """Civil substantive judgments, plus 社維法 rulings (字別 contains 秩, filed
    on the criminal side and so excluded by the civil filter)."""
    from legal_agent.data.judicial_api import is_substantive_civil

    parts = jid.split(",")
    return is_substantive_civil(jid) or (len(parts) > 2 and "秩" in parts[2])


def records_from_api(user: str, password: str, limit: int, delay: float,
                     conn: sqlite3.Connection, progress=print) -> Iterator[dict]:
    """One night's change list, fetched one judgment at a time (gently).

    A jid the API answers 查無資料 for is deleted locally, as the harvester
    does: the court withdrew it, and the spec makes removal an obligation."""
    from legal_agent.data import judicial_api
    from legal_agent.data.judicial_json import delete_judgment

    token = judicial_api.auth(user, password)
    jids = [j for _d, jl in judicial_api.fetch_change_list(token) for j in jl]
    jids = [j for j in jids if _api_candidate(j)][:limit]
    progress(f"異動清單候選 {len(jids)} 筆(上限 {limit})")
    for i, jid in enumerate(jids, 1):
        jdoc = judicial_api.fetch_judgment(token, jid)
        time.sleep(delay)
        if jdoc is None:
            if delete_judgment(jid, conn):
                progress(f"  {jid} — 已從來源移除,本地留存一併刪除")
            continue
        yield jdoc_to_record(jdoc)
        if i % 100 == 0:
            progress(f"  [{i}/{len(jids)}]")


def main(argv: list[str] | None = None) -> int:
    from legal_agent import config

    parser = argparse.ArgumentParser(
        prog="python -m legal_agent.data.judgment_backfill",
        description="補同類判決不足 3 筆的糾紛家族(只收官方原文;先 --dry-run 看會補哪些)",
    )
    parser.add_argument("paths", nargs="*", help="本機裁判書 JSON 檔或資料夾(可遞迴)")
    parser.add_argument("--api", action="store_true", help="改從裁判書開放API 抓(0-6 時)")
    parser.add_argument("--limit", type=int, default=3000, help="--api 每晚最多抓幾筆")
    parser.add_argument("--delay", type=float, default=0.3, help="--api 每筆間隔秒數")
    parser.add_argument("--target", type=int, default=TARGET)
    parser.add_argument("--sessions", default=str(config.PROJECT_ROOT / "evals" / "real_sessions.json"))
    parser.add_argument("--dry-run", action="store_true", help="只列出會補哪些,不寫入")
    args = parser.parse_args(argv)
    if bool(args.paths) == args.api:
        parser.error("請給本機路徑,或 --api,二擇一")

    from legal_agent.data.bootstrap import ensure_corpus
    from legal_agent.data.database import connect

    ensure_corpus()
    conn = connect(config.DB_PATH)
    try:
        wanted = deficits(conn, args.sessions, args.target)
        unnamed = sorted(f for f in wanted if not nameable(f))
        if unnamed:
            # No 案由 maps to these, so no record can ever serve them.
            print(f"案由表認不出、補不到:{'、'.join(unnamed)}")
        wanted = {f: n for f, n in wanted.items() if nameable(f)}
        print(f"待補:{wanted or '無'}")
        if not wanted:
            return 0
        if args.api:
            import os

            from legal_agent.data.judicial_api import _load_env

            env = _load_env()
            user = os.environ.get("JUDICIAL_USER") or env.get("JUDICIAL_USER")
            password = os.environ.get("JUDICIAL_PASSWORD") or env.get("JUDICIAL_PASSWORD")
            if not user or not password:
                print("缺少憑證:請在 .env 或環境變數設定 JUDICIAL_USER / JUDICIAL_PASSWORD")
                return 2
            records = records_from_api(user, password, args.limit, args.delay, conn)
        else:
            records = records_from_paths(args.paths)
        print(backfill(conn, records, wanted, dry_run=args.dry_run).render())
    finally:
        conn.close()
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
