"""The two family maps are the whole instrument — pin what they must decide.

`judgment_relevance` grades the reference-judgment layer by comparing families
derived from BOTH sides. Neither side is hand-labelled, which is the point, so
the only thing that can quietly rot is a map entry. These fix the decisions the
number depends on, including the one that was wrong first time round.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.evaluation.judgment_relevance import (  # noqa: E402
    _CROSS_CUTTING,
    case_type_family,
    is_uninformative,
    statute_family,
)


@pytest.mark.parametrize("ref,family", [
    ("民法第432條", "租賃"),          # 債編 租賃節
    ("民法第1114條", "扶養"),         # 親屬編 扶養章
    ("民法第184條", "侵權"),
    ("民法第1151條", "繼承"),
    ("民法第818條", "共有"),
    ("民法第1055-1條", "婚姻"),       # 離婚節 — the 之一 suffix must not break parsing
    ("民法第14條", "監護"),           # 總則 single, not the general part
    ("勞動基準法第11條", "勞動"),
    ("家庭暴力防治法第14條", "家暴"),
    ("公寓大廈管理條例第10條", "住戶"),
    ("租賃住宅市場發展及管理條例第7條", "租賃"),
])
def test_statute_family_follows_the_code_structure(ref, family):
    assert statute_family(ref) == family


def test_cross_cutting_articles_are_not_a_dispute_family():
    """§273 (連帶債務) is a rule that applies inside a loan, a sale or a repair
    job alike. Grading a session by it scored 清償借款 — the right case — as a
    miss, which is why these are excluded from scoring on both sides."""
    assert statute_family("民法第273條") in _CROSS_CUTTING
    assert statute_family("民法第153條") in _CROSS_CUTTING
    assert statute_family("民法第129條") in _CROSS_CUTTING


def test_the_earliest_keyword_in_the_case_type_wins():
    """A court writes the claim it decided first and appends the ancillary ones
    after 「等(含…)」. Table order alone graded this 扶養; it is a 婚姻 case that
    also settled support."""
    assert case_type_family("離婚等(含未成年子女親權酌定、扶養費等)") == "婚姻"
    assert case_type_family("分割遺產") == "繼承"          # not 共有, despite 分割
    assert case_type_family("返還代墊扶養費用") == "扶養"


@pytest.mark.parametrize("case_type,uninformative", [
    ("損害賠償", True),
    ("損害賠償等", True),
    ("請求損害賠償", True),
    ("損害賠償(交通)", False),         # names the dispute: a road accident
    ("損害賠償（交通）", False),        # the corpus uses both paren styles
    ("侵權行為損害賠償", False),       # keyword hits before the fallback
    ("遷讓房屋等", False),
])
def test_generic_case_types_are_not_scored_either_way(case_type, uninformative):
    assert is_uninformative(case_type) is uninformative


def test_the_harness_runs_end_to_end(tmp_path):
    """Integration on a SLICE, not all 168: retrieval is the slow part and the
    published figure is the harness's job, not the suite's. Twelve sessions
    exercise every branch and keep the run inside the suite's budget."""
    import json

    from legal_agent.config import DB_PATH

    if not Path(DB_PATH).exists():
        pytest.skip("no corpus in this checkout")
    from legal_agent.evaluation.judgment_relevance import run_judgment_relevance

    sessions = json.loads(
        (ROOT / "evals" / "real_sessions.json").read_text(encoding="utf-8"))[:12]
    slice_path = tmp_path / "slice.json"
    slice_path.write_text(json.dumps(sessions, ensure_ascii=False), encoding="utf-8")

    report = run_judgment_relevance(slice_path)
    assert len(report.cases) == len(sessions)
    assert {c.verdict for c in report.cases} <= {
        "match", "mismatch", "unlabelled", "none"}
    assert report.scorable == sum(
        1 for c in report.cases if c.verdict in {"match", "mismatch"})
    assert 0.0 <= report.rate <= 1.0
    # A session with no judgment must not be scored as a miss.
    assert all(c.verdict == "none" for c in report.cases if not c.n_shown)
