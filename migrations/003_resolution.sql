-- clipdex resolution schema (series3-post4)
-- Canonical guests + alias rows pointing at them.
-- Aliases come from guests_raw mentions; one canonical guest can have many.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS guests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name  TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS guests_normalized_name_uidx
    ON guests (normalized_name);

CREATE TABLE IF NOT EXISTS guest_aliases (
    id               BIGSERIAL PRIMARY KEY,
    guest_id         UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    alias_name       TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    source_video_id  TEXT REFERENCES processed_videos(video_id) ON DELETE SET NULL,
    confidence       REAL NOT NULL,
    decided_by       TEXT NOT NULL CHECK (decided_by IN ('exact','fuzzy','llm','manual')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS guest_aliases_guest_idx
    ON guest_aliases (guest_id);
CREATE INDEX IF NOT EXISTS guest_aliases_normalized_idx
    ON guest_aliases (normalized_alias);
CREATE UNIQUE INDEX IF NOT EXISTS guest_aliases_unique_per_guest
    ON guest_aliases (guest_id, normalized_alias);

-- LLM decisions cache: same pair never asked twice.
-- Keyed on the *normalized* pair (sorted) so it's symmetric.
CREATE TABLE IF NOT EXISTS guest_merge_decisions (
    id              BIGSERIAL PRIMARY KEY,
    norm_a          TEXT NOT NULL,
    norm_b          TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('yes','no','uncertain')),
    rationale       TEXT,
    decided_by      TEXT NOT NULL CHECK (decided_by IN ('llm','manual')),
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS guest_merge_decisions_pair_uidx
    ON guest_merge_decisions (norm_a, norm_b);

-- Review queue: fuzzy candidates 70–89 that we want a human to OK.
CREATE TABLE IF NOT EXISTS guest_merge_review (
    id              BIGSERIAL PRIMARY KEY,
    guest_id        UUID NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
    raw_id          BIGINT NOT NULL REFERENCES guests_raw(id) ON DELETE CASCADE,
    candidate_name  TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    score           REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS guest_merge_review_status_idx
    ON guest_merge_review (status);
