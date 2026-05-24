-- clipdex search schema (series3-post4 follow-up, series3-post6).
-- Postgres FTS over transcript_segments, plus a cache for LLM-reranked queries.

-- Use a regular table-backed view we can REINDEX/REFRESH cheaply. The materialized
-- view holds the to_tsvector('english', text) precomputed and a GIN index over it.
DROP MATERIALIZED VIEW IF EXISTS transcript_segments_search;

CREATE MATERIALIZED VIEW transcript_segments_search AS
SELECT
    ts.video_id,
    ts.seq,
    ts.start_ms,
    ts.end_ms,
    ts.text,
    to_tsvector('english', ts.text) AS ts_doc
FROM transcript_segments ts
WHERE length(trim(ts.text)) > 1;

CREATE UNIQUE INDEX transcript_segments_search_pk
    ON transcript_segments_search (video_id, seq);

CREATE INDEX transcript_segments_search_gin
    ON transcript_segments_search USING GIN (ts_doc);

-- Cache: maps (query_hash, fts_top_ids_hash) -> reranked id list.
-- 7-day TTL enforced at read time; nothing fancy.
CREATE TABLE IF NOT EXISTS search_cache (
    id             BIGSERIAL PRIMARY KEY,
    query_hash     TEXT NOT NULL,
    top_ids_hash   TEXT NOT NULL,
    query_text     TEXT NOT NULL,
    reranked       JSONB NOT NULL,
    cached_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS search_cache_keys_uidx
    ON search_cache (query_hash, top_ids_hash);

CREATE INDEX IF NOT EXISTS search_cache_age_idx
    ON search_cache (cached_at);
