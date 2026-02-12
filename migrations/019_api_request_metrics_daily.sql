CREATE TABLE IF NOT EXISTS api_request_metrics_daily (
    api_name TEXT NOT NULL,
    day DATE NOT NULL,
    total_checks BIGINT NOT NULL DEFAULT 0,
    total_errors BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (api_name, day)
);
