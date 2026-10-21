"""The direction checks in RESULTS.md §7.1 that re-run without a model."""
from __future__ import annotations

from pathlib import Path

from legal_agent.evaluation.judge_direction import (
    direction_cues,
    labels,
    lexical_verdicts,
    parse_verdict,
)

ROOT = Path(__file__).resolve().parents[1]


def test_direction_cues_read_verdict_and_claim_and_skip_the_prompt_echo():
    cues = direction_cues(
        "1. 他可以向房東請求返還押金。\n2. 對方的說法站不站得住：對方的說法站不住腳。"
    )
    assert cues == {"verdict": ["asker"], "claim": ["asker"]}
    assert direction_cues("對方的說法站不站得住：要看情況。")["verdict"] == []
    assert direction_cues("1. 他無法主張減免。\n2. 對方的說法站得住腳。") == {
        "verdict": ["other_party"], "claim": ["other_party"],
    }


def test_lexical_check_matches_the_published_counts():
    """RESULTS.md §7.1 / README: contradiction 2/5 caught, 1/11 false, 6 of 24;
    with 「no verdict」 4/5, 7/11, 17 of 24."""
    rows = lexical_verdicts(ROOT / "evals/realworld_answers_run1.json")
    truth = labels(ROOT / "evals/realworld_v1.json",
                   ROOT / "evals/realworld_answer_coding_run1.json")
    assert len(rows) == 24

    def counts(flag):
        wrong = [i for i, t in truth.items() if t["truth"] == "wrong"]
        right = [i for i, t in truth.items() if t["truth"] == "right"]
        return (sum(flag(rows[i]) for i in wrong), len(wrong),
                sum(flag(rows[i]) for i in right), len(right),
                sum(flag(r) for r in rows.values()))

    assert counts(lambda r: r["contradiction"]) == (2, 5, 1, 11, 6)
    assert counts(lambda r: r["contradiction"] or r["no_verdict"]) == (4, 5, 7, 11, 17)


def test_unreadable_judge_output_is_none_not_unflagged():
    assert parse_verdict("plain", "理由……") == (None, None)
    assert parse_verdict("plain", "判定：站不住") == (True, None)
    assert parse_verdict("prometheus", "Feedback [RESULT] 5") == (False, 5)
    assert parse_verdict("judgelm", "2\nexplanation") == (True, 2)
