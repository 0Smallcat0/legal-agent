"""司法院裁判書查詢 (judgment.judicial.gov.tw/FJUD) — the public, no-account source.

The 裁判書開放API and the opendata monthly archives both need an account
(RESULTS §10). The public search site does not: its 進階查詢 form takes a 案由
(`jud_title`) and returns a paged list, and each result's page carries the
court's full text. This module turns that into the flat record the importer
already eats ({JID, JYEAR, JTITLE, JFULL}), so everything downstream —
`judgment_backfill` selection, `judicial_json.parse_judgment`, the redaction in
`judgment_ingest` — is unchanged. Nothing here writes a judgment.

Manners, because it is someone else's server:
  * at least 3 seconds between ANY two requests (`MIN_DELAY`, not lowerable);
  * every response that yields data is cached under LEGAL_AGENT_HOME, so a
    re-run, or a run resumed after a crash, asks for nothing it already has;
  * only 判決 are fetched (a 裁定 is skipped from its list row), except where
    a 裁定 is the merits decision (`RULINGS_ARE_MERITS`).

The JID is the site's own `id` parameter — the same comma form the API uses
(「KSDV,115,訴,973,20261014,1」), so a record from here and one from the API
are the same row.

    python -m legal_agent.data.fjud --fill            # the families backfill wants
    python -m legal_agent.data.fjud --title 返還寄託物 --max 10
    python -m legal_agent.data.judgment_backfill "$LEGAL_AGENT_HOME/fjud_cache/docs"
"""
from __future__ import annotations

import argparse
import hashlib
import html
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

BASE = "https://judgment.judicial.gov.tw/FJUD/"
MIN_DELAY = 3.0
# The site's bot defence rejects a bare client; these are what a browser sends.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

# 案由 queries per family. Each must read back as that family through
# `judgment_relevance.case_type_family` (a test holds this), or nothing fetched
# with it could ever count.
FAMILY_QUERIES: dict[str, tuple[str, ...]] = {
    "寄託": ("返還寄託物", "寄託"),
    "保證": ("保證債務", "連帶保證"),
    "使用借貸": ("返還借用物", "使用借貸"),
    "秩序": ("社會秩序維護法",),
    "贈與": ("撤銷贈與",),
    "委任": ("服務報酬", "交付帳冊"),
    "買賣": ("買賣價金", "貨款"),
    "擔保物權": ("抵押權不存在", "抵押權"),
}

# 社維法 cases are decided by 裁定 (社會秩序維護法第45條), so for that family a
# 裁定 is the merits decision, not a procedural side order.
RULINGS_ARE_MERITS = frozenset({"秩序"})

_ROW_RE = re.compile(
    r'href="data\.aspx\?ty=JD&amp;id=(?P<id>[^"&]+)[^"]*"[^>]*>(?P<head>[^<]*)</a>'
    r'.*?<td>(?P<date>[^<]*)</td>\s*<td[^>]*>(?P<title>[^<]*)</td>',
    re.S,
)
_LIST_RE = re.compile(r"qryresultlst\.aspx\?[^\"']+")
_TOTAL_RE = re.compile(r"共\s*([\d,]+)\s*筆")
_HIDDEN_RE = re.compile(r'name="(__[A-Z]+)" id="[^"]*" value="([^"]*)"')


def default_cache() -> Path:
    from legal_agent import config

    return config.DATA_DIR / "fjud_cache"


def _key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class ListRow:
    jid: str
    heading: str        # 「臺灣臺北地方法院 114 年度 簡上 字第 516 號民事判決」
    date: str           # ROC 「115.10.14」
    case_type: str      # the 案由 column

    @property
    def is_judgment(self) -> bool:
        return self.heading.rstrip().endswith("判決")


def parse_list(page: str) -> tuple[list[ListRow], int | None]:
    """A qryresultlst page -> (rows, total hits as the site reports it)."""
    rows = [
        ListRow(urllib.parse.unquote(m["id"]), html.unescape(m["head"]).strip(),
                m["date"].strip(), html.unescape(m["title"]).strip())
        for m in _ROW_RE.finditer(page)
    ]
    total = _TOTAL_RE.search(page)
    return rows, int(total.group(1).replace(",", "")) if total else None


