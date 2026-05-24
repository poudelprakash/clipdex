-- clipdex initial schema (series3-post2)
-- Tables for ingest worker idempotency + transcript storage.

CREATE TABLE IF NOT EXISTS processed_videos (
    video_id        TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    source          TEXT,
    segment_count   INT,
    ingested_at     TIMESTAMPTZ,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    video_id   TEXT NOT NULL REFERENCES processed_videos(video_id) ON DELETE CASCADE,
    seq        INT NOT NULL,
    start_ms   INT NOT NULL,
    end_ms     INT NOT NULL,
    text       TEXT NOT NULL,
    source     TEXT NOT NULL,
    PRIMARY KEY (video_id, seq)
);

CREATE INDEX IF NOT EXISTS transcript_segments_video_idx
    ON transcript_segments (video_id, start_ms);
