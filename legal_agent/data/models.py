"""The in-memory statute row type (spec §1.4).

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
    hierarchy_level: str       # source_hierarchy.level (憲法 / 法律 / 命令 / 函釋 / 行政實務見解)
    source_url: str | None = None