def _strip(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>|</div>|</p>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    # Nested <div>s close several at once; the empty lines that leaves are markup.
    lines = [line.rstrip() for line in html.unescape(text).replace("\r", "").split("\n")]
    return "\n".join(line for line in lines if line.strip())


def _field(page: str, label: str) -> str:
    at = page.find(f"{label}：")
    if at < 0:
        return ""
    m = re.search(r'<div class="col-td[^"]*">(.*?)</div>', page[at:at + 600], re.S)
    return re.sub(r"\s+", " ", _strip(m.group(1))).strip() if m else ""


def parse_document(page: str, jid: str) -> dict | None:
    """A data.aspx page -> the importer's flat record, or None if it holds no text.

    Two layouts occur: older judgments as one preformatted block (`text-pre`),
    newer ones as one <div> per line (`htmlcontent`). Either way the text is
    the court's, line for line."""
    text = ""
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)   # upload metadata, not text
    pre = re.search(r'<div class="text-pre text-pre-in">(.*?)</div>', page, re.S)
    if pre and pre.group(1).strip():
        text = _strip(pre.group(1))
    else:
        at = page.find('<div class="htmlcontent">')
        if at >= 0:
            end = page.find('<div class="text-pre text-pre-in">', at)
            text = _strip(page[at:end if end > 0 else len(page)])
    if not text.strip():
        return None
    parts = jid.split(",")
    return {
        "JID": jid,
        "JYEAR": parts[1] if len(parts) > 1 else "",
        "JTITLE": _field(page, "裁判案由"),
        "JFULL": text,
        "SOURCE": BASE + "data.aspx?ty=JD&id=" + urllib.parse.quote(jid, safe=""),
    }


class Client:
    """One browser-like session, throttled to MIN_DELAY between requests."""

    def __init__(self, delay: float = MIN_DELAY, log=print):
        self.delay = max(MIN_DELAY, delay)
        self.log = log
        self._last = 0.0
        self.requests = 0
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def get(self, url: str, data: dict | None = None, referer: str | None = None) -> str:
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        headers = dict(_HEADERS)
        if referer:
            headers["Referer"] = referer
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with self._opener.open(request, timeout=60) as response:
                page = response.read().decode("utf-8", "replace")
        finally:
            self._last = time.monotonic()
            self.requests += 1
        if "rejected by bot-defense" in page:
            raise RuntimeError(f"bot-defense rejected {url}")
        return page

    def search(self, title: str, sys_code: str = "") -> str:
        """Submit the 進階查詢 form for one 案由; returns the list URL (session-bound)."""
        self.get(BASE + "default.aspx")
        form_page = self.get(BASE + "Default_AD.aspx", referer=BASE + "default.aspx")
        form = dict(_HIDDEN_RE.findall(form_page))
        form.update({
            "jud_court": "", "jud_sys": sys_code, "jud_year": "", "sel_judword": "常用字別",
            "jud_case": "", "jud_no": "", "jud_no_end": "", "dy1": "", "dm1": "",
            "dd1": "", "dy2": "", "dm2": "", "dd2": "", "jud_title": title,
            "jud_jmain": "", "jud_kw": "", "KbStart": "", "KbEnd": "",
            "judtype": "JUDBOOK", "whosub": "0", "ctl00$cp_content$btnQry": "送出查詢",
        })
        result = self.get(BASE + "Default_AD.aspx", data=form, referer=BASE + "Default_AD.aspx")
        found = _LIST_RE.search(result)
        if not found:
            raise RuntimeError(f"no result list for 案由 {title!r}")
        return BASE + html.unescape(found.group(0))


class Cache:
    """List pages and documents on disk; what is here is never fetched again."""

    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "lists").mkdir(parents=True, exist_ok=True)
        (self.root / "docs").mkdir(parents=True, exist_ok=True)

    def list_path(self, title: str, sys_code: str, page: int) -> Path:
        return self.root / "lists" / f"{_key(title, sys_code, str(page))}.json"

    def doc_path(self, jid: str) -> Path:
        return self.root / "docs" / f"{_key(jid)}.json"

    def missing_path(self, jid: str) -> Path:
        return self.root / "docs" / f"{_key(jid)}.none"


def list_rows(client: Client, cache: Cache, title: str, sys_code: str = "",
              pages: int = 3) -> Iterator[ListRow]:
    """Result rows for one 案由, newest first, up to `pages` pages of 20."""
    list_url: str | None = None
    for page in range(1, pages + 1):
        path = cache.list_path(title, sys_code, page)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            if list_url is None:
                list_url = client.search(title, sys_code)
            raw = client.get(f"{list_url}&sort=DS&page={page}", referer=BASE + "Default_AD.aspx")
            rows, total = parse_list(raw)
            payload = {"title": title, "sys": sys_code, "page": page, "total": total,
                       "rows": [row.__dict__ for row in rows]}
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        rows = [ListRow(**r) for r in payload["rows"]]
        yield from rows
        if len(rows) < 20:
            return


