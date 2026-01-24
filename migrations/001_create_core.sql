-- Core tables for standalone gain alert service

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bots (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT CHECK (kind IN ('management', 'userbot')) NOT NULL,
    session_name TEXT UNIQUE,
    status TEXT DEFAULT 'unknown',
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS groups (
    id BIGSERIAL PRIMARY KEY,
    tg_chat_id BIGINT UNIQUE NOT NULL,
    title TEXT,
    enabled BOOLEAN DEFAULT true,
    daily_cap INT DEFAULT 0,
    cooldown_minutes INT DEFAULT 10,
    notif_channel_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tokens_tracked (
    id BIGSERIAL PRIMARY KEY,
    address TEXT UNIQUE NOT NULL,
    source_group_id BIGINT REFERENCES groups(id) ON DELETE SET NULL,
    first_seen_mc NUMERIC,
    last_mc NUMERIC,
    status TEXT DEFAULT 'active',
    last_hit_multiplier NUMERIC DEFAULT 1,
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_checked_at TIMESTAMPTZ DEFAULT NOW(),
    peak_mc NUMERIC DEFAULT 0,
    ticker VARCHAR(32),
    last_alert_mc NUMERIC(24, 6),
    current_tier TEXT DEFAULT 'tier_a',
    next_poll_at TIMESTAMPTZ,
    stop_reason TEXT,
    dex_screener_refreshed_at TIMESTAMPTZ,
    original_message_id BIGINT,
    CONSTRAINT check_valid_tier
        CHECK (current_tier IN ('tier_a', 'tier_b', 'tier_c', 'tier_d', 'tier_e', 'tier_f') OR current_tier IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_tokens_source_group ON tokens_tracked(source_group_id);
CREATE INDEX IF NOT EXISTS idx_tokens_tracked_ticker ON tokens_tracked(ticker);
CREATE INDEX IF NOT EXISTS idx_tokens_next_poll
    ON tokens_tracked(next_poll_at)
    WHERE status = 'active' AND next_poll_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tokens_current_tier
    ON tokens_tracked(current_tier)
    WHERE status = 'active';
