-- Gain alerts decision log
CREATE TABLE IF NOT EXISTS alerts_log (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('gain','stoploss')),
    baseline_mc NUMERIC(24,6),
    current_mc NUMERIC(24,6),
    gain_threshold_pct NUMERIC(10,5),
    sent_to BIGINT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','skipped','failed')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_log_token ON alerts_log(token_id, created_at DESC);
