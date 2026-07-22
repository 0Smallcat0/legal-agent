"""裁判書開放API harvester — the network half in front of judicial_json.py.

Spec (官方規格 114.08.22, opendata.judicial.gov.tw):
  * POST /jdg/api/Auth  {user, password}   -> {Token}, valid 6 hours
  * POST /jdg/api/JList {token}            -> the change list of the single day
    SEVEN DAYS AGO: [{date, list: [jid, ...]}] — an INCREMENTAL feed, not bulk
  * POST /jdg/api/JDoc  {token, j: jid}    -> one judgment: JID/JYEAR/JCASE/
    JNO/JDATE/JTITLE + JFULLX{JFULLTYPE, JFULLCONTENT, JFULLPDF} + ATTACHMENTS
  * Service window: 每日凌晨 0-6 時 ONLY. Outside it the API refuses — this
    module warns but lets the server be the judge.
  * A jid appearing again = the judgment was AMENDED (overwrite); the error
    「查無資料 …」 = removed/未公開 — skip, and any local copy must be deleted.

Credentials come from the environment (JUDICIAL_USER / JUDICIAL_PASSWORD) or a
gitignored `.env` file at the repo root — never from source, never committed.

The importer (judicial_json.py) stays the single door into the `judgments`
table; this module only fetches and ADAPTS the JDoc shape to the importer's
flat-JFULL record (`jdoc_to_record`). Judgments remain REFERENCE material —
never retrieval candidates, never citable law (spec §1.2).

Run (inside the 0-6h window):
    python -m legal_agent.data.judicial_api --limit 200
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_BASE = "https://data.judicial.gov.tw/jdg/api"
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

# 民事(V) procedural 字別 with little consultative value — 司促 (payment
# orders) alone is ~1/3 of a day's civil feed and carries no reasoning.
# Conservative EXCLUDE list: everything 司-prefixed (司促/司執/司聲/司養聲…)
# plus bare orders; anything else civil is kept.
_PROCEDURAL_JCASE_PREFIX = ("司",)
_PROCEDURAL_JCASE = {"促", "聲", "抗", "全", "裁全", "聲全", "事聲", "續"}


def _load_env(path: Path = _ENV_PATH) -> dict[str, str]:
    """Minimal KEY=VALUE reader for the gitignored .env (no dependency)."""
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip()
    return values


def _post(path: str, payload: dict, timeout: float = 120.0) -> object:
    req = urllib.request.Request(
        f"{_BASE}/{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"裁判書API呼叫失敗({path}):{exc}") from exc


def auth(user: str, password: str) -> str:
    """Exchange platform credentials for a 6-hour token."""
    data = _post("Auth", {"user": user, "password": password})
    token = data.get("Token") if isinstance(data, dict) else None
    if not token:
        raise RuntimeError(f"驗證失敗:{data!r}")
    return token


def fetch_change_list(token: str) -> list[tuple[str, list[str]]]:
    """The 7-days-ago change list: [(date, [jid, ...]), ...]."""
    data = _post("JList", {"token": token})
    if not isinstance(data, list):
        raise RuntimeError(f"JList 回應非清單:{data!r}")
    return [(str(d.get("date")), list(d.get("list") or [])) for d in data]


def fetch_judgment(token: str, jid: str) -> dict | None:
    """One judgment, or None when the API says 查無資料 (removed/未公開)."""
    data = _post("JDoc", {"token": token, "j": jid})
    if isinstance(data, dict) and data.get("error"):
        return None
    return data if isinstance(data, dict) else None


def is_substantive_civil(jid: str) -> bool:
    """Civil (V) and not a procedural 字別 — the consultative slice of a day."""
    parts = jid.split(",")
    if len(parts) < 3 or not parts[0].endswith("V"):
        return False
    jcase = parts[2]
    if any(jcase.startswith(p) for p in _PROCEDURAL_JCASE_PREFIX):
        return False
    return jcase not in _PROCEDURAL_JCASE


def jdoc_to_record(jdoc: dict) -> dict:
    """JDoc's nested shape -> the flat record judicial_json.parse_judgment eats.
    JFULL = JFULLX.JFULLCONTENT regardless of JFULLTYPE (text or file — the
    content field carries the text either way; the PDF url is not stored)."""
    fullx = jdoc.get("JFULLX") or {}
    return {
        "JID": jdoc.get("JID"),
        "JYEAR": jdoc.get("JYEAR"),
        "JTITLE": jdoc.get("JTITLE"),
        "JFULL": (fullx.get("JFULLCONTENT") or "") if isinstance(fullx, dict) else "",
    }


def harvest(
    user: str,
    password: str,
    limit: int = 200,
    delay: float = 0.3,
    only_substantive_civil: bool = True,
    progress=print,
) -> tuple[int, int, int]:
    """Auth -> JList -> JDoc loop -> judgments table. Returns
    (fetched, inserted, skipped). Gentle by design: serial, `delay` between
    calls, hard `limit` — the nightly window is shared infrastructure."""
    from legal_agent import config
    from legal_agent.data.database import connect, init_db
    from legal_agent.data.judicial_json import load_judgments, parse_judgment

    hour = datetime.now().hour
    if hour >= 6:
        progress(f"警告:現在 {hour} 時 — API 服務時間為 0-6 時,伺服器可能拒絕。")

    token = auth(user, password)
    days = fetch_change_list(token)
    jids = [j for _date, jlist in days for j in jlist]
    if only_substantive_civil:
        jids = [j for j in jids if is_substantive_civil(j)]
    progress(f"異動清單:{sum(len(l) for _d, l in days)} 筆,篩選後 {len(jids)} 筆,"
             f"本次上限 {limit} 筆")
    jids = jids[:limit]

    init_db(config.DB_PATH)
    conn = connect(config.DB_PATH)
    try:
        known_ids = {r[0] for r in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
        # Skip jids already in the table BEFORE spending API calls on them.
        # (Amended-judgment refresh is a known TODO — the importer skips dup
        # PKs anyway, so behaviour is unchanged, just cheaper.)
        have = {r[0] for r in conn.execute("SELECT jid FROM judgments")}
        todo = [j for j in jids if j not in have]
        if len(todo) < len(jids):
            progress(f"已在庫 {len(jids) - len(todo)} 筆,不重抓;本次實際 {len(todo)} 筆")

        rows: list[dict] = []
        fetched = inserted = skipped = 0
        for i, jid in enumerate(todo, 1):
            jdoc = fetch_judgment(token, jid)
            time.sleep(delay)
            if jdoc is None:
                progress(f"  [{i}/{len(todo)}] {jid} — 查無資料(已移除/未公開),略過")
                continue
            fetched += 1
            row, warnings = parse_judgment(jdoc_to_record(jdoc), known_ids)
            for w in warnings:
                progress(f"  警告:{w}")
            if row is not None:
                rows.append(row)
            # Batch-insert: a mid-run kill (network drop, window close, Ctrl-C)
            # keeps every completed batch instead of losing the whole run.
            if len(rows) >= 50:
                ins, skp = load_judgments(rows, conn)
                inserted += ins
                skipped += skp
                rows = []
            if i % 25 == 0:
                progress(f"  [{i}/{len(todo)}] 已取得 {fetched} 筆…")
        if rows:
            ins, skp = load_judgments(rows, conn)
            inserted += ins
            skipped += skp
    finally:
        conn.close()
    progress(f"完成:取得 {fetched},入庫 {inserted},重複略過 {skipped}")
    return fetched, inserted, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m legal_agent.data.judicial_api",
        description="裁判書開放API 收割:Auth → 異動清單 → 逐筆全文 → judgments 表"
                    "(參考層;服務時間每日 0-6 時)",
    )
    parser.add_argument("--limit", type=int, default=200, help="本次最多抓幾筆(預設 200)")
    parser.add_argument("--all-types", action="store_true",
                        help="不篩選——預設只收民事(V)非程序性字別")
    parser.add_argument("--delay", type=float, default=0.3, help="每筆間隔秒數(預設 0.3)")
    args = parser.parse_args(argv)

    env = _load_env()
    import os
    user = os.environ.get("JUDICIAL_USER") or env.get("JUDICIAL_USER")
    password = os.environ.get("JUDICIAL_PASSWORD") or env.get("JUDICIAL_PASSWORD")
    if not user or not password:
        print("缺少憑證:請在 .env 或環境變數設定 JUDICIAL_USER / JUDICIAL_PASSWORD")
        return 2

    harvest(user, password, limit=args.limit, delay=args.delay,
            only_substantive_civil=not args.all_types)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
