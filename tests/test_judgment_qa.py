"""The judgment citation acceptance set (evals/judgment_qa_v1.json)."""
from __future__ import annotations

import json
from pathlib import Path

from legal_agent.evaluation.judgment_coverage import serves_family
from legal_agent.evaluation.judgment_qa import (
    DEFAULT_FILE,
    Case,
    QAReport,
    expected_for,
    load,
    run_judgment_qa,
)

ROOT = Path(__file__).resolve().parents[1]


def test_the_set_has_at_least_thirty_questions_with_frozen_expectations():
    questions = load(DEFAULT_FILE)["questions"]
    assert len(questions) >= 30
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        assert q["question"] and q["expected_statutes"]
        assert "expected_judgments" in q, q["id"]


def test_expected_judgments_are_in_the_shipped_corpus_and_serve_the_question(shipped_conn):
    """Every expected jid ships, serves the question's family and cites one of
    its articles — the rule `expected_for` froze them by."""
    shipped = {r["jid"]: r for r in json.loads(
        (ROOT / "legal_agent" / "corpus" / "judgments_v1.json").read_text(encoding="utf-8"))}
    for q in load(DEFAULT_FILE)["questions"]:
        for e in q["expected_judgments"]:
            row = shipped[e["jid"]]
            assert serves_family(row["case_type"], row["cited_articles"]) == q["family"]
            refs = {f"{c['statute_id']}{c['article_no']}" for c in row["cited_articles"]}
            assert refs & set(q["expected_statutes"]), (q["id"], e["jid"])


def test_frozen_lists_are_what_the_rule_derives_from_the_corpus(shipped_conn):
    """Nobody edited a list by hand: re-deriving gives the same jids. A shipped
    backfill that adds judgments a question should cite fails here, and the
    fix is a new question file version, not an edit."""
    for q in load(DEFAULT_FILE)["questions"]:
        derived = [e["jid"] for e in expected_for(shipped_conn, q["family"], q["expected_statutes"])]
        assert derived == [e["jid"] for e in q["expected_judgments"]], q["id"]


def test_case_scoring():
    hit = Case("a", "寄託", {"J1"}, shown=[("J1", "返還寄託物"), ("J2", "返還借用物")], in_window=True)
    assert hit.correct == 1 and hit.hit and not hit.off_topic and hit.cause is None

    off = Case("b", "寄託", {"J1"}, shown=[("J3", "清償借款")], in_window=True)
    assert off.off_topic and off.cause == "引錯家族"

    crowded = Case("c", "寄託", {"J1"}, shown=[("J4", "返還寄託物")], in_window=True)
    assert not crowded.off_topic and crowded.cause == "被擠出前三"

    assert Case("d", "寄託", {"J1"}, in_window=False).cause == "檢索漏條文"
    assert Case("e", "寄託", set(), in_window=True).cause == "語料無應引判決"
    assert not Case("f", "寄託", {"J1"}).off_topic          # nothing shown is not off-topic

    report = QAReport("focus", [hit, off, crowded])
    assert (report.correct, report.shown, report.hits, report.off_topic) == (1, 4, 1, 1)
    assert report.causes() == {"引錯家族": 1, "被擠出前三": 1}


def test_the_harness_runs_end_to_end(tmp_path, shipped_conn):
    data = load(DEFAULT_FILE)
    data["questions"] = data["questions"][:4]
    path = tmp_path / "slice.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for mode in ("focus", "window"):
        report = run_judgment_qa(path, mode=mode, conn=shipped_conn)
        assert len(report.cases) == 4
        assert report.correct <= report.shown <= 12
        assert "引用正確率" in report.render()
