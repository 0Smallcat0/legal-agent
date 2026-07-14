"""Tests for the MOJ bulk-XML importer (spec §1.2) — parse the official-format
XML into source_ingest proposal rows, honestly skipping what it cannot
represent. Deterministic, no network; fixture is synthetic 測試-prefixed text.

Run:  python -m pytest tests/test_moj_xml.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.moj_xml import (  # noqa: E402
    MojXmlError,
    main,
    parse_moj_xml,
)
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.data.source_ingest import load_proposals  # noqa: E402
from legal_agent.retrieval.retriever import retrieve  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "moj_sample.xml"


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "t.db"
    init_db(db)
    connection = connect(db)
    seed_source_hierarchy(connection)
    yield connection
    connection.close()


def _by_law(proposals):
    grouped: dict[str, list[dict]] = {}
    for p in proposals:
        grouped.setdefault(p["statute_id"], []).append(p)
    return grouped


# ── parsing: the happy path ──────────────────────────────────────────────────
def test_law_parses_to_source_ingest_shape():
    proposals, _ = parse_moj_xml(FIXTURE)
    law = _by_law(proposals)["測試噪音管制法"]

    assert [p["article_no"] for p in law] == ["第1條", "第9-1條"]  # spaces dropped
    first = law[0]
    assert first["effective_from"] == "2021-12-08"     # 8-digit 西元 YYYYMMDD
    assert first["effective_to"] is None
    assert first["hierarchy_level"] == "法律"
    assert first["source_url"].endswith("pcode=T0000001")
    # verbatim content — the retriever/verifier depend on untouched text
    assert first["content"] == "為維護國民健康及環境安寧,提高國民生活品質,特制定本測試法。"


def test_roc_compact_date_converts_to_iso():
    proposals, _ = parse_moj_xml(FIXTURE)
    order = _by_law(proposals)["測試噪音管制標準"]
    assert order[0]["effective_from"] == "2021-01-20"  # 1100120 → ROC 110 → 2021
    assert order[0]["hierarchy_level"] == "命令"


def test_empty_article_is_skipped_with_warning():
    proposals, warnings = parse_moj_xml(FIXTURE)
    assert all(p["article_no"] != "第99條" for p in proposals)
    assert any("第99條" in w and "為空" in w for w in warnings)


# ── honesty: repealed laws and unknown tiers ─────────────────────────────────
def test_repealed_law_gets_empty_window_and_warning():
    proposals, warnings = parse_moj_xml(FIXTURE)
    repealed = _by_law(proposals)["測試已廢止法"]
    # empty half-open window [d, d): stored, but never retrievable until the
    # human reviewer fills in the true historical range
    assert repealed[0]["effective_from"] == "2020-01-01"
    assert repealed[0]["effective_to"] == "2020-01-01"
    assert any("測試已廢止法" in w and "廢止" in w for w in warnings)


def test_unknown_nature_is_skipped_with_warning_not_guessed():
    proposals, warnings = parse_moj_xml(FIXTURE)
    assert "測試市噪音自治條例" not in _by_law(proposals)   # no rank → no row
    assert any("自治條例" in w for w in warnings)


def test_strict_mode_raises_instead_of_warning():
    with pytest.raises(MojXmlError, match="自治條例"):
        parse_moj_xml(FIXTURE, strict=True)


# ── selection ────────────────────────────────────────────────────────────────
def test_include_filter_keeps_only_named_laws():
    proposals, warnings = parse_moj_xml(FIXTURE, include={"測試噪音管制標準"})
    assert set(_by_law(proposals)) == {"測試噪音管制標準"}
    assert warnings == []   # skipped-by-filter laws produce no noise


# ── round trip: XML → proposals → ingest → point-in-time retrieval ──────────
def test_round_trip_into_corpus_and_retrieval(conn, tmp_path):
    proposals, _ = parse_moj_xml(FIXTURE)
    proposal_file = tmp_path / "proposals.json"
    proposal_file.write_text(
        json.dumps(proposals, ensure_ascii=False), encoding="utf-8"
    )

    inserted, skipped = load_proposals(proposal_file, conn)
    assert (inserted, skipped) == (len(proposals), 0)

    # the current slice is retrievable through the normal pipeline
    hits = retrieve("測試近鄰噪音罰鍰", conn=conn)
    assert any(
        s.statute_id == "測試噪音管制法" and s.article_no == "第9-1條" for s in hits
    )

    # the repealed law's empty window keeps it out of EVERY point in time
    for as_of in (None, "2019-12-31", "2020-01-01", "2026-01-01"):
        assert all(
            s.statute_id != "測試已廢止法"
            for s in retrieve("本測試法已廢止", as_of_date=as_of, conn=conn)
        )


# ── CLI ──────────────────────────────────────────────────────────────────────
def test_cli_writes_proposal_json(tmp_path, capsys):
    out = tmp_path / "out.json"
    assert main([str(FIXTURE), "-o", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    reference, _ = parse_moj_xml(FIXTURE)
    assert written == reference

    stdout = capsys.readouterr().out
    assert "3 部法規" in stdout          # 噪音管制法 + 管制標準 + 已廢止法
    assert "source_ingest" in stdout     # tells the human the next step
