-- ============================================================================
-- Taiwan Legal Agent — Data Layer schema (spec §1.4)
--
-- Engine   : SQLite (single-user personal build; rationale in README.md).
-- Encoding : all legal text is verbatim Chinese — store as UTF-8 TEXT.
-- Dates    : ISO 8601 'YYYY-MM-DD' TEXT. SQLite has no native DATE type, and
--            ISO 8601 strings sort lexicographically == chronologically, which
--            is EXACTLY what the statute time-slice range queries below rely on.
--            NOTE: the official source (全國法規資料庫) gives 民國/ROC dates
--            (生效日期). Converting ROC -> Gregorian happens at entry time
--            (legal_agent/data/roc_date.py) so the comparisons below Just Work.
--            This file only defines structure — it inserts no rows.
--
-- Idempotent : CREATE TABLE IF NOT EXISTS — safe to run on every startup.
-- Order      : source_hierarchy is created BEFORE statutes, because
--              statutes.hierarchy_level references it (foreign key).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- source_hierarchy — authority ranking of source levels (spec §1.4)
--
-- Ranks each source so that when a 法律 and a 函釋 conflict, the reasoning layer
-- knows which wins. Convention: LOWER rank = HIGHER authority.
--     憲法(1) > 法律(2) > 命令(3) > 函釋(4) > 行政實務見解(5)  -> "which wins" = MIN(rank)
--
-- Seeded by legal_agent/data/seed.py (NOT here — this file only defines
-- structure). Five levels are seeded; their names are the controlled vocabulary
-- the statutes.hierarchy_level foreign key validates against.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_hierarchy (
    level        TEXT PRIMARY KEY,            -- 憲法 / 法律 / 命令 / 函釋
    rank         INTEGER NOT NULL UNIQUE,     -- lower = more authoritative
    description  TEXT
);


-- ----------------------------------------------------------------------------
-- statutes — TIME-SLICED  (spec §1.4: "the #1 thing most first builds get wrong")
--
-- The primary key is a TIME SLICE, not just an article number:
--
--         PRIMARY KEY (statute_id, article_no, effective_from)
--
-- The same article (e.g. 民法第793條) appears as SEVERAL rows — one per
-- amendment — each valid over the half-open interval
--
--         [effective_from, effective_to)        (effective_to IS NULL = in force now)
--
-- This is what lets the system answer "for a dispute that happened in 2023,
-- which version applied?" instead of blindly citing today's (possibly amended,
-- possibly repealed) text. Losing this is how legal AIs end up citing repealed
-- articles.
--
-- Canonical point-in-time lookup (documented here; IMPLEMENTED in
-- legal_agent/retrieval/retriever.py):
--
--     SELECT * FROM statutes
--     WHERE statute_id     = :statute_id
--       AND article_no     = :article_no
--       AND effective_from <= :as_of_date
--       AND (effective_to IS NULL OR :as_of_date < effective_to)
--     ORDER BY effective_from DESC
--     LIMIT 1;
--
-- The PRIMARY KEY index also covers "give me every version of this article"
-- (its (statute_id, article_no) prefix), so no extra index is needed for that.
--
-- IMPORTANT SQLite gotcha: unlike other databases, SQLite lets NULLs sit in a
-- PRIMARY KEY column unless it is declared NOT NULL. All three key columns are
-- therefore explicitly NOT NULL — this is a deliberate correctness guard, not
-- boilerplate.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS statutes (
    statute_id       TEXT NOT NULL,   -- 法規名稱, e.g. "民法"
    article_no       TEXT NOT NULL,   -- 條號,     e.g. "第793條"
    content          TEXT NOT NULL,   -- 條文內容 (verbatim Chinese)
    effective_from   TEXT NOT NULL,   -- 生效日, ISO 8601 'YYYY-MM-DD'
    effective_to     TEXT,            -- 失效日; NULL = currently in force
    hierarchy_level  TEXT NOT NULL,   -- 憲法 / 法律 / 命令 / 函釋
    source_url       TEXT,            -- provenance (law.moj.gov.tw article URL)

    PRIMARY KEY (statute_id, article_no, effective_from),
    FOREIGN KEY (hierarchy_level) REFERENCES source_hierarchy(level)
);


-- ----------------------------------------------------------------------------
-- judgments (spec §1.4)
--
-- Court data is semi-structured and badly formatted (spec §1.3 trap #2), so the
-- parsed fields (issues / cited_articles / holding) are themselves an NLP task
-- and stay NULL until the parsing step. jid is the 司法院 judgment id.
--
-- cited_articles convention: a JSON array of {"statute_id","article_no"} objects,
-- e.g.  '[{"statute_id":"民法","article_no":"第793條"}]'
-- This keeps the spec's three-table model (no join table) while still enabling
-- "find all judgments citing 民法第793條" via SQLite's built-in JSON1:
--
--     SELECT j.jid
--     FROM judgments j, json_each(j.cited_articles) c
--     WHERE json_extract(c.value, '$.statute_id') = :statute_id
--       AND json_extract(c.value, '$.article_no') = :article_no;
--
-- If citation lookups later become hot, promote cited_articles to a proper
-- judgment_citations(jid, statute_id, article_no) join table with indexes.
-- Flagged as a known future option — deliberately NOT built now (see README).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS judgments (
    jid             TEXT PRIMARY KEY,   -- 司法院 judgment id (JID)
    court           TEXT,               -- 法院
    year            INTEGER,            -- 年度 (ROC year as integer, e.g. 112)
    case_type       TEXT,               -- 案由
    issues          TEXT,               -- 爭點        (parsed — NLP task, §1.3)
    cited_articles  TEXT,               -- 引用法條     (parsed; JSON array, see above)
    holding         TEXT,               -- 裁判要旨
    full_text       TEXT                -- 判決全文
);
