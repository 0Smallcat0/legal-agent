"""Tests for 主文 extraction and award reading (data/judgment_text.py).

Fixtures mirror REAL harvested shapes (2026-07-23): ideographic-space
headings, fixed-width wrapping, 大寫 numerals in small-claims judgments, and
主文 quoted inside body text. No network, no DB.

Run:  python -m pytest tests/test_judgment_text.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.judgment_text import (  # noqa: E402
    award_amounts,
    awards,
    format_awards,
    main_text,
)

# Shape copied from a real 簡易判決: padded heading, numbered items, and the
# three money kinds (award / 訴訟費用 / 假執行擔保).
SIMPLE = (
    "臺灣宜蘭地方法院民事簡易判決\n"
    "114年度宜簡字第406號\n"
    "上列當事人間請求損害賠償等事件，判決如下：\n"
    "　　主　　　文\n"
    "一、被告應連帶給付原告新臺幣20,000元。\n"
    "二、原告其餘之訴駁回。\n"
    "三、訴訟費用新臺幣1,500元，其中新臺幣416元由被告連帶負擔。\n"
    "四、本判決原告勝訴部分得假執行。但被告如以新臺幣20,000元\n"
    "    為原告預供擔保，得免為假執行。\n"
    "　　事實及理由\n"
    "壹、程序事項：略。\n"
)

# 小額判決: 大寫 numerals, and the body QUOTES 「判決書得僅記載主文」 — the
# heading anchor must not latch onto that quote.
SMALL_CLAIM = (
    "臺灣宜蘭地方法院民事小額判決\n"
    "115年度羅原小字第14號\n"
    "　　主　文\n"
    "被告應給付原告新臺幣貳萬伍仟玖佰肆拾伍元，及自民國一百一\n"
    "十四年十一月三十日起至清償日止，按週年利率百分之五計算之\n"
    "利息。\n"
    "原告其餘之訴駁回。\n"
    "訴訟費用新臺幣壹仟伍佰元由被告負擔五分之四。\n"
    "　　理由要領\n"
    "一、民事訴訟法第436條之18第1項規定「判決書得僅記載主文，就\n"
    "    當事人有爭執事項，於必要時得加記理由要領。」\n"
)

DISMISSED = (
    "　　主　文\n"
    "原告之訴及假執行之聲請均駁回。\n"
    "訴訟費用新臺幣3,000元由原告負擔。\n"
    "　　事實及理由\n"
)


def test_main_text_is_verbatim_and_bounded():
    block = main_text(SIMPLE)
    assert block is not None
    assert block.startswith("一、被告應連帶給付原告新臺幣20,000元。")
    assert "訴訟費用新臺幣1,500元" in block      # whole block, verbatim
    assert "程序事項" not in block                # stops at the next heading
    assert "判決如下" not in block                # starts after the heading


def test_heading_quoted_in_body_is_not_mistaken_for_the_heading():
    block = main_text(SMALL_CLAIM)
    assert block is not None
    assert block.startswith("被告應給付原告新臺幣貳萬伍仟玖佰肆拾伍元")
    assert "理由要領" not in block and "民事訴訟法第436條之18" not in block


def test_award_excludes_costs_and_security():
    assert award_amounts(main_text(SIMPLE)) == [20000]     # not 1,500 / not 416


def test_formal_numerals_and_wrapped_sentence():
    # 25,945 is written 貳萬伍仟玖佰肆拾伍 and its sentence wraps across lines.
    assert awards(SMALL_CLAIM) == (25945,)


def test_dismissal_yields_no_amount():
    assert awards(DISMISSED) == ()
    assert format_awards(awards(DISMISSED)) == ""


def test_missing_heading_returns_none():
    assert main_text("臺灣某地方法院民事裁定\n本件上訴駁回。\n") is None
    assert main_text("") is None and main_text(None) is None
    assert awards(None) == ()


def test_citation_reads_the_header_verbatim():
    # The API's jid is a database key; the 案號 in the judgment's own first two
    # lines is what a person can look up — and it says 判決 vs 裁定 for free.
    from legal_agent.data.judgment_text import citation

    text = ("臺灣宜蘭地方法院民事簡易判決\r\n114年度宜簡字第406號\r\n"
            "原      告  林某某\r\n")
    assert citation(text) == "臺灣宜蘭地方法院民事簡易判決 114年度宜簡字第406號"
    ruling = "臺灣宜蘭地方法院民事裁定\r\n114年度羅簡字第192號\r\n上  訴  人\r\n"
    assert citation(ruling) == "臺灣宜蘭地方法院民事裁定 114年度羅簡字第192號"
    # 調解筆錄 carries no such header — say nothing rather than guess.
    assert citation("調  解  筆  錄\r\n聲  請  人  周某\r\n") is None
    assert citation(None) is None and citation("") is None


def test_format_awards_reports_range_when_several():
    # A real case orders six defendants different sums — a single headline
    # number would misstate it.
    assert format_awards((20000,)) == "判賠 20,000 元"
    assert format_awards((165000, 1672000, 900000)) == "判賠 165,000–1,672,000 元(多筆)"
    assert format_awards(()) == ""


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
