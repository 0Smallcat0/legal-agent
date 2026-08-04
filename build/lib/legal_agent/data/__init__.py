"""Data layer (spec §1) — the time-versioned, hierarchy-aware knowledge base.

Everything else stands on this layer: retrieval reads FROM it, the
anti-hallucination verifier validates AGAINST it. This is the only layer with
real, load-bearing content — the schema (schema.sql) plus the entry/ingest
tooling. The DB now holds a small human-verified 住宅噪音 corpus (11 statute
articles; 0 judgments).
"""
