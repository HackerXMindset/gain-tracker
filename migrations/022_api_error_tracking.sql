ALTER TABLE tokens_tracked
    ADD COLUMN IF NOT EXISTS last_api_error_api TEXT,
    ADD COLUMN IF NOT EXISTS last_api_error_code INT,
    ADD COLUMN IF NOT EXISTS last_api_error_message TEXT,
    ADD COLUMN IF NOT EXISTS last_api_error_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_tokens_last_api_error_at
    ON tokens_tracked(last_api_error_at DESC)
    WHERE last_api_error_at IS NOT NULL;
