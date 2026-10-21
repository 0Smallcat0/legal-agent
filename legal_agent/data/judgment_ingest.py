"""Ship the reference judgments with the repo — redacted to what the page shows.

The 司法院 API serves only 00:00-06:00, one day at a time, so a harvest cannot
practically be reproduced; the reachable judgments ship in the package instead.

  * Only judgments citing a corpus statute can surface (`related_judgments` is
    a JOIN on `cited_articles`), so the shipped set is the whole reachable set.
  * The page reads two slices — header (court + 案號) and 主文 — so only those
    are kept: lossless for `citation()`/`awards()`, and the party block goes.
  * A 主文 that names a party is dropped, not masked (masking breaks
    verbatim): those judgments ship header-only and still surface.
  * Names come from the judgment's OWN party block, not a surname heuristic
    (「連帶給付」 and 「平方公尺」 are surname-shaped).
Measurements: evals/HISTORY.md.

    python -m legal_agent.data.judgment_ingest -o corpus/judgments_v1.json
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from legal_agent.data import judicial_json
from legal_agent.data.judgment_text import (
    _CASE_NO_RE,
    _COURT_LINE_RE,
    main_text,
)

# The heading is rewritten with the ideographic spacing courts use, so
# `main_text()` finds it in the redacted text exactly as it did in the original.
MAIN_HEADING = "主　　文"

_PARTY_ROLES = (
    "原告", "被告", "上訴人", "被上訴人", "聲請人", "相對人",
    "債權人", "債務人", "法定代理人", "訴訟代理人", "複代理人", "參加人",
    "被移送人",          # 社維法 rulings (秩 字別): the person fined
)
_PARTY_BLOCK_END = ("上列當事人間", "當事人間", "主文")
# Party entries that name an organisation rather than a person.
_ORG_MARKERS = (
    "公司", "銀行", "事務所", "管理委員會", "協會", "基金會", "工會",
    "股份", "有限", "商行", "企業", "診所", "醫院", "學校", "政府", "機關",
)


def _party_block(full_text: str) -> str:
    """The header region that lists the parties, before the narrative starts."""
    cut = len(full_text)
    for marker in _PARTY_BLOCK_END:
        found = full_text.find(marker)
        if found != -1:
            cut = min(cut, found)
    return full_text[:cut]


def _looks_like_person(token: str) -> bool:
    token = token.strip()
    if not 2 <= len(token) <= 4:
        return False
    if any(marker in token for marker in _ORG_MARKERS):
        return False
    if "○" in token or "Ｏ" in token:      # already masked by the court
        return False
    return all("一" <= ch <= "鿿" for ch in token)


def party_names(full_text: str | None) -> set[str]:
    """Personal names the judgment itself lists as parties or representatives.

    Read from the party block, so it is ground truth rather than a guess: a
    token is a name because the court printed it under 原告/被告, not because
    it starts with a common surname.
    """
    if not full_text:
        return set()
    names: set[str] = set()
    for line in _party_block(full_text).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        compact = "".join(stripped.split())
        for role in _PARTY_ROLES:
            # Courts pad the label with ideographic spaces: 「原      告  王悟愷」.
            if compact.startswith(role):
                candidate = compact[len(role):]
                if _looks_like_person(candidate):
                    names.add(candidate)
                break
        else:
            # Continuation lines carry a further party with no label of their own.
            if line.startswith((" ", "　")) and _looks_like_person(stripped):
                names.add(stripped)
    return names


# A non-party the 主文 names (「對訴外人沈○○之財產執行無效果時」) is in no
# party block, so it is read where it stands. Masked (○) names do not match.
_NON_PARTY_RE = re.compile(r"訴外人([^\s，、。;；之及與對○Ｏ]{2,4})")


def names_in_main_text(full_text: str | None) -> set[str]:
    """Personal names — parties, or 訴外人 — that appear inside the 主文 itself."""
    block = main_text(full_text) or ""
    names = {name for name in party_names(full_text) if name in block}
    names |= {m for m in _NON_PARTY_RE.findall(block) if _looks_like_person(m)}
    return names


def redact(full_text: str | None) -> str:
    """Header (court + 案號) plus the 主文, and nothing else.

    Returns the header alone when the 主文 names a party (see module docstring).
    """
    if not full_text:
        return ""
    head = full_text[:400]
    kept = [
        match.group(1).strip()
        for match in (_COURT_LINE_RE.search(head), _CASE_NO_RE.search(head))
        if match
    ]
    block = main_text(full_text)
    if block and not names_in_main_text(full_text):
        kept += [MAIN_HEADING, block]
    return "\n".join(kept)


def surfaceable(conn: sqlite3.Connection) -> list[dict]:
    """The judgments a consultation can actually reach, redacted for shipping.

    Reachability is not a judgement call: `related_judgments` joins
    `cited_articles` against the retrieved statutes, so a judgment citing no
    corpus statute can never appear on a page.
    """
    corpus = {row[0] for row in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    records = []
    rows = conn.execute(
        "SELECT jid, court, year, case_type, cited_articles, full_text FROM judgments"
    )
    for jid, court, year, case_type, cited_articles, full_text in rows:
        try:
            cited = json.loads(cited_articles or "[]")
        except (TypeError, ValueError):
            continue
        kept = [c for c in cited if c.get("statute_id") in corpus]
        if not kept:
            continue
        records.append({
            "jid": jid,
            "court": court,
            "year": year,
            "case_type": case_type,
            "cited_articles": kept,
            "full_text": redact(full_text),
        })
    records.sort(key=lambda record: record["jid"])
    return records


def load_judgments(path: str | Path, conn: sqlite3.Connection) -> int:
    """Persist a shipped judgment file into `judgments`. Idempotent.

    爭點/裁判要旨 stay NULL for the same reason the harvester leaves them NULL:
    summarising reasoning is an NLP task this project will not fake.
    """
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{path} 需為 JSON 陣列")
    rows = []
    for index, record in enumerate(records):
        if not record.get("jid"):
            raise ValueError(f"judgment[{index}] 缺少 'jid'")
        rows.append({
            "jid": record["jid"],
            "court": record.get("court"),
            "year": record.get("year"),
            "case_type": record.get("case_type"),
            "issues": None,
            "cited_articles": json.dumps(record.get("cited_articles") or [], ensure_ascii=False),
            "holding": None,
            "full_text": record.get("full_text") or "",
        })
    inserted, _skipped = judicial_json.load_judgments(rows, conn)
    return inserted


def main(argv: list[str] | None = None) -> int:
    import argparse

    from legal_agent.config import CORPUS_DIR, DB_PATH
    from legal_agent.data.database import connect

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", default=str(CORPUS_DIR / "judgments_v1.json"))
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        records = surfaceable(conn)
    finally:
        conn.close()

    out = Path(args.out)
    out.write_text(
        json.dumps(records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    withheld = sum(1 for record in records if MAIN_HEADING not in record["full_text"])
    print(f"{len(records)} judgments -> {out}")
    print(f"  主文 withheld (names a party): {withheld}")
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
