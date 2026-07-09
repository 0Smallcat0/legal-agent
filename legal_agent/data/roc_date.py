"""ROC (民國) -> Gregorian ISO 8601 date conversion (spec §1.4 date handling).

Taiwan statute dates on law.moj.gov.tw are written in 民國 (ROC) form, e.g.
"民國 110 年 01 月 20 日" or the compact "1100120". The `statutes` schema stores
ISO 8601 'YYYY-MM-DD'. Rule: Gregorian year = ROC year + 1911.

Accepted input shapes (ALL interpreted as ROC — this is an ROC-only converter):
  1. Chinese      : "民國 110 年 01 月 20 日", "110年1月20日"
                    (民國 optional, flexible whitespace, full-width digits OK)
  2. Compact 7-dig: "1100120"  (3-digit ROC year + 2-digit month + 2-digit day,
                    zero-padded — the canonical fixed-width government form)
  3. Separated    : "110/01/20", "110-1-20", "110.1.20"  (ROC year 1-3 digits)

Anything else — a 4-digit (Gregorian-looking) year, a 6/8-digit number, an
impossible calendar date (e.g. 民國38年2月29日), or junk — raises RocDateError.
The converter NEVER guesses: ambiguous or malformed input is an error.
"""
from __future__ import annotations

import re
from datetime import date

ROC_EPOCH_OFFSET = 1911  # Gregorian year = ROC year + 1911 (民國 1 年 = 1912)


class RocDateError(ValueError):
    """Raised when a string cannot be unambiguously parsed as a valid ROC date."""


# Normalize full-width digits/punctuation that Chinese input methods can emit.
_NORMALIZE = {ord("０") + i: ord("0") + i for i in range(10)}
_NORMALIZE.update({ord(k): ord(v) for k, v in {"／": "/", "－": "-", "．": ".", "　": " "}.items()})

_CHINESE_RE = re.compile(r"^\s*(?:民國)?\s*(\d{1,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*$")
_COMPACT_RE = re.compile(r"^\s*(\d{3})(\d{2})(\d{2})\s*$")          # exactly 7 digits
_SEPARATED_RE = re.compile(r"^\s*(\d{1,3})[/\-.](\d{1,2})[/\-.](\d{1,2})\s*$")


def convert_roc_to_iso(raw: str) -> str:
    """Convert an ROC date string to ISO 8601 'YYYY-MM-DD'.

    Raises:
        RocDateError: if ``raw`` is not a recognizable, valid ROC date.
    """
    if not isinstance(raw, str):
        raise RocDateError(f"預期字串,得到 {type(raw).__name__}")

    text = raw.translate(_NORMALIZE).strip()
    if not text:
        raise RocDateError("日期為空")

    for pattern in (_CHINESE_RE, _COMPACT_RE, _SEPARATED_RE):
        match = pattern.match(text)
        if match:
            roc_year, month, day = (int(group) for group in match.groups())
            break
    else:
        raise RocDateError(
            f"無法辨識的日期格式: {raw!r}"
            "(可接受:民國110年01月20日 / 1100120 / 110-01-20)"
        )

    if roc_year < 1:
        raise RocDateError(f"民國年須 >= 1(得到 {roc_year}): {raw!r}")

    gregorian_year = roc_year + ROC_EPOCH_OFFSET
    try:
        parsed = date(gregorian_year, month, day)
    except ValueError as exc:  # month/day out of range, or impossible date (e.g. 2/29 non-leap)
        raise RocDateError(f"無效的日期 {raw!r}: {exc}") from exc
    return parsed.isoformat()
