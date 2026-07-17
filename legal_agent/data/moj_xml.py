"""MOJ bulk-XML importer (spec §1.2) — 全國法規資料庫 官方 XML → proposal JSON.

Parses the official bulk download (``FalVMingLing.xml`` from the 公開資料下載
area, obtained with the owner's approved account — this module fetches NOTHING)
into the proposal-JSON shape that ``source_ingest.load_proposals`` already
validates and persists. The human stays in the loop (spec §1.5):

    MOJ bulk XML  --[this module: parse + normalize]-->  proposal JSON
    --[HUMAN verifies every entry]-->  python -m legal_agent.data.source_ingest

File shape (verified against the official format / kong0107-mojLawSplit):
    <LAWS UpdateDate="YYYY/MM/DD">
      <法規>
        <法規性質>法律|命令|憲法</法規性質>
        <法規名稱>噪音管制法</法規名稱>
        <法規網址>https://law.moj.gov.tw/...?pcode=O0030001</法規網址>
        <最新異動日期>20211208</最新異動日期>   ← 8位西元 或 7位民國
        <生效日期/> <廢止註記/> <沿革內容>…</沿革內容>
        <法規內容>
          <編章節>第 一 章 總則</編章節>       ← structural, skipped
          <條文><條號>第 9-1 條</條號><條文內容>…</條文內容></條文>
        </法規內容>
      </法規>
      …
    </LAWS>

Honesty limits (spec §1.3 trap 1 — stated, not papered over):
  * The bulk file carries LAW-level dates only, so every article of a law gets
    the law-level effective_from — per-article amendment history is NOT here.
  * A repealed law (廢止註記 non-empty) gets effective_to = its last change
    date, which yields an EMPTY validity window [d, d): retrieval will never
    surface it until the human reviewer fills the real historical window in.
    Each such law is reported as a warning for exactly that reason.
Laws it cannot represent honestly (unknown 法規性質, missing/garbled dates,
empty 條文) are skipped WITH a warning — never silently, never guessed.

Streaming (iterparse + clear) so the ~hundreds-of-MB national file parses in
constant memory. Stdlib only — no lxml, no network, no LLM, no DB access.

Run:  python -m legal_agent.data.moj_xml FalVMingLing.xml -o proposals.json \
          [--include 噪音管制法 --include 民法 …] [--strict]
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from legal_agent.data.roc_date import RocDateError, convert_roc_to_iso

# 法規性質 values this corpus can place on the authority ladder (spec §1.4).
# Anything else (自治條例, 條約, …) is skipped with a warning — the ladder has
# no verified rank for it, and guessing a rank is exactly what we refuse to do.
_KNOWN_LEVELS = frozenset({"憲法", "法律", "命令"})

_GREGORIAN_8 = re.compile(r"^\d{8}$")
_WHITESPACE = re.compile(r"[\s　]+")   # ASCII + full-width space


class MojXmlError(ValueError):
    """A law the importer refuses to represent (raised only under strict=True)."""


def _parse_moj_date(raw: str | None, label: str) -> str:
    """MOJ date text → ISO 'YYYY-MM-DD'. 8 digits = 西元 YYYYMMDD; everything
    else (7-digit compact, 110/01/20, 民國110年…) is delegated to the ROC
    converter, which never guesses. Raises MojXmlError on blank/invalid."""
    text = (raw or "").strip()
    if not text:
        raise MojXmlError(f"{label} 為空 — 無法建立時間切片")
    if _GREGORIAN_8.match(text):
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        except ValueError as exc:
            raise MojXmlError(f"{label} 非有效西元日期: {text!r}") from exc
    try:
        return convert_roc_to_iso(text)
    except RocDateError as exc:
        raise MojXmlError(f"{label} 無法解析: {text!r}") from exc


def _normalize_article_no(raw: str) -> str:
    """'第 9-1 條' → '第9-1條' (drop internal whitespace, keep everything else)."""
    return _WHITESPACE.sub("", raw)


def _law_to_proposals(law: ET.Element) -> tuple[list[dict], list[str]]:
    """One <法規> element → (proposal rows, warnings). Raises MojXmlError when
    the whole law cannot be represented (no name / unknown 性質 / no date)."""
    name = (law.findtext("法規名稱") or "").strip()
    if not name:
        raise MojXmlError("法規名稱 為空")

    level = (law.findtext("法規性質") or "").strip()
    if level not in _KNOWN_LEVELS:
        raise MojXmlError(
            f"「{name}」的 法規性質 {level!r} 不在位階表 {sorted(_KNOWN_LEVELS)} 內"
        )

    # 生效日期 when the file carries one, else the last-change date.
    warnings: list[str] = []
    raw_effective = (law.findtext("生效日期") or "").strip()
    # MOJ sentinel: 9999-12-31 means "latest amendment NOT yet in force". Taking
    # it literally would date-exclude the whole law from every point-in-time
    # query (found live on 民法) — fall back to the last-change date instead.
    if raw_effective.replace("-", "") == "99991231":
        warnings.append(
            f"「{name}」生效日期為 9999(修正尚未施行)— 改用最新異動日期"
        )
        raw_effective = ""
    effective_from = _parse_moj_date(
        raw_effective or law.findtext("最新異動日期"),
        f"「{name}」的 {'生效日期' if raw_effective else '最新異動日期'}",
    )
    effective_to: str | None = None
    if (law.findtext("廢止註記") or "").strip():
        effective_to = effective_from
        warnings.append(
            f"「{name}」已廢止:effective 區間暫記為空窗 [{effective_from}, "
            f"{effective_from}),檢索不會取用 — 需人工從沿革補上真實歷史區間"
        )

    source_url = (law.findtext("法規網址") or "").strip() or None

    proposals: list[dict] = []
    for article in law.iter("條文"):
        article_no = _normalize_article_no((article.findtext("條號") or "").strip())
        content = (article.findtext("條文內容") or "").strip()
        if not article_no:
            warnings.append(f"「{name}」有一筆條文缺 條號 — 已略過")
            continue
        if not content:
            warnings.append(f"「{name}」{article_no} 條文內容為空 — 已略過")
            continue
        proposals.append({
            "statute_id": name,
            "article_no": article_no,
            "content": content,               # verbatim (ends trimmed only)
            "effective_from": effective_from,
            "effective_to": effective_to,
            "hierarchy_level": level,
            "source_url": source_url,
        })
    return proposals, warnings


def parse_moj_xml(
    path: str | Path,
    include: set[str] | None = None,
    strict: bool = False,
) -> tuple[list[dict], list[str]]:
    """Parse an MOJ bulk XML file into source_ingest proposal rows.

    Args:
        path: the downloaded FalVMingLing.xml (or any file of the same shape).
        include: law names (法規名稱, exact) to keep; None = keep every law.
        strict: True → a law that cannot be represented raises MojXmlError;
            False (default) → it becomes a warning and parsing continues,
            because one malformed law must not nuke a national-scale file.

    Returns:
        (proposals, warnings) — proposals in source_ingest JSON shape;
        warnings say what was skipped or needs the human reviewer's hand.
    """
    proposals: list[dict] = []
    warnings: list[str] = []

    context = ET.iterparse(str(path), events=("start", "end"))
    _, root = next(context)                   # <LAWS> — kept for memory reclaim
    for event, elem in context:
        if event != "end" or elem.tag != "法規":
            continue
        name = (elem.findtext("法規名稱") or "").strip()
        if include is not None and name not in include:
            root.clear()                      # not selected — free and move on
            continue
        try:
            rows, law_warnings = _law_to_proposals(elem)
            proposals.extend(rows)
            warnings.extend(law_warnings)
        except MojXmlError as exc:
            if strict:
                raise
            warnings.append(f"整部法規略過:{exc}")
        root.clear()                          # constant memory on the big file
    return proposals, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m legal_agent.data.moj_xml",
        description="全國法規資料庫 bulk XML → source_ingest proposal JSON(供人工審核)",
    )
    parser.add_argument("xml_path", help="下載好的 FalVMingLing.xml")
    parser.add_argument("-o", "--out", required=True, help="輸出 proposal JSON 路徑")
    parser.add_argument(
        "--include", action="append", default=None, metavar="法規名稱",
        help="只擷取這些法規(可重複);不給則全檔擷取",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="遇到無法表示的法規直接失敗(預設:警告並續行)",
    )
    args = parser.parse_args(argv)

    include = set(args.include) if args.include else None
    proposals, warnings = parse_moj_xml(args.xml_path, include=include, strict=args.strict)

    Path(args.out).write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    laws = {p["statute_id"] for p in proposals}
    print(f"擷取 {len(laws)} 部法規、{len(proposals)} 條 → {args.out}")
    for w in warnings:
        print(f"警告:{w}")
    print("下一步:人工逐條核對後,再執行 "
          f"python -m legal_agent.data.source_ingest {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
