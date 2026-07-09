"""Unit tests for the ROC -> Gregorian ISO date converter (build step 2).

Covers the realistic input formats plus edge cases; malformed / ambiguous input
must raise RocDateError rather than guess.

Run:  python -m pytest tests/test_roc_date.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.roc_date import RocDateError, convert_roc_to_iso  # noqa: E402


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Chinese format, spaced / unspaced / single-digit month-day
        ("民國 110 年 01 月 20 日", "2021-01-20"),
        ("民國110年01月20日", "2021-01-20"),
        ("民國110年1月20日", "2021-01-20"),
        ("110年1月20日", "2021-01-20"),          # 民國 prefix optional
        ("  民國 110 年 01 月 20 日  ", "2021-01-20"),  # surrounding whitespace
        # Compact 7-digit (canonical government fixed-width form)
        ("1100120", "2021-01-20"),
        ("0380101", "1949-01-01"),                # zero-padded ROC year 38
        ("1141231", "2025-12-31"),
        # Separated forms, treated as ROC
        ("110/01/20", "2021-01-20"),
        ("110-1-20", "2021-01-20"),
        ("110.01.20", "2021-01-20"),
        # Boundaries & leap year
        ("民國 1 年 1 月 1 日", "1912-01-01"),     # ROC year 1 == 1912
        ("民國105年2月29日", "2016-02-29"),        # 2016 is a leap year
        # Full-width digits / punctuation from Chinese IMEs
        ("民國１１０年０１月２０日", "2021-01-20"),
        ("１１０／０１／２０", "2021-01-20"),
    ],
)
def test_valid_conversions(raw, expected):
    assert convert_roc_to_iso(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",                    # empty
        "   ",                 # whitespace only
        "abc",                 # junk
        "民國一一〇年",         # Chinese numerals not supported -> error (no guess)
        "2021-01-20",          # 4-digit (Gregorian) year -> rejected
        "2021/01/20",          # ditto with slashes
        "110120",              # 6 digits: ambiguous length
        "11001200",            # 8 digits: too long
        "民國110年13月01日",     # month out of range
        "民國110年00月10日",     # month zero
        "民國110年01月32日",     # day out of range
        "民國38年2月29日",       # 1949 is NOT a leap year
        "民國0年1月1日",         # ROC year 0 invalid
        "0000000",             # compact ROC year 0
        "民國110年1月",          # incomplete
        None,                  # non-string input
    ],
)
def test_invalid_inputs_raise(raw):
    with pytest.raises(RocDateError):
        convert_roc_to_iso(raw)


def test_error_is_valueerror_subclass():
    # Callers may catch either RocDateError or the broader ValueError.
    assert issubclass(RocDateError, ValueError)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
