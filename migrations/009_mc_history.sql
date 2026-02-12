-- Phase 1.5: Market cap history for investment simulator

-- Store MC snapshots on every poll for time-based hold strategies
CREATE TABLE IF NOT EXISTS token_mc_history (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    market_cap NUMERIC(24, 6) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mc_history_token_time
ON token_mc_history(token_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_mc_history_lookup
ON token_mc_history(token_id, recorded_at);

COMMENT ON TABLE token_mc_history IS 'Market cap snapshots recorded on every poll for historical analysis';
COMMENT ON COLUMN token_mc_history.recorded_at IS 'Timestamp when this market cap was observed';

-- User-configurable hold timeframes for investment simulator
CREATE TABLE IF NOT EXISTS hold_timeframes (
    id BIGSERIAL PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    seconds INT NOT NULL,
    display_order INT DEFAULT 0,
    is_default BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT hold_timeframe_seconds_positive CHECK (seconds > 0),
    CONSTRAINT hold_timeframe_label_format CHECK (label ~ '^[0-9]+[smhdw]+$')
);

CREATE INDEX IF NOT EXISTS idx_hold_timeframes_default
ON hold_timeframes(display_order)
WHERE is_default = true;

COMMENT ON TABLE hold_timeframes IS 'Configurable hold periods for investment simulator (e.g., 1h, 6h, 24h)';
COMMENT ON COLUMN hold_timeframes.label IS 'Human-readable label like "5m", "1h", "24h"';
COMMENT ON COLUMN hold_timeframes.seconds IS 'Duration in seconds';
COMMENT ON COLUMN hold_timeframes.is_default IS 'Show in /invest by default';

-- Seed default timeframes
INSERT INTO hold_timeframes (label, seconds, display_order, is_default) VALUES
('5m', 300, 1, true),
('10m', 600, 2, false),
('15m', 900, 3, true),
('30m', 1800, 4, true),
('45m', 2700, 5, false),
('1h', 3600, 10, true),
('2h', 7200, 11, false),
('3h', 10800, 12, false),
('6h', 21600, 13, true),
('12h', 43200, 14, false),
('24h', 86400, 20, true),
('48h', 172800, 21, false),
('72h', 259200, 22, false),
('7d', 604800, 30, true),
('14d', 1209600, 31, false),
('30d', 2592000, 32, true)
ON CONFLICT (label) DO NOTHING;
