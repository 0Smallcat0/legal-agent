"""Who won, read one 主文 sentence at a time.

The eight cases below are the regression seeds: every one is a judgment the
obvious whole-block ruler (「之訴駁回」 anywhere in the 主文) gets WRONG, and
every one of its errors runs the same way — a win labelled a loss. For a block
whose job is to tell a reader that somebody lost, that is the worst available
direction of error, which is why they are pinned against the shipped corpus
rather than against hand-typed fixtures.

Run:  python -m pytest tests/test_judgment_outcome.py -q
"""
from __future__ import annotations

import pytest

from legal_agent.data.bootstrap import ensure_corpus
from legal_agent.data.database import connect
from legal_agent.data.judgment_text import Outcome, main_text, outcome

# jid prefix -> (verdict, mover, why the whole-block ruler misreads it)
SEEDS: dict[str, tuple[str, str, str]] = {
    "MLDV,114,家繼訴,56": (
        "partly", "原告",
        "「原告先位之訴駁回」 then 確認特留分存在 and 命被告塗銷 — the alternative claim won",
    ),
    "TPHV,114,上,908": (
        "granted", "上訴人",
        "「原判決廢棄。被上訴人在第一審之訴駁回」 — the appellant won outright",
    ),
    "TPHV,114,上易,270": (
        "granted", "上訴人",
        "same shape, second court",
    ),
    "IPCV,115,商暫,4": (
        "partly", "聲請人",
        "two injunctions granted; only 「緊急處置之聲請駁回」 refused",
    ),
    "IPCV,115,商暫,5": (
        "partly", "聲請人",
        "same 主文 filed under the other case number",
    ),
    "TCDV,114,簡上,160": (
        "partly", "上訴人",
        "廢棄 + 「其餘上訴駁回」 — the appellate wording a 「其餘之訴駁回」 test never sees",
    ),
    "SCDV,114,再易,12": (
        "denied_procedurally", "再審原告",
        "「再審之訴駁回」 is procedural and says nothing about the underlying case",
    ),
    "CTDV,115,簡上,4": (
        "partly", "上訴人",
        "amount sits in the 廢棄 clause; 「其餘上訴駁回」 again",
    ),
}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    path = tmp_path_factory.mktemp("outcome") / "j.db"
    ensure_corpus(str(path))
    conn = connect(path)
    yield conn
    conn.close()


def _full_text(conn, prefix: str) -> str:
    row = conn.execute(
        "SELECT full_text FROM judgments WHERE jid LIKE ?", (prefix + ",%",)
    ).fetchone()
    assert row is not None, f"{prefix} is not in the shipped corpus any more"
    return row[0]


@pytest.mark.parametrize("prefix", sorted(SEEDS))
def test_the_whole_block_rulers_known_errors_are_read_correctly(corpus, prefix):
    verdict, mover, why = SEEDS[prefix]
    text = _full_text(corpus, prefix)

    result = outcome(text)

    assert result.verdict == verdict, f"{prefix}: {why}"
    assert result.mover == mover


@pytest.mark.parametrize("prefix", sorted(SEEDS))
def test_every_seed_is_one_the_whole_block_ruler_actually_gets_wrong(corpus, prefix):
    """A regression case the old ruler already passed would prove nothing. Each
    seed must genuinely trip a whole-block 「駁回」 test.

    Bare 「駁回」 rather than 「之訴駁回」 on purpose: the two IPCV injunctions read
    「緊急處置之聲請駁回」, so the narrower string misses them and the broader one
    calls them losses. Both are whole-block tests and both are wrong; the seed
    set has to sit inside the ruler that catches the most, or it would be
    quietly grading the weaker one."""
    block = main_text(_full_text(corpus, prefix))

    assert "駁回" in block, f"{prefix} is not a case the whole-block ruler misreads"
    assert SEEDS[prefix][0] != "denied"


def test_the_outcome_always_names_the_party_it_is_about(corpus):
    """An appellate 主文 is relative to position: the same sentence is a win for
    one side and a loss for the other, so a verdict with no party attached is
    misleading on its own."""
    for prefix, (_verdict, mover, _why) in SEEDS.items():
        described = outcome(_full_text(corpus, prefix)).describe()
        assert mover in described, f"{prefix}: {described}"

    assert outcome(None).describe() == "此判決主文無法判讀勝敗"
    assert Outcome("unreadable").mover == ""


def test_a_bare_win_and_a_bare_loss_still_read_the_obvious_way():
    """The failure shapes get the attention, but the common cases must not
    regress while the rules chase them."""
    plain_win = "主文\r\n被告應給付原告新臺幣100,000元。\r\n訴訟費用由被告負擔。\r\n事實及理由"
    plain_loss = "主文\r\n原告之訴駁回。\r\n訴訟費用由原告負擔。\r\n事實及理由"

    assert outcome(plain_win).verdict == "granted"
    assert outcome(plain_loss).verdict == "denied"
    assert outcome(plain_loss).describe() == "此判決主文駁回原告的請求"


def test_an_order_to_pay_points_the_way_the_obligor_points():
    """On appeal the roles swap, so 「被告應給付原告」 and 「上訴人應給付被上訴人」
    are the same grammar pointing opposite ways."""
    against_respondent = "主文\r\n被告應給付原告新臺幣50,000元。\r\n事實及理由"
    against_mover = "主文\r\n上訴人應給付被上訴人新臺幣50,000元。\r\n事實及理由"

    assert outcome(against_respondent).verdict == "granted"
    assert outcome(against_mover).verdict != "granted"


def test_an_order_to_cure_a_defect_decides_nothing_either_way():
    """「逾期未補正，即駁回原告之訴」 carries an 應-order AND a 駁回, and was landing
    in `granted` or in `denied` depending on which clause won. The dismissal is
    conditional and in the future; the 裁定 decides nothing."""
    cure = (
        "主文\r\n原告應於本裁定送達後十日內補正如附表所示之事項，"
        "逾期未補正，即駁回原告之訴。\r\n事實及理由"
    )

    assert outcome(cure).verdict == "unreadable"


def test_costs_never_decide_the_case():
    """Cost sentences carry 駁回 and 負擔 constantly and settle nothing."""
    costs_only = "主文\r\n訴訟費用由原告負擔。\r\n事實及理由"

    assert outcome(costs_only).verdict == "unreadable"
