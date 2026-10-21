"""Data layer (spec §1) — the time-versioned, hierarchy-aware knowledge base.

Retrieval reads FROM it; the verifier validates AGAINST it. Holds the schema
(schema.sql), the ingest tooling for statutes (moj_xml -> human-reviewed
proposal -> source_ingest) and reference judgments (judicial_api/judicial_json),
and bootstrap, which builds the database from the corpus shipped in the package.
"""