def document(client: Client, cache: Cache, jid: str) -> dict | None:
    """The record for one jid, from cache or the site (then cached)."""
    path = cache.doc_path(jid)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if cache.missing_path(jid).exists():
        return None
    url = BASE + "data.aspx?ty=JD&id=" + urllib.parse.quote(jid, safe="") + "&ot=in"
    record = parse_document(client.get(url, referer=BASE + "qryresultlst.aspx"), jid)
    if record is None:
        cache.missing_path(jid).write_text("", encoding="utf-8")
        return None
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return record


def collect(client: Client, cache: Cache, family: str, need: int, known_ids: set[str],
            have: set[str], pages: int = 3, log=print) -> list[dict]:
    """Fetch until `need` records serve `family`, newest first.

    A row is fetched only when its listed 案由 already reads as the family; a
    fetched record counts only when `serves_family` accepts it (it must also
    cite one of the family's articles — the page can reach it no other way)."""
    from legal_agent.data.judicial_json import parse_judgment
    from legal_agent.evaluation.judgment_coverage import serves_family
    from legal_agent.evaluation.judgment_relevance import case_type_family

    got: list[dict] = []
    seen: set[str] = set()
    for title in FAMILY_QUERIES.get(family, ()):
        for row in list_rows(client, cache, title, pages=pages):
            if len(got) >= need:
                return got
            merits = row.is_judgment or family in RULINGS_ARE_MERITS
            if (row.jid in seen or row.jid in have or not merits
                    or case_type_family(row.case_type) != family):
                continue
            seen.add(row.jid)
            record = document(client, cache, row.jid)
            if record is None:
                continue
            parsed, _warnings = parse_judgment(record, known_ids)
            if parsed and serves_family(parsed["case_type"], json.loads(parsed["cited_articles"])) == family:
                got.append(record)
                log(f"  {family}: {row.jid}  {row.case_type}")
    return got


def main(argv: list[str] | None = None) -> int:
    from legal_agent import config

    parser = argparse.ArgumentParser(
        prog="python -m legal_agent.data.fjud",
        description="從司法院裁判書查詢網站抓判決原文到本機快取(間隔 ≥3 秒、可續抓)",
    )
    parser.add_argument("--fill", action="store_true", help="抓 judgment_backfill 認定不足的家族")
    parser.add_argument("--title", help="改為抓單一案由")
    parser.add_argument("--sys", default="", help="裁判類別(V 民事、M 刑事…;預設全部)")
    parser.add_argument("--max", type=int, default=10, help="--title 模式最多抓幾份全文")
    parser.add_argument("--pages", type=int, default=3, help="每個案由最多翻幾頁(每頁 20 筆)")
    parser.add_argument("--target", type=int, default=None)
    parser.add_argument("--delay", type=float, default=MIN_DELAY)
    parser.add_argument("--cache", default=None, help="快取資料夾(預設 LEGAL_AGENT_HOME/fjud_cache)")
    parser.add_argument("--sessions", default=str(config.PROJECT_ROOT / "evals" / "real_sessions.json"))
    args = parser.parse_args(argv)
    if bool(args.fill) == bool(args.title):
        parser.error("請給 --fill 或 --title,二擇一")

    cache = Cache(Path(args.cache) if args.cache else default_cache())
    client = Client(args.delay)
    if args.title:
        fetched = 0
        for row in list_rows(client, cache, args.title, args.sys, args.pages):
            if fetched >= args.max:
                break
            if row.is_judgment and document(client, cache, row.jid) is not None:
                fetched += 1
                print(f"  {row.jid}  {row.case_type}")
        print(f"全文 {fetched} 份;本次連線 {client.requests} 次;快取 {cache.root}")
        return 0

    from legal_agent.data.bootstrap import ensure_corpus
    from legal_agent.data.database import connect
    from legal_agent.data.judgment_backfill import deficits
    from legal_agent.evaluation.judgment_coverage import TARGET, nameable

    ensure_corpus()
    conn = connect(config.DB_PATH)
    try:
        wanted = deficits(conn, args.sessions, args.target or TARGET)
        known_ids = {r[0] for r in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
        have = {r[0] for r in conn.execute("SELECT jid FROM judgments")}
    finally:
        conn.close()
    for family, need in wanted.items():
        if not nameable(family) or family not in FAMILY_QUERIES:
            print(f"{family}: 沒有可查的案由,跳過")
            continue
        got = collect(client, cache, family, need, known_ids, have, args.pages)
        print(f"{family}: 需要 {need},取得 {len(got)}")
    print(f"本次連線 {client.requests} 次;快取 {cache.root / 'docs'}")
    return 0


if __name__ == "__main__":       # pragma: no cover
    raise SystemExit(main())
