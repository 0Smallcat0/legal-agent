"""Ship the reference judgments with the repo — redacted to what the page shows.

A fresh clone used to get 2,560 statutes and ZERO judgments: `db/*.db` is
gitignored, and the 司法院 API serves only 00:00-06:00 and returns one day at a
time (seven days late), so reproducing the harvest takes weeks of nightly runs.
The README's own screenshot — real judgments with the 主文 award beside the
answer — was therefore the one thing a reader could not reproduce.

Two facts make shipping them cheap and safe:

**Only 386 of 1,367 can ever surface.** `retrieval/judgments.related_judgments`
is a deterministic JOIN on `cited_articles`; a judgment with no corpus article
in it is unreachable by construction. So the shipped set is not a sample — it
is the whole reachable set.

**The page reads two slices, not the document.** `judgment_text.citation()`
reads the header's court + 案號 lines, `awards()` reads the 主文. Everything
else (事實及理由) is never displayed. Keeping only those slices is measured
LOSSLESS for what is rendered — citation() and awards() return identical values
on all 386 — while dropping the party block, and it costs 0.26 MB instead of
5.9 MB.

**Names inside 主文 are dropped, not masked.** The party block goes with the
redaction, but 31 of the 386 also name a party in a 主文 sentence
(「被告陳○○應給付…」). Masking would make the 主文 no longer verbatim, and
verbatim-or-nothing is the rule the whole corpus rests on. So those 31 ship
with their header only: they still surface, still carry their article overlap,
and `awards()` returns () — the same silence the block already renders for a
judgment whose 主文 orders no readable payment. Dropping the judgments outright
was measured and rejected: it costs 19 of the 239 covered articles (勞基§24,
民法§226/§194/§482 among them) to remove names that this route removes anyway.

Detection uses the judgment's OWN party block as ground truth rather than a
surname heuristic — 「連帶給付」 and 「平方公尺」 are surname-shaped and are not
names, and a heuristic flagged 96 where the ground truth flags 31.

    python -m legal_agent.data.judgment_ingest -o corpus/judgments_v1.json
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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


def names_in_main_text(full_text: str | None) -> set[str]:
    """Party names that appear inside the 主文 itself."""
    block = main_text(full_text) or ""
    return {name for name in party_names(full_text) if name in block}


def redact(full_text: str | None) -> str:
    """Header (court + 案號) plus the 主文, and nothing else.

    Returns the header alone when the 主文 names a party — see the module
    docstring for why those are dropped rather than masked.
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
    inserted = 0
    for index, record in enumerate(records):
        jid = record.get("jid")
        if not jid:
            raise ValueError(f"judgment[{index}] 缺少 'jid'")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO judgments "
            "(jid, court, year, case_type, issues, cited_articles, holding, full_text) "
            "VALUES (?, ?, ?, ?, NULL, ?, NULL, ?)",
            (
                jid,
                record.get("court"),
                record.get("year"),
                record.get("case_type"),
                json.dumps(record.get("cited_articles") or [], ensure_ascii=False),
                record.get("full_text") or "",
            ),
        )
        inserted += cursor.rowcount
    conn.commit()
    return inserted


def main(argv: list[str] | None = None) -> int:
    import argparse

    from legal_agent.config import DB_PATH
    from legal_agent.data.database import connect

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", default="corpus/judgments_v1.json")
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
