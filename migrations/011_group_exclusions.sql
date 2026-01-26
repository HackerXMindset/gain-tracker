-- Per-group exclusions for track-all monitoring

CREATE TABLE IF NOT EXISTS monitored_source_exclusions (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_monitored_source_exclusions_chat
    ON monitored_source_exclusions(chat_id);
CREATE INDEX IF NOT EXISTS idx_monitored_source_exclusions_user
    ON monitored_source_exclusions(user_id);
