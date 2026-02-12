-- Per-call API tracing
CREATE TABLE IF NOT EXISTS api_call_log (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT REFERENCES tokens_tracked(id) ON DELETE SET NULL,
    api_name TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('initial','poll','snapshot','alert')),
    status_code INT,
    error TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_call_log_created ON api_call_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_call_log_token ON api_call_log(token_id, created_at DESC);
