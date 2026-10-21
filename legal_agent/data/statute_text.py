"""Marking the proviso inside an article — a verbatim slice, never a reading.

Retrieved provisos (民法§793, 社維法§72 「不聽禁止者」) reached the page and were
not read as conditions the other side must still meet; pointing at a clause
the statute already delimits is code's job. 「但…不在此限」 is delimited at both
ends, so it can be sliced like 主文 (see judgment_text.py). Nothing here
decides whether the clause applies or rewrites it.

Only the PAIR is marked, for precision: 不在此限 without 但 (2 articles) is
missed, not mis-marked. Recall is low by choice — of 533 articles with 但, 312
end otherwise (93 不得, 33 者,不, 8 不適用之) and are not marked; the verbatim
article is on the page either way, and a wrong span misleads. 「…者」 was
rejected (RESULTS.md §9).
"""
from __future__ import annotations

import re

_PROVISO_END = "不在此限"
_PROVISO_START = "但"
_SENTENCE_BREAKS = "。\n"


def proviso_spans(content: str) -> list[tuple[int, int]]:
    """`(start, end)` for every 但…不在此限 clause, in order.

    A span is taken only when the 但 and its 不在此限 sit in the SAME sentence —
    an article whose earlier paragraph happens to contain 但 must not swallow
    everything up to a proviso three sentences later.
    """
    text = content or ""
    spans: list[tuple[int, int]] = []
    for match in re.finditer(_PROVISO_END, text):
        start = text.rfind(_PROVISO_START, 0, match.start())
        if start == -1:
            continue
        between = text[start:match.start()]
        if any(brk in between for brk in _SENTENCE_BREAKS):
            continue
        if spans and start < spans[-1][1]:      # overlapping — keep the first
            continue
        spans.append((start, match.end()))
    return spans


def mark_provisos(content: str, prefix: str, suffix: str,
                  escape=lambda s: s) -> str:
    """`content` with each proviso wrapped in `prefix`/`suffix`, verbatim.

    `escape` is applied to the text, never to the markers, so an HTML caller
    passes `html.escape` and gets a correctly-escaped string with live tags.
    """
    text = content or ""
    spans = proviso_spans(text)
    if not spans:
        return escape(text)
    out, cursor = [], 0
    for start, end in spans:
        out.append(escape(text[cursor:start]))
        out.append(prefix + escape(text[start:end]) + suffix)
        cursor = end
    out.append(escape(text[cursor:]))
    return "".join(out)
