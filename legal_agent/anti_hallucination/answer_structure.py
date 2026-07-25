"""Gate 4 — separate 法律明文 / 實務見解 / 研判 (spec §2.5, three-section form).

A legal answer now has THREE labelled parts, sorted by the source's 位階:
    「法律明文」 — 憲法 / 法律 / 命令 (rank <=3): verifiable black-letter law.
    「實務見解」 — 函釋 / 行政實務見解 (rank 4-5): must open with a disclaimer that
                   this is NOT statutory text, only for reference.
    「分析研判」 — model inference, for-reference-only.

split_sections parses all three; a missing section is signalled (None) so the
caller can flag it — it never crashes. The system prompt (dialogue/stage3)
instructs the model to emit all three headings.
"""
from __future__ import annotations

import re

LAW_HEADING = "法律明文"
PRACTICE_HEADING = "實務見解"
ANALYSIS_HEADING = "分析研判"

# The 實務見解 section MUST carry this phrase (spec: 非法律明文). It also lets us tell
# the 法律明文 HEADING apart from the disclaimer's "非法律明文".
PRACTICE_DISCLAIMER = "非法律明文"

_HEADINGS = (LAW_HEADING, PRACTICE_HEADING, ANALYSIS_HEADING)
# Match the 法律明文 heading but NOT the "非法律明文" disclaimer inside 實務見解.
_LAW_HEADING_RE = re.compile(r"(?<!非)" + LAW_HEADING)


def _find(heading: str, text: str) -> int:
    if heading == LAW_HEADING:
        m = _LAW_HEADING_RE.search(text)
        return m.start() if m else -1
    return text.find(heading)


# Models emit the headings as markdown (「**法律明文**」). Splitting on the bare
# heading therefore leaves the opening 「**」 dangling at the END of the previous
# section and the closing 「**」 stuck to the heading — the user reads a stray
# 「**」 on its own line between every section. Strip the decoration; keep the
# text itself byte-for-byte.
_DECOR = " \t*#_\r\n:："


def _tidy(block: str, heading: str) -> str:
    body = block[len(heading):] if block.startswith(heading) else block
    body = body.strip(_DECOR)
    return f"{heading}\n{body}" if body else heading


# A section whose body is just 「(無)」 says something true: there was nothing to
# report. Callers use this to avoid warning about a missing disclaimer on a
# section that has no content to disclaim.
_EMPTY_BODIES = {"", "無", "(無)", "（無）", "N/A", "n/a"}


def is_empty_section(section: str | None, heading: str) -> bool:
    """True when `section` carries the heading but no substantive body."""
    if section is None:
        return True
    body = section[len(heading):] if section.startswith(heading) else section
    return body.strip(_DECOR + "。,，、") in _EMPTY_BODIES


def split_sections(answer: str) -> tuple[str | None, str | None, str | None]:
    """Split `answer` into (法律明文, 實務見解, 分析研判) text.

    Any heading that is absent comes back as None (a flag for the caller). Never
    raises. Each present section spans from its heading to the next present
    heading (in document order).
    """
    text = answer or ""
    present = [(h, _find(h, text)) for h in _HEADINGS]
    present = [(h, pos) for h, pos in present if pos != -1]
    present.sort(key=lambda hp: hp[1])

    section: dict[str, str] = {}
    for i, (heading, start) in enumerate(present):
        end = present[i + 1][1] if i + 1 < len(present) else len(text)
        section[heading] = _tidy(text[start:end].strip(), heading)

    return (
        section.get(LAW_HEADING),
        section.get(PRACTICE_HEADING),
        section.get(ANALYSIS_HEADING),
    )
