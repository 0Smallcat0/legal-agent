"""The real-world outcome harness, and the guard that keeps its ruler honest.

The harness's whole claim is that its labels come from OUTSIDE this project, so
the one failure that would void it is a label the corpus can never match: it
scores a confident 0 and reads as a retrieval failure. `check_labels` turns that
into a loud error, and the first test here is the regression for the exact bug
that shipped in the first draft (民法 labelled as 中華民國民法).
"""
from __future__ import annotations

import json

import pytest

from legal_agent.evaluation.realworld import (
    BadLabelError,
    CaseOutcome,
    check_labels,
    run_realworld,
)
from tests.conftest import load_noise_fixture


def _corpus(tmp_path):
    from legal_agent.data.database import connect, init_db
    from legal_agent.data.seed import seed_source_hierarchy

    db = tmp_path / "t.db"
    init_db(db)
    conn = connect(db)
    seed_source_hierarchy(conn)   # 法律 must exist for the FK
    load_noise_fixture(conn)
    return conn


def _case_file(tmp_path, governing, initial="樓上鄰居半夜製造噪音吵到睡不著"):
    doc = {
        "version": "test",
        "sources": [{"id": "t", "title": "t", "url": "t", "label_source": "official"}],
        "cases": [{
            "id": "t-01",
            "source": "t",
            "domain": "住宅噪音",
            "label_source": "official",
            "initial_text": initial,
            "governing_statutes": governing,
            "real_outcome": "警方到場並開單。",
        }],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_label_naming_a_statute_the_corpus_lacks_aborts(tmp_path):
    """A misspelled statute_id must fail loudly, not score a fake miss."""
    conn = _corpus(tmp_path)
    path = _case_file(tmp_path, [{"statute_id": "中華民國民法", "article_no": "第430條"}])
    with pytest.raises(BadLabelError) as excinfo:
        run_realworld(path, conn=conn)
    assert "中華民國民法第430條" in str(excinfo.value)


def test_label_present_in_corpus_passes_the_guard(tmp_path):
    conn = _corpus(tmp_path)
    doc = json.loads(_case_file(
        tmp_path, [{"statute_id": "社會秩序維護法", "article_no": "第72條"}],
    ).read_text(encoding="utf-8"))
    check_labels(doc, conn)   # must not raise


def test_hit_when_the_governing_article_reaches_the_window(tmp_path):
    conn = _corpus(tmp_path)
    path = _case_file(tmp_path, [{"statute_id": "社會秩序維護法", "article_no": "第72條"}])
    report = run_realworld(path, conn=conn)
    case = report.cases[0]
    assert case.hit == ["社會秩序維護法第72條"]
    assert case.missed == []
    assert not case.silent_miss


def test_silent_miss_is_answered_anyway_with_nothing_relevant():
    """The shape that matters: no governing article retrieved, no refusal."""
    answered = CaseOutcome(
        id="x", domain="d", label_source="official",
        expected=["民法第430條"], hit=[], window=["民法第184條"],
        tier="normal", real_outcome="…",
    )
    refused = CaseOutcome(
        id="y", domain="d", label_source="official",
        expected=["民法第430條"], hit=[], window=[],
        tier="insufficient", real_outcome="…",
    )
    assert answered.silent_miss and not answered.refused
    assert refused.refused and not refused.silent_miss


def test_label_sources_are_reported_separately(tmp_path):
    """A derived label must never be pooled into the external number."""
    conn = _corpus(tmp_path)
    doc = json.loads(_case_file(
        tmp_path, [{"statute_id": "社會秩序維護法", "article_no": "第72條"}],
    ).read_text(encoding="utf-8"))
    doc["cases"].append(dict(doc["cases"][0], id="t-02", label_source="derived"))
    path = tmp_path / "two.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    report = run_realworld(path, conn=conn)
    assert [c.id for c in report.subset("official")] == ["t-01"]
    assert [c.id for c in report.subset("derived")] == ["t-02"]


# ── direction: the same guard, applied to the outcome fields ────────────────
# hit@k says the right article reached the window; it says nothing about which
# way the answer then argued. The direction number exists because one pass over
# eight ended rental disputes reasoned the wrong way round in four of them with
# `flagged_count` 0 in all eight.


def _coded(favours="asker", money="yes", **extra):
    return {"favours": favours, "money_to_asker": money, **extra}


def _direction_doc(outcome=None, label_source="official"):
    return {
        "cases": [{
            "id": "t-01",
            "label_source": label_source,
            "outcome_direction": outcome if outcome is not None else _coded(),
        }],
    }


def test_a_value_outside_the_vocabulary_aborts_the_whole_run():
    """Same rule as `check_labels`, same reason: an uncalibrated value renders
    as a confident count rather than as an error."""
    from legal_agent.evaluation.realworld import compare_directions

    doc = _direction_doc()
    with pytest.raises(BadLabelError) as excinfo:
        compare_directions(doc, {"t-01": _coded(favours="landlord")})
    assert "favours" in str(excinfo.value)
    assert "landlord" in str(excinfo.value)


def test_a_case_coded_on_one_side_only_aborts_instead_of_being_dropped():
    """Silently skipping it would move the denominator without anyone deciding
    that it should."""
    from legal_agent.evaluation.realworld import compare_directions

    with pytest.raises(BadLabelError) as excinfo:
        compare_directions(_direction_doc(), {})
    assert "只編了" in str(excinfo.value)

    with pytest.raises(BadLabelError):
        compare_directions({"cases": [{"id": "t-01", "label_source": "official"}]},
                           {"t-01": _coded()})


def test_coding_an_id_the_case_file_does_not_have_aborts():
    from legal_agent.evaluation.realworld import compare_directions

    with pytest.raises(BadLabelError) as excinfo:
        compare_directions(
            _direction_doc(), {"t-01": _coded(), "t-99": _coded()},
        )
    assert "t-99" in str(excinfo.value)


def test_opposed_is_only_an_actual_inversion():
    """「split」 against either side is a partial mismatch, not the shape that
    sends a person into a dispute pointed the wrong way."""
    from legal_agent.evaluation.realworld import compare_directions

    inverted = compare_directions(
        _direction_doc(_coded("other_party", "no")), {"t-01": _coded("asker", "yes")},
    )[0]
    assert inverted.opposed and not inverted.agrees

    partial = compare_directions(
        _direction_doc(_coded("split", "partial")), {"t-01": _coded("asker", "yes")},
    )[0]
    assert not partial.opposed and not partial.agrees


def test_unclear_on_either_side_is_not_counted_as_a_disagreement():
    """Forcing a coder to pick a side when the text does not commit is how a
    scheme starts manufacturing the number it was built to measure."""
    from legal_agent.evaluation.realworld import compare_directions, render_directions

    match = compare_directions(
        _direction_doc(_coded("unclear", "unclear")), {"t-01": _coded("asker", "yes")},
    )[0]
    assert not match.committed
    assert not match.opposed and not match.agrees
    assert "未表態" in render_directions([match])


def test_direction_counts_are_pooled_by_label_source():
    """A number is only as external as its weakest label, and that rule does
    not stop applying at the outcome field."""
    from legal_agent.evaluation.realworld import compare_directions, render_directions

    doc = _direction_doc()
    doc["cases"].append({
        "id": "t-02", "label_source": "derived",
        "outcome_direction": _coded("other_party", "no"),
    })
    matches = compare_directions(doc, {"t-01": _coded(), "t-02": _coded("asker", "yes")})
    text = render_directions(matches)

    assert "外部標註" in text and "本專案反推的標註" in text
    assert [m.label_source for m in matches] == ["official", "derived"]


def test_shipped_case_file_labels_all_exist_in_the_shipped_corpus():
    """The published number is only external if every label is resolvable."""
    from legal_agent import config
    from legal_agent.data.database import connect
    from legal_agent.evaluation.realworld import DEFAULT_CASES, load_document

    if not config.DB_PATH.exists():
        pytest.skip("no built corpus in this environment")
    conn = connect(config.DB_PATH)
    try:
        check_labels(load_document(DEFAULT_CASES), conn)   # must not raise
    finally:
        conn.close()
