"""The coverage veto: refuse what the corpus provably does not carry.

The absolute BM25 floor could not do this and the numbers say so — on the
35-case probe it refused 5 of 20 out-of-scope questions while falsely refusing
2 of 15 in-scope ones. These tests hold the two invariants that keep the table
from going stale the way the floor did.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from legal_agent.anti_hallucination.coverage import (
    ABSENT_DOMAINS,
    absent_domain,
)
from legal_agent.anti_hallucination.honesty import (
    INSUFFICIENT_TEXT,
    grade_honesty,
    insufficient_text,
)
from legal_agent.data.models import Statute

EVALS = Path(__file__).resolve().parents[1] / "evals"

_STUB = Statute(
    statute_id="民法", article_no="第1條",
    content="民事,法律所未規定者,依習慣;無習慣者,依法理。",
    effective_from="1929-05-23", effective_to=None,
    hierarchy_level="法律", source_url="",
)


def _corpus_statute_ids() -> set[str] | None:
    """The statutes actually shipped, or None in a bare checkout."""
    from legal_agent.config import DB_PATH

    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        return {r[0] for r in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    finally:
        conn.close()


def test_every_absent_statute_is_really_absent_from_the_corpus():
    """INVARIANT 1 — the table self-destructs when the corpus catches up.

    The insufficiency floor was calibrated on an 11-article corpus and left
    fixed while corpus v2 lifted every score; nothing failed, and out-of-scope
    questions sailed over it for a week. A row here naming a statute we DO carry
    is the same silent staleness, so it is a test failure instead.
    """
    ids = _corpus_statute_ids()
    if ids is None:
        pytest.skip("no corpus in this checkout")
    present = sorted(name for name in ABSENT_DOMAINS if name in ids)
    assert not present, (
        f"these statutes are IN the corpus and must not be vetoed: {present}"
    )


def _in_scope_queries() -> list[str]:
    sessions = json.loads((EVALS / "real_sessions.json").read_text(encoding="utf-8"))
    golden = json.loads((EVALS / "golden_v2.json").read_text(encoding="utf-8"))
    out = [s["query"] for s in sessions]
    out += [
        c["question"] + " " + " ".join(str(v) for v in c.get("facts", {}).values())
        for c in golden
        if c.get("expected_tier") != "insufficient"
    ]
    return out


def test_no_trigger_fires_on_an_in_scope_question():
    """INVARIANT 2 — the 0-false-positive standard, applied to refusals.

    A wrong refusal is worse than a hedge: the corpus HAD the answer and the
    reader was turned away. Triggers were pruned against these very queries, so
    this is a regression guard on that pruning, not independent evidence —
    「本票」「卡債」「健保」「非自願離職」「遺產稅」「農地」「停權」 each fired on a
    real in-scope session and were dropped or narrowed for it.
    """
    fired = [(q[:40], absent_domain(q)) for q in _in_scope_queries() if absent_domain(q)]
    assert not fired, f"veto fired on in-scope questions: {fired}"


def test_veto_beats_a_high_score():
    """The whole point: oos-09 本票裁定 topped BM25 at 503.5 — the highest score
    in the entire probe, in-scope cases included — and was answered from
    民法§473 消費借貸. Magnitude cannot see that 票據法 is missing."""
    query = "收到本票裁定但否認曾簽發該本票  想知道還能不能救濟"
    assert absent_domain(query) == ("票據法", "本票裁定")
    assert grade_honesty([_STUB], [503.5], query=query) == "insufficient"
    # …and without the veto the same score is 「normal」.
    assert grade_honesty([_STUB], [503.5]) == "normal"


def test_veto_only_ever_refuses():
    """It cannot promote a tier. A question with no absent-domain trigger is
    graded exactly as before — this keeps the change auditable to one direction.
    """
    for scores, expected in (
        ([503.5], "normal"), ([80.0], "marginal"), ([1.0], "insufficient"),
    ):
        assert grade_honesty([_STUB], scores) == expected
        assert grade_honesty([_STUB], scores, query="樓上小孩晚上一直跑跳") == expected


def test_refusal_names_the_missing_statute():
    """「資料庫沒有涵蓋」 is honest and useless. golden's expected_action for
    oos-10 asks the system to say WHICH law is missing and where to go."""
    text = insufficient_text("卡債八十萬無力清償,想聲請更生")
    assert "消費者債務清理條例" in text
    assert "法律扶助基金會" in text
    # No trigger -> the original fixed text, unchanged (two tests assert on it).
    assert insufficient_text("樓上小孩晚上一直跑跳") == INSUFFICIENT_TEXT
    assert insufficient_text("") == INSUFFICIENT_TEXT
