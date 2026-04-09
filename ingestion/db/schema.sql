-- Personal Brand Intelligence System — Database Schema
-- Compatible with PostgreSQL 14+ and Supabase

-- ─────────────────────────────────────────────
-- EXTENSIONS
-- ─────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ─────────────────────────────────────────────
-- ENUMS
-- ─────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE fetch_method_enum AS ENUM (
        'rss',
        'telegram_api',
        'youtube_transcript',
        'hn_api',
        'web_scraper',
        'site_change_monitor',
        'manual_import',
        'x_api',           -- Wave 3, stub
        'linkedin_api'     -- Wave 3, stub
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE content_status_enum AS ENUM (
        'new',
        'normalized',
        'deduplicated',
        'filtered',
        'candidate',
        'selected',
        'drafted',
        'published',
        'error'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ─────────────────────────────────────────────
-- SOURCES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    source_name             TEXT NOT NULL,
    canonical_name          TEXT NOT NULL,
    canonical_key           TEXT NOT NULL UNIQUE,

    -- Classification
    source_type             TEXT NOT NULL,                          -- person | media | community | channel | newsletter | podcast
    region                  TEXT,                                   -- RU/mixed | EN/global | EN+RU/global etc.
    language                TEXT,                                   -- ru | en | mixed  (separate from region)
    primary_platform        TEXT,                                   -- TG | X | LI | WEB | YT | POD | SB | COMM | FORUM | ...
    platforms               JSONB NOT NULL DEFAULT '[]'::JSONB,    -- all platforms: ["TG", "YT"]

    -- Contact / access
    url                     TEXT,
    handle                  TEXT,

    -- Signal metadata
    themes                  TEXT[],
    signal_type             TEXT,
    signal_quality          SMALLINT CHECK (signal_quality BETWEEN 1 AND 5),
    early_signal_potential  SMALLINT CHECK (early_signal_potential BETWEEN 1 AND 5),
    startup_signal_value    SMALLINT CHECK (startup_signal_value BETWEEN 1 AND 5),
    content_adaptation_value SMALLINT CHECK (content_adaptation_value BETWEEN 1 AND 5),
    brand_fit               SMALLINT CHECK (brand_fit BETWEEN 1 AND 5),
    tier                    SMALLINT NOT NULL DEFAULT 3 CHECK (tier BETWEEN 1 AND 3),
    wave                    SMALLINT NOT NULL DEFAULT 1 CHECK (wave BETWEEN 1 AND 3),

    -- Scheduling
    monitoring_frequency    TEXT,                                   -- daily | 3x_week | weekly
    fetch_method            fetch_method_enum NOT NULL DEFAULT 'manual_import',
    fetch_config            JSONB NOT NULL DEFAULT '{}'::JSONB,    -- fetcher-specific params

    -- State
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    notes                   TEXT,
    error_count             INTEGER NOT NULL DEFAULT 0,
    last_error_at           TIMESTAMPTZ,
    last_error_msg          TEXT,
    last_checked_at         TIMESTAMPTZ,

    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sources_updated_at ON sources;
CREATE TRIGGER sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_sources_fetch_method    ON sources (fetch_method) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_sources_tier_wave       ON sources (tier, wave)   WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_sources_canonical_key   ON sources (canonical_key);

-- ─────────────────────────────────────────────
-- CONTENT ITEMS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS content_items (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source link
    source_id               UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_content_id     TEXT,                                   -- original ID from source system

    -- Content classification
    content_type            TEXT,                                   -- article | post | thread | video | episode | ...
    source_content_type     TEXT,                                   -- raw type string from source (e.g. "rss_item", "tg_message")

    -- Content body
    title                   TEXT,
    content_text            TEXT,                                   -- raw fetched text
    normalized_text         TEXT,                                   -- cleaned, stripped, ready for AI
    summary_raw             TEXT,                                   -- auto-summary placeholder (populated later)
    url                     TEXT,
    author_name             TEXT,

    -- Timing
    published_at            TIMESTAMPTZ,
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Engagement metrics (optional, source-dependent)
    engagement_like_count    INTEGER,
    engagement_comment_count INTEGER,
    engagement_repost_count  INTEGER,
    engagement_view_count    INTEGER,

    -- Raw data
    raw_payload             JSONB,

    -- Dedup
    content_hash            TEXT NOT NULL,

    -- Classification
    language                TEXT,                                   -- detected or inherited from source

    -- Pipeline state
    status                  content_status_enum NOT NULL DEFAULT 'new',
    is_duplicate            BOOLEAN NOT NULL DEFAULT FALSE,
    topic_cluster_id        UUID,

    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    UNIQUE (source_id, external_content_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_content_items_source_id   ON content_items (source_id);
CREATE INDEX IF NOT EXISTS idx_content_items_status      ON content_items (status) WHERE NOT is_duplicate;
CREATE INDEX IF NOT EXISTS idx_content_items_hash        ON content_items (content_hash);
CREATE INDEX IF NOT EXISTS idx_content_items_published   ON content_items (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_items_fetched     ON content_items (fetched_at DESC);
