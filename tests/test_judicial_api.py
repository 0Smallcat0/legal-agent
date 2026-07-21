"""Offline tests for the 裁判書API harvester's pure parts: the JDoc adapter,
the substantive-civil filter, and the .env reader. No network.

Run:  python -m pytest tests/test_judicial_api.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.data.judicial_api import (  # noqa: E402
    _load_env,
    is_substantive_civil,
    jdoc_to_record,
)
from legal_agent.data.judicial_json import parse_judgment  # noqa: E402


def test_jdoc_to_record_flattens_nested_fulltext():
    jdoc = {
        "JID": "ILDV,115,重訴,7,20260707,1",
        "JYEAR": "115",
        "JCASE": "重訴",
        "JNO": "7",
        "JDATE": "20260707",
        "JTITLE": "塗銷所有權移轉登記等",
        "JFULLX": {"JFULLTYPE": "file", "JFULLCONTENT": "臺灣宜蘭地方法院民事判決…依民法第184條…", "JFULLPDF": "http://x"},
    }
    record = jdoc_to_record(jdoc)
    assert record["JID"] == "ILDV,115,重訴,7,20260707,1"
    assert record["JFULL"].startswith("臺灣宜蘭地方法院")

    # the record feeds straight into the existing importer
    row, warnings = parse_judgment(record, known_ids={"民法"})
    assert warnings == []
    assert row["jid"] == "ILDV,115,重訴,7,20260707,1"
    assert row["court"] == "ILDV"
    assert row["year"] == 115
    assert row["case_type"] == "塗銷所有權移轉登記等"
    assert '"民法"' in row["cited_articles"] and "第184條" in row["cited_articles"]


def test_jdoc_to_record_survives_missing_fullx():
    row = jdoc_to_record({"JID": "X,1,訴,1,20260101,1", "JYEAR": "1", "JTITLE": "t"})
    assert row["JFULL"] == ""


def test_substantive_civil_filter():
    assert is_substantive_civil("ILDV,115,重訴,7,20260707,1")       # 民事實質
    assert is_substantive_civil("ILEV,114,宜簡,406,20260617,2")     # 簡易判決
    assert not is_substantive_civil("ILDV,115,司促,2524,20260611,1")  # 司-prefixed
    assert not is_substantive_civil("ILDV,115,促,12,20260611,1")      # bare order
    assert not is_substantive_civil("CHDM,100,訴,1552,20130517,2")    # 刑事 M
    assert not is_substantive_civil("badjid")                         # malformed


def test_load_env_reads_key_values(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nJUDICIAL_USER=abc\nJUDICIAL_PASSWORD = p w \n", encoding="utf-8")
    values = _load_env(env)
    assert values["JUDICIAL_USER"] == "abc"
    assert values["JUDICIAL_PASSWORD"] == "p w"
    assert _load_env(tmp_path / "missing.env") == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
