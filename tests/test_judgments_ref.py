"""Tests for the reference-judgment lookup (retrieval/judgments.py) and its
stage-3 wiring. Deterministic: tmp DB, fake LLM, no network.

Run:  python -m pytest tests/test_judgments_ref.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.database import connect, init_db  # noqa: E402
from legal_agent.data.models import Statute  # noqa: E402
from legal_agent.data.seed import seed_source_hierarchy  # noqa: E402
from legal_agent.retrieval.judgments import related_judgments, render_block  # noqa: E402

STUB_ANSWER = (
    "「法律明文」:依民法第184條。\n"
    "「實務見解」:以下為主管機關實務見解/處理原則,非法律明文,僅供參考。(無)\n"
    "「分析研判」:僅供參考。"
)


def _statute(sid="民法", ano="第184條", content="因故意或過失,不法侵害他人之權利者,負損害賠償責任。"):
    return Statute(sid, ano, content, "2010-01-01", None, "法律", None)


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "j.db"
    init_db(db)
    c = connect(db)
    seed_source_hierarchy(c)
    c.execute(
        "INSERT INTO statutes VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("民法", "第184條", "因故意或過失,不法侵害他人之權利者,負損害賠償責任。",
         "2010-01-01", None, "法律", None),
    )
    rows = [
        ("AAA,114,訴,1,20260101,1", "AAA", "損害賠償",
         [{"statute_id": "民法", "article_no": "第184條"},
          {"statute_id": "民法", "article_no": "第195條"}]),
        ("BBB,115,簡,2,20260201,1", "BBB", "修復漏水",
         [{"statute_id": "民法", "article_no": "第184條"}]),
        ("CCC,115,訴,3,20260301,1", "CCC", "給付票款",
         [{"statute_id": "票據法", "article_no": "第5條"}]),
    ]
    for jid, court, case_type, cited in rows:
        c.execute(
            "INSERT INTO judgments (jid, court, year, case_type, issues, "
            "cited_articles, holding, full_text) VALUES (?, ?, ?, ?, NULL, ?, NULL, ?)",
            (jid, court, 114, case_type, json.dumps(cited, ensure_ascii=False), "全文"),
        )
    c.commit()
    yield c
    c.close()


def test_overlap_ranked_and_unrelated_excluded(conn):
    retrieved = [_statute(), _statute("民法", "第195條", "非財產上之損害…")]
    refs = related_judgments(retrieved, conn=conn)
    assert [r.jid for r in refs] == ["AAA,114,訴,1,20260101,1", "BBB,115,簡,2,20260201,1"]
    assert refs[0].matched == ("民法第184條", "民法第195條")   # 2-overlap wins
    assert all("CCC" not in r.jid for r in refs)               # 票據法-only never surfaces


def test_no_overlap_or_no_retrieved_gives_empty(conn):
    assert related_judgments([], conn=conn) == []
    other = [_statute("噪音管制法", "第6條", "…")]
    assert related_judgments(other, conn=conn) == []


def test_render_block_labels_reference_tier(conn):
    refs = related_judgments([_statute()], conn=conn)
    text = render_block(refs)
    assert "非法律明文" in text and "僅供參考" in text
    assert "AAA,114,訴,1,20260101,1" in text and "損害賠償" in text


def test_stage3_carries_related_judgments(conn, monkeypatch):
    # A one-article tmp corpus scores under the honesty floor by construction —
    # pin the tier (the floor has its own tests) so the judgment JOIN is what
    # this test exercises.
    from legal_agent.dialogue import stage3 as s3mod

    monkeypatch.setattr(s3mod, "grade_honesty", lambda retrieved, scores: "normal")
    result = s3mod.run_stage3(
        {"problem": "被侵害請求損害賠償"}, llm=lambda p: STUB_ANSWER, conn=conn,
    )
    assert result.related_judgments, "stage3 should surface reference judgments"
    # Only §184 exists in this corpus -> AAA and BBB tie at 1 overlap and the
    # newer jid (BBB,115) leads; the 票據法-only judgment must never appear.
    jids = [r.jid for r in result.related_judgments]
    assert jids[0].startswith("BBB")
    assert any(j.startswith("AAA") for j in jids)
    assert not any(j.startswith("CCC") for j in jids)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
