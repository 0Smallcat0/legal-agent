"""Interactive statute data-entry + read-back CLI (build step 2).

A personal, single-user tool for hand-entering the ~dozen 住宅噪音 statute
articles read directly off law.moj.gov.tw. No scraping, no HTTP, no LLM — the
human types the real legal text. Everything writes only to the local SQLite DB
through data/database.py (reusing its connection logic).

Subcommands:
    seed   建立 source_hierarchy 的四個位階(FK 前置作業,冪等)
    add    逐條輸入條文(欄位逐一提示、生效日自動由民國轉 ISO、寫入前需確認)
    list   讀回 statutes 全部資料,並標記可疑列(空內容 / 無效日期 / 位階不符)

Run:  python -m legal_agent.cli {seed|add|list}
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import unicodedata
from datetime import date

from legal_agent.config import DB_PATH
from legal_agent.data.database import connect, init_db
from legal_agent.data.models import Statute
from legal_agent.data.roc_date import RocDateError, convert_roc_to_iso
from legal_agent.data.seed import seed_source_hierarchy

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ── CJK-aware display width (stdlib only — no external table library) ─────────
def _disp_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_width(text))


def _truncate(text: str, max_width: int) -> str:
    out, used = [], 0
    for char in text:
        cw = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + cw > max_width:
            out.append("…")
            break
        out.append(char)
        used += cw
    return "".join(out)


def _is_iso_date(value: object) -> bool:
    """True iff value is a strict 'YYYY-MM-DD' string naming a real calendar date."""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


# ── interactive prompt helpers (all Chinese-facing) ──────────────────────────
def _prompt_nonempty(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("  ⚠ 此欄位必填,請重新輸入。")


def _prompt_optional(label: str) -> str | None:
    value = input(f"{label}(可留空,直接 Enter 略過): ").strip()
    return value or None


def _prompt_multiline_content() -> str:
    print("條文內容 content(可多行貼上;輸入完成後,單獨一行輸入 END 結束):")
    while True:
        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == "END":
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        if text:
            return text
        print("  ⚠ 條文內容必填,請重新輸入(貼上內容後,單獨一行輸入 END)。")


def _prompt_roc_date(label: str, *, required: bool) -> tuple[str | None, str | None]:
    """Return (iso_date, raw_input). For an optional field, blank -> (None, None)."""
    while True:
        raw = input(f"{label}: ").strip()
        if not raw:
            if required:
                print("  ⚠ 此欄位必填。")
                continue
            return None, None
        try:
            return convert_roc_to_iso(raw), raw
        except RocDateError as exc:
            print(f"  ⚠ 日期無法轉換:{exc}")
            print("     範例:民國110年01月20日 或 1100120")


def _prompt_pick_level(levels: list[sqlite3.Row]) -> str:
    print("位階 hierarchy_level(輸入編號選擇,避免打錯):")
    for index, row in enumerate(levels, 1):
        desc = f" — {row['description']}" if row["description"] else ""
        print(f"  {index}) {row['level']}(rank {row['rank']}){desc}")
    while True:
        choice = input(f"編號 [1-{len(levels)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(levels):
            return levels[int(choice) - 1]["level"]
        print("  ⚠ 無效的編號,請重新選擇。")


def _confirm(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [y/n]: ").strip().lower()
        if answer in ("y", "yes", "是"):
            return True
        if answer in ("n", "no", "否"):
            return False
        print("  請輸入 y 或 n。")


# ── core DB operations (pure, unit-testable) ─────────────────────────────────
def insert_statute(conn: sqlite3.Connection, statute: Statute) -> None:
    """Insert one statute time-slice. Raises sqlite3.IntegrityError on a
    duplicate (statute_id, article_no, effective_from) or an unknown level."""
    conn.execute(
        "INSERT INTO statutes(statute_id, article_no, content, effective_from, "
        "effective_to, hierarchy_level, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            statute.statute_id,
            statute.article_no,
            statute.content,
            statute.effective_from,
            statute.effective_to,
            statute.hierarchy_level,
            statute.source_url,
        ),
    )
    conn.commit()


def _row_flags(row, valid_levels: set[str]) -> list[str]:
    """Return a list of human-readable problems for one statutes row (empty = ok)."""
    flags: list[str] = []
    if not (row["content"] or "").strip():
        flags.append("內容為空")
    from_ok = _is_iso_date(row["effective_from"])
    if not from_ok:
        flags.append("生效日非合法日期")
    to_val = row["effective_to"]
    to_ok = to_val is None or _is_iso_date(to_val)
    if not to_ok:
        flags.append("失效日非合法日期")
    if row["hierarchy_level"] not in valid_levels:
        flags.append("位階不在種子集合")
    if from_ok and to_val is not None and to_ok and to_val < row["effective_from"]:
        flags.append("失效日早於生效日")
    return flags


def _render_table(headers: list[str], rows_cells: list[list[str]]) -> None:
    cols = len(headers)
    widths = [_disp_width(h) for h in headers]
    for cells in rows_cells:
        for i in range(cols):
            widths[i] = max(widths[i], _disp_width(cells[i]))

    def fmt(cells: list[str]) -> str:
        return " │ ".join(_pad(cells[i], widths[i]) for i in range(cols))

    print(fmt(headers))
    print("─┼─".join("─" * w for w in widths))
    for cells in rows_cells:
        print(fmt(cells))


# ── subcommands ──────────────────────────────────────────────────────────────
def cmd_seed(conn: sqlite3.Connection) -> None:
    count = seed_source_hierarchy(conn)
    print("source_hierarchy 已就緒(位階,rank 越小權威越高):")
    for row in conn.execute("SELECT level, rank, description FROM source_hierarchy ORDER BY rank"):
        print(f"  rank {row['rank']}  {row['level']}  {row['description'] or ''}")
    print(f"共 {count} 列。(此指令可重複執行,不會重覆插入)")


def cmd_add(conn: sqlite3.Connection) -> None:
    levels = conn.execute(
        "SELECT level, rank, description FROM source_hierarchy ORDER BY rank"
    ).fetchall()
    if not levels:
        print("source_hierarchy 尚未建立,無法選擇位階。")
        print("請先執行:python -m legal_agent.cli seed")
        return

    print("開始逐條輸入(可隨時 Ctrl-C 中止)。\n")
    added = 0
    while True:
        print("═══════════ 新增一條 ═══════════")
        statute_id = _prompt_nonempty("法規名稱 statute_id(例:民法)")
        article_no = _prompt_nonempty("條號 article_no(例:第793條)")
        content = _prompt_multiline_content()
        iso_from, raw_from = _prompt_roc_date(
            "生效日 生效日期(民國;例 民國110年01月20日 或 1100120)", required=True
        )
        iso_to, raw_to = _prompt_roc_date(
            "失效日(民國;若仍有效請直接 Enter)", required=False
        )
        hierarchy_level = _prompt_pick_level(levels)
        source_url = _prompt_optional("來源網址 source_url")

        statute = Statute(
            statute_id=statute_id,
            article_no=article_no,
            content=content,
            effective_from=iso_from,
            effective_to=iso_to,
            hierarchy_level=hierarchy_level,
            source_url=source_url,
        )
        _preview(statute, raw_from, raw_to)

        if _confirm("確認寫入?"):
            try:
                insert_statute(conn, statute)
                added += 1
                print("  ✔ 已寫入。\n")
            except sqlite3.IntegrityError as exc:
                print(f"  ✘ 寫入失敗(此(法規,條號,生效日)可能已存在):{exc}\n")
        else:
            print("  ↩ 已放棄這一筆,未寫入。\n")

        if not _confirm("要再新增一條嗎?"):
            break
    print(f"結束。本次共寫入 {added} 筆。用 `list` 指令可讀回檢查。")


def _preview(statute: Statute, raw_from: str | None, raw_to: str | None) -> None:
    print("\n─────────── 請確認以下資料 ───────────")
    print(f"  法規名稱 statute_id     : {statute.statute_id}")
    print(f"  條號     article_no     : {statute.article_no}")
    print(f"  位階     hierarchy_level: {statute.hierarchy_level}")
    print(f"  生效日   effective_from : {statute.effective_from}   ← 輸入 {raw_from!r}")
    if statute.effective_to:
        print(f"  失效日   effective_to   : {statute.effective_to}   ← 輸入 {raw_to!r}")
    else:
        print("  失效日   effective_to   : (現行有效 / NULL)")
    print(f"  來源     source_url     : {statute.source_url or '(無)'}")
    print("  條文內容 content        :")
    for line in statute.content.splitlines() or [statute.content]:
        print(f"    │ {line}")
    print(f"  (內容共 {len(statute.content)} 字)")
    print("──────────────────────────────────────")


def cmd_list(conn: sqlite3.Connection) -> None:
    valid_levels = {r["level"] for r in conn.execute("SELECT level FROM source_hierarchy")}
    rows = conn.execute(
        "SELECT rowid, * FROM statutes ORDER BY statute_id, article_no, effective_from"
    ).fetchall()

    if not rows:
        print("statutes 目前沒有任何資料。")
        if not valid_levels:
            print("注意:source_hierarchy 尚未 seed(請先執行 `seed`)。")
        return

    headers = ["#", "法規名稱", "條號", "生效日", "失效日", "位階", "內容節錄", "旗標"]
    cells_list: list[list[str]] = []
    flagged: list[tuple[sqlite3.Row, list[str]]] = []
    for row in rows:
        flags = _row_flags(row, valid_levels)
        if flags:
            flagged.append((row, flags))
        excerpt = _truncate((row["content"] or "").replace("\n", "⏎"), 24)
        cells_list.append(
            [
                str(row["rowid"]),
                row["statute_id"] or "",
                row["article_no"] or "",
                row["effective_from"] or "",
                row["effective_to"] if row["effective_to"] is not None else "(現行)",
                row["hierarchy_level"] or "",
                excerpt,
                "⚠" if flags else "",
            ]
        )

    _render_table(headers, cells_list)
    print(f"\n共 {len(rows)} 列。")
    if flagged:
        print("⚠ 疑似需要人工檢查:")
        for row, flags in flagged:
            print(f"  #{row['rowid']} {row['statute_id']} {row['article_no']}:{'、'.join(flags)}")
    else:
        print("✔ 未發現明顯異常(空內容 / 無效日期 / 位階不符 / 失效早於生效)。")
    if not valid_levels:
        print("注意:source_hierarchy 尚未 seed,因此所有位階都會被標記。")


def main(argv: list[str] | None = None) -> int:
    # Make CJK / box-drawing output safe even when stdout is redirected (Windows).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        prog="legal_agent.cli", description="住宅噪音 statute 資料輸入 / 讀回工具"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="建立四個位階(FK 前置,冪等)")
    sub.add_parser("add", help="逐條互動輸入條文")
    sub.add_parser("list", help="讀回並檢查已輸入條文")
    args = parser.parse_args(argv)

    init_db(DB_PATH)          # idempotent: guarantee the tables exist
    conn = connect(DB_PATH)   # reuse existing connection logic (FK ON + Row factory)
    try:
        if args.command == "seed":
            cmd_seed(conn)
        elif args.command == "add":
            cmd_add(conn)
        elif args.command == "list":
            cmd_list(conn)
    except KeyboardInterrupt:
        print("\n已中止,未完成的輸入不會寫入。")
        return 130
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
