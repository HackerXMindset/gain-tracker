CREATE TABLE IF NOT EXISTS timeframe_snapshot_attempts (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    timeframe_seconds INTEGER NOT NULL,
    target_time TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    source TEXT,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timeframe_attempts_token
    ON timeframe_snapshot_attempts(token_id);

CREATE INDEX IF NOT EXISTS idx_timeframe_attempts_target
    ON timeframe_snapshot_attempts(token_id, timeframe_seconds, target_time);

CREATE INDEX IF NOT EXISTS idx_timeframe_attempts_created
    ON timeframe_snapshot_attempts(created_at);
