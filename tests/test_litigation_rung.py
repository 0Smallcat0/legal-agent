"""Tests for the litigation rung: which court track and what 裁判費, computed from
民事訴訟法 only when the user typed the amount. Deterministic, no LLM, no database.

Run:  python -m pytest tests/test_litigation_rung.py -q
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

import pytest

from legal_agent import config
from legal_agent.data.bootstrap import PROPOSALS
from legal_agent.dialogue.solution import (
    LITIGATION_QUOTES,
    build_generic_ladder,
    build_solution_ladder,
    claim_amount,
    court_fee,
)


@lru_cache(maxsize=1)
def _corpus() -> dict[str, str]:
    """「民事訴訟法第436-8條」 -> its text, over every shipped proposal."""
    articles = {}
    for name in PROPOSALS:
        for row in json.loads((config.CORPUS_DIR / name).read_text(encoding="utf-8")):
            articles[row["statute_id"] + row["article_no"]] = row["content"]
    return articles


def _litigation(problem: str, domain: str | None = None, stance: str = "complainant"):
    ladder = build_generic_ladder({"problem": problem}, domain=domain, stance=stance)
    return next((r for r in ladder.rungs if r.key == "litigation"), None)


# ── the law it quotes is the corpus's, word for word ─────────────────────────
@pytest.mark.parametrize("ref, text", LITIGATION_QUOTES)
def test_every_quoted_line_is_verbatim_in_the_article_it_names(ref, text):
    assert text in _corpus()[ref]


@pytest.mark.parametrize("problem", ["他欠我八萬元", "他欠我二十萬", "他欠我兩百萬", "他不還錢"])
def test_every_article_the_rung_names_is_in_the_corpus(problem):
    for ref in _litigation(problem).legal_basis:
        assert ref in _corpus(), ref


def test_the_mediation_rungs_cite_the_mediation_statute_that_now_ships():
    ladders = [
        build_generic_ladder({"problem": "x"}, stance="complainant"),
        build_generic_ladder({"problem": "x"}, domain="traffic", stance="complainant"),
        build_solution_ladder({"problem": "樓上很吵"}, stance="complainant"),
    ]
    refs = [ref for lad in ladders for r in lad.rungs if "調解" in r.title for ref in r.legal_basis]
    assert "鄉鎮市調解條例第23條" in refs
    assert all(ref in _corpus() for ref in refs if ref.startswith("鄉鎮市調解條例"))


# ── reading the amount ───────────────────────────────────────────────────────
@pytest.mark.parametrize("said, low, high", [
    ("對方欠我八萬", 80_000, 80_000),
    ("修車花了三萬八", 38_000, 38_000),             # spoken: not 30,008
    ("押金一千八", 1_800, 1_800),
    ("估價1.5萬", 15_000, 15_000),
    ("總共3萬5千元", 35_000, 35_000),
    ("新台幣 30,000 元", 30_000, 30_000),
    ("NT$30,000", 30_000, 30_000),
    ("賠償陸拾萬元", 600_000, 600_000),
    ("修理費八萬多", 80_001, 89_999),
    ("貨款四十幾萬", 400_001, 499_999),
    ("貨款30多萬", 300_001, 399_999),                # like 三十多萬, not 30萬 and a bit
    ("訂金被沒收五萬", 50_000, 50_000),
])
def test_an_amount_the_user_typed_is_read(said, low, high):
    claim, asked = claim_amount({"problem": said})
    assert (claim.low, claim.high) == (low, high)
    assert asked == ()


@pytest.mark.parametrize("said", [
    "我哥把一塊農地租出去",      # 塊 is a piece here
    "少一塊都不行",
    "千萬不要簽",
    "住了三個月,5年前買的",       # no money unit at all
    "社區有三千人",
    "我月薪四萬五",               # a rate is not a claim
    "合約寫遺失最高賠三千",        # the other side's cap
    "店家只肯退我五千",            # the other side's offer
    "只能轉讓還要收手續費三千",     # the other side's charge
])
def test_no_amount_is_read_where_the_user_claimed_none(said):
    assert claim_amount({"problem": said}) == (None, ())


def test_a_figure_marked_as_the_claim_wins_over_the_others():
    claim, _ = claim_amount({"problem": "車價五十萬,他還欠我十五萬,我月薪四萬五"})
    assert (claim.low, claim.said) == (150_000, "十五萬")


def test_several_unmarked_amounts_are_asked_about_not_picked():
    claim, asked = claim_amount({"problem": "總價十二萬,訂金六萬,又多花了九萬"})
    assert claim is None
    assert asked == ("十二萬", "六萬", "九萬")


@pytest.mark.parametrize("said, quoted", [("領走大概兩百萬", "大概兩百萬"), ("加起來不到十萬", "不到十萬")])
def test_a_hedged_amount_is_quoted_back_with_its_hedge(said, quoted):
    assert claim_amount({"problem": said}) == (None, (quoted,))
    rung = _litigation(said)
    assert f"你提到的「{quoted}」不是確切的請求金額" in rung.next_step
    assert "裁判費 " not in rung.cost


# ── track thresholds (§436-8 十萬, §427 五十萬, §427 ¶2 item 十一) ─────────────
@pytest.mark.parametrize("amount, domain, track", [
    ("100,000", None, "小額程序"),
    ("100,001", None, "簡易程序"),
    ("500,000", None, "簡易程序"),
    ("500,001", None, "通常程序"),
    ("600,000", None, "通常程序"),
    ("600,000", "traffic", "簡易程序"),          # 道路交通事故: 簡易 at any amount
])
def test_the_track_follows_the_statutory_thresholds(amount, domain, track):
    assert _litigation(f"他欠我{amount}元", domain).title == f"民事訴訟(最後手段):{track}"


# ── the fee (§77-13 brackets, rounded up to 萬; §77-27 caps any surcharge) ───
@pytest.mark.parametrize("amount, fee", [
    (3_000, 1_000), (80_000, 1_000), (100_000, 1_000),
    (100_001, 1_100),                  # 「畸零之數不滿萬元者，以萬元計算」
    (105_000, 1_100), (180_000, 1_800), (1_000_000, 10_000),
    (1_500_000, 14_500), (2_000_000, 19_000),
    (10_000_000, 91_000),              # 1,000 + 90×100 + 900×90
])
def test_court_fee_follows_the_brackets(amount, fee):
    assert court_fee(amount) == fee


def test_the_page_states_fee_and_the_surcharge_ceiling():
    rung = _litigation("他欠我二十萬")
    assert rung.cost == "裁判費 2,000~3,000 元(律師費另計)"
    assert "「二十萬」(200,000 元)" in rung.what_it_is
    assert "簡易程序" in rung.title and "民事訴訟法第427條" in rung.legal_basis
    assert "聲請發支付命令" in rung.what_it_is and "民事訴訟法第508條" in rung.legal_basis


def test_a_range_is_priced_at_both_ends():
    rung = _litigation("修理費八萬多")
    assert rung.title.endswith("小額程序")
    assert rung.cost == "裁判費 1,000~1,500 元(律師費另計)"
    assert "80,001~89,999 元" in rung.what_it_is


def test_the_small_claim_question_the_probe_used_to_refuse_is_now_answered():
    # honesty_probe oos-15's facts, verbatim: 民事訴訟法 now ships.
    rung = _litigation("求償金額八萬元,想走小額訴訟")
    assert rung.title.endswith("小額程序")
    assert rung.cost == "裁判費 1,000~1,500 元(律師費另計)"
    assert "民事訴訟法第436-8條" in rung.legal_basis


# ── no amount, no number ─────────────────────────────────────────────────────
def test_no_amount_means_the_rung_asks_and_computes_nothing():
    rung = _litigation("他借錢不還,已經一年了")
    assert rung.title == "民事訴訟(最後手段)"
    assert "你還沒說要向對方請求多少錢" in rung.next_step
    assert not re.search(r"\d[\d,]* 元", rung.what_it_is + rung.cost)


def test_several_amounts_are_named_back_in_the_question():
    rung = _litigation("我訂了十二萬的布置,付了訂金六萬,另外找人又花了九萬")
    assert "「十二萬」「六萬」「九萬」" in rung.next_step
    assert "裁判費 " not in rung.cost


def test_the_party_being_claimed_against_gets_no_litigation_rung():
    assert _litigation("他說我欠他二十萬", stance="respondent") is None
