-- clipdex enrich schema (series3-post3)
-- Raw extraction tables: one row per LLM-emitted mention.
-- Canonical guests + dedup tables come in post 4.

CREATE TABLE IF NOT EXISTS guests_raw (
    id           BIGSERIAL PRIMARY KEY,
    video_id     TEXT NOT NULL REFERENCES processed_videos(video_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    role         TEXT,
    company      TEXT,
    confidence   REAL NOT NULL,
    chunk_start_ms INT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS guests_raw_video_idx ON guests_raw (video_id);

CREATE TABLE IF NOT EXISTS topics_raw (
    id           BIGSERIAL PRIMARY KEY,
    video_id     TEXT NOT NULL REFERENCES processed_videos(video_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    segment_ids  INT[] NOT NULL,
    confidence   REAL NOT NULL,
    chunk_start_ms INT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS topics_raw_video_idx ON topics_raw (video_id);

CREATE TABLE IF NOT EXISTS quotes_raw (
    id           BIGSERIAL PRIMARY KEY,
    video_id     TEXT NOT NULL REFERENCES processed_videos(video_id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    segment_id   INT NOT NULL,
    speaker      TEXT,
    quotability_score REAL NOT NULL,
    chunk_start_ms INT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS quotes_raw_video_idx ON quotes_raw (video_id);

-- Per-video enrichment progress, so re-runs are idempotent.
CREATE TABLE IF NOT EXISTS enriched_videos (
    video_id      TEXT PRIMARY KEY REFERENCES processed_videos(video_id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    chunk_count   INT,
    guest_count   INT,
    topic_count   INT,
    quote_count   INT,
    error         TEXT,
    enriched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
