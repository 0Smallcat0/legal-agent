"""The pocket card claims every quoted line is verbatim. This is that claim,
enforced — the same rule `test_every_statutory_term_appears_verbatim_in_the_corpus`
holds over the vocabulary table.

Run:  python -m pytest tests/test_respondent_card.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import legal_agent

ROOT = Path(__file__).resolve().parents[1]

CARD = ROOT / "docs" / "respondent_card.md"


def _quoted_lines() -> list[str]:
    """Every blockquote line, with this page's own bold markers and the
    paragraph-number prefix removed — those are the page's, not the statute's."""
    lines = []
    for raw in CARD.read_text(encoding="utf-8").splitlines():
        if not raw.startswith(">"):
            continue
        text = raw.lstrip(">").strip().replace("**", "")
        text = re.sub(r"^（第[一二三四五六七八九十]+項）", "", text)
        if text:
            lines.append(text)
    return lines


def test_every_quoted_line_is_verbatim_in_the_corpus():
    lines = _quoted_lines()
    assert len(lines) >= 8, "the card lost its quotes"
    conn = legal_agent.open_corpus()
    try:
        for line in lines:
            hit = conn.execute(
                "SELECT 1 FROM statutes WHERE effective_to IS NULL AND content LIKE ? LIMIT 1",
                ("%" + line + "%",),
            ).fetchone()
            assert hit is not None, f"not verbatim in the corpus: {line}"
    finally:
        conn.close()


def test_the_card_carries_no_action_ladder_and_no_letter():
    """Measured 2026-08-15: handing a respondent the complainant's steps tells
    him to act against the person complaining about him."""
    text = CARD.read_text(encoding="utf-8")
    body = text.split("## 3. 這頁刻意沒有的東西")[0]   # that section NAMES them
    for banned in ("110", "存證信函範本", "聲請調解", "提起民事訴訟"):
        assert banned not in body, banned


def test_the_card_states_the_three_limits_of_the_police_principle():
    text = CARD.read_text(encoding="utf-8")
    assert "不是法律" in text
    assert "只適用該局轄區" in text
    assert "唯一一份同類文件" in text


def test_the_card_refuses_the_you_are_safe_verdict():
    assert "不會告訴你「你沒事」" in CARD.read_text(encoding="utf-8")
