CREATE TABLE IF NOT EXISTS api_request_metrics (
    api_name TEXT PRIMARY KEY,
    total_checks BIGINT NOT NULL DEFAULT 0,
    total_errors BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
