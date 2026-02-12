CREATE TABLE IF NOT EXISTS api_request_metrics_hourly (
    api_name TEXT NOT NULL,
    hour_ts TIMESTAMPTZ NOT NULL,
    total_checks BIGINT NOT NULL DEFAULT 0,
    total_errors BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (api_name, hour_ts)
);

CREATE INDEX IF NOT EXISTS idx_api_request_metrics_hourly_recent
ON api_request_metrics_hourly(hour_ts);
