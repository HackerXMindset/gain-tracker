-- Analytics Phase 1: Milestone tracking and stats infrastructure

-- Table to track when tokens hit major multiplier milestones
CREATE TABLE IF NOT EXISTS token_milestones (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    milestone_type TEXT NOT NULL CHECK (milestone_type IN ('2x', '5x', '10x', '100x')),
    achieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    market_cap_at_milestone NUMERIC(24, 6) NOT NULL,
    first_seen_mc NUMERIC(24, 6) NOT NULL,
    multiplier NUMERIC(10, 5) NOT NULL,
    time_to_milestone_seconds INT NOT NULL,
    UNIQUE(token_id, milestone_type)
);

CREATE INDEX IF NOT EXISTS idx_token_milestones_token ON token_milestones(token_id);
CREATE INDEX IF NOT EXISTS idx_token_milestones_achieved ON token_milestones(achieved_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_milestones_type_time ON token_milestones(milestone_type, achieved_at DESC);

COMMENT ON TABLE token_milestones IS 'Tracks when tokens hit major multiplier milestones (2x, 5x, 10x, 100x)';
COMMENT ON COLUMN token_milestones.time_to_milestone_seconds IS 'Seconds elapsed from first_seen_at to milestone achievement';

-- Table for cached source statistics (used in Phase 2)
CREATE TABLE IF NOT EXISTS source_stats (
    id BIGSERIAL PRIMARY KEY,
    source_id INT REFERENCES monitored_sources(id) ON DELETE CASCADE,
    stat_period TEXT NOT NULL CHECK (stat_period IN ('24h', '7d', '30d', 'all_time')),
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    total_calls INT DEFAULT 0,
    tokens_hit_2x INT DEFAULT 0,
    tokens_hit_5x INT DEFAULT 0,
    tokens_hit_10x INT DEFAULT 0,
    tokens_hit_100x INT DEFAULT 0,
    avg_time_to_2x_seconds INT,
    avg_time_to_5x_seconds INT,
    avg_time_to_peak_seconds INT,
    avg_peak_multiplier NUMERIC(10, 5),
    best_performer_address TEXT,
    best_performer_multiplier NUMERIC(10, 5),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, stat_period)
);

CREATE INDEX IF NOT EXISTS idx_source_stats_source ON source_stats(source_id);
CREATE INDEX IF NOT EXISTS idx_source_stats_updated ON source_stats(updated_at);

COMMENT ON TABLE source_stats IS 'Cached aggregate statistics per monitored source';

-- Table for time-based performance patterns (used in Phase 5)
CREATE TABLE IF NOT EXISTS hourly_patterns (
    id BIGSERIAL PRIMARY KEY,
    hour_of_day INT NOT NULL CHECK (hour_of_day >= 0 AND hour_of_day < 24),
    day_of_week INT NOT NULL CHECK (day_of_week >= 0 AND day_of_week < 7),
    tokens_called INT DEFAULT 0,
    tokens_hit_2x INT DEFAULT 0,
    tokens_hit_5x INT DEFAULT 0,
    avg_time_to_2x_seconds INT,
    success_rate_2x NUMERIC(5, 4),
    last_updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(hour_of_day, day_of_week)
);

CREATE INDEX IF NOT EXISTS idx_hourly_patterns_hour ON hourly_patterns(hour_of_day);
CREATE INDEX IF NOT EXISTS idx_hourly_patterns_dow ON hourly_patterns(day_of_week);

COMMENT ON TABLE hourly_patterns IS 'Time-based performance analysis by hour (UTC) and day of week (0=Monday)';
COMMENT ON COLUMN hourly_patterns.success_rate_2x IS 'Percentage as decimal (0.0 to 1.0)';

-- Add peak tracking timestamp to tokens_tracked
ALTER TABLE tokens_tracked
ADD COLUMN IF NOT EXISTS peak_reached_at TIMESTAMPTZ;

-- Add caller tracking for source attribution
ALTER TABLE tokens_tracked
ADD COLUMN IF NOT EXISTS caller_user_id BIGINT;

-- Index for querying tokens by when they reached peak
CREATE INDEX IF NOT EXISTS idx_tokens_peak_reached
ON tokens_tracked(peak_reached_at)
WHERE peak_reached_at IS NOT NULL;

COMMENT ON COLUMN tokens_tracked.peak_reached_at IS 'Timestamp when peak_mc was last updated';
COMMENT ON COLUMN tokens_tracked.caller_user_id IS 'User ID who originally called this token (for source attribution)';

-- Track which tokens were called from which source (for analytics)
CREATE TABLE IF NOT EXISTS token_call_history (
    id BIGSERIAL PRIMARY KEY,
    token_address TEXT NOT NULL,
    source_chat_id BIGINT NOT NULL,
    caller_user_id BIGINT,
    called_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    message_id BIGINT,
    UNIQUE(token_address, source_chat_id, caller_user_id)
);

CREATE INDEX IF NOT EXISTS idx_token_call_source ON token_call_history(source_chat_id);
CREATE INDEX IF NOT EXISTS idx_token_call_time ON token_call_history(called_at DESC);
CREATE INDEX IF NOT EXISTS idx_token_call_address ON token_call_history(token_address);

COMMENT ON TABLE token_call_history IS 'Tracks which tokens were called from which monitored source';
