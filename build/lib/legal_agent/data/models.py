"""In-memory record types mirroring the three data-layer tables (spec §1.4).

Plain data holders — no behavior. They exist so the rest of the system passes
typed rows around instead of raw dicts/tuples, and so the single most important
design decision — the statute *time slice* — is legible in Python, not only in
SQL. These are just the typed shapes rows take in Python; the table DDL lives in
schema.sql.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Statute:
    """One TIME SLICE of one article (spec §1.4).

    Identity is (statute_id, article_no, effective_from) — NOT just the article
    number. The same 民法第793條 can exist as several rows, one per amendment,
    each valid over the half-open interval [effective_from, effective_to).
    """
    statute_id: str            # 法規名稱, e.g. "民法"
    article_no: str            # 條號,     e.g. "第793條"
    content: str               # 條文內容 (verbatim Chinese)
    effective_from: str        # 生效日, ISO 8601 'YYYY-MM-DD'
    effective_to: str | None   # 失效日; None = currently in force
    hierarchy_level: str       # 憲法 / 法律 / 命令 / 函釋 (-> SourceHierarchy.level)
    source_url: str | None = None


@dataclass(frozen=True)
class Judgment:
    """A court judgment (spec §1.4).

    Parsed fields (issues, cited_articles, holding) are an NLP task per spec
    §1.3 trap #2 and stay None until the parsing step. cited_articles is a JSON
    array string — see schema.sql for the convention.
    """
    jid: str
    court: str | None = None
    year: int | None = None            # 年度 (ROC year, e.g. 112)
    case_type: str | None = None       # 案由
    issues: str | None = None          # 爭點
    cited_articles: str | None = None  # 引用法條 (JSON array)
    holding: str | None = None         # 裁判要旨
    full_text: str | None = None


@dataclass(frozen=True)
class SourceHierarchy:
    """Authority ranking of a source level (spec §1.4).

    Lower ``rank`` = higher authority (5 levels): 憲法(1) > 法律(2) > 命令(3) >
    函釋(4) > 行政實務見解(5). Used at reasoning time to decide which source wins.
    """
    level: str                    # 憲法 / 法律 / 命令 / 函釋 / 行政實務見解
    rank: int                     # lower = more authoritative
    description: str | None = None
