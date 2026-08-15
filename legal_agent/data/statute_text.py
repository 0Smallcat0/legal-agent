"""Marking the proviso inside an article — a verbatim slice, never a reading.

The 2026-08-15 live run (`journal/`) produced a second finding after the ladder:
**retrieved, quoted, and not read.** All three governing articles reached the
page verbatim — 社維法§72 with 「不聽禁止者」, 民法§793 with its full proviso — and
not one of them was used as a condition the other side must still meet. In one
run the two facts that go toward 不聽禁止 (the committee came, the police came)
were read as evidence that 對方的說法站得住.

Retrieval did not fail there. **Presentation did, and presentation is code's
job — no model is needed to point at a clause the statute has already delimited
for itself.**

The line this module refuses to cross is the one `judgment_text.py` drew: 主文
can be sliced out verbatim because it is *structurally* delimited, while 爭點
and 裁判要旨 stay NULL because summarising them is NLP. 「但…不在此限」 carries its
own delimiters at both ends, so it belongs to the first kind. Nothing here reads
the clause, decides whether it applies, or rewrites it.

Measured on the shipping corpus (2,922 articles in force, 2026-08-15):

| pattern | articles |
|---|---|
| 不在此限 | 223 |
| 但 | 533 |
| 但 without 不在此限 | 312 |
| 不在此限 without 但 | 2 |
| 者 | 2,066 (71%) |

**Precision is why the pattern is the pair and not either half.** The two
articles carrying 不在此限 without 但 were read by eye: 刑法§266 III
(「前二項以供人暫時娛樂之物為賭者,不在此限」) and 強制汽車責任保險法§23
(「惟停駛中車輛辦理過戶不在此限」). Both are real provisos; both are MISSED here
rather than mis-marked, because neither is introduced by 但. That is the failure
direction this module wants.

**The recall is low and that is accepted, for `award_amounts`' reason: silence
beats a wrong number.** 312 articles carry 但 with some other terminator — 93 of
them 不得, 33 者,不, 8 不適用之 — and none of them are marked. Missing one costs
the reader nothing he did not already have: the verbatim article is on the page
either way. Marking the wrong span puts emphasis on the wrong clause at the exact
moment he is deciding what the other side must prove.

**「…者」 was measured and rejected**: 2,066 articles, 71% of the corpus in force.
That is the register of Chinese statutory drafting, not a marker. Recorded in
`evals/RESULTS.md` under "Measured, then NOT shipped".
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
