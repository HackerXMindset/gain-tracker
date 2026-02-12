CREATE TABLE IF NOT EXISTS rank_forwarding_rules (
    id SERIAL PRIMARY KEY,
    source_chat_id BIGINT NOT NULL,
    destination_chat_id BIGINT,
    command_text TEXT NOT NULL DEFAULT '/rank',
    send_userbot_id BIGINT REFERENCES bots(id) ON DELETE SET NULL,
    forward_userbot_id BIGINT REFERENCES bots(id) ON DELETE SET NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    schedule_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    schedule_interval_minutes INTEGER NOT NULL DEFAULT 1440,
    next_scheduled_at TIMESTAMPTZ,
    allowed_command_user_ids BIGINT[] NOT NULL DEFAULT '{}',
    allowed_reply_user_ids BIGINT[] NOT NULL DEFAULT '{}',
    excluded_message_texts TEXT[] NOT NULL DEFAULT '{}',
    post_timestamp BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp_timezone TEXT NOT NULL DEFAULT 'UTC',
    post_chart_request BOOLEAN NOT NULL DEFAULT FALSE,
    chart_request_chat_id BIGINT,
    chart_request_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_rank_forwarding_source
ON rank_forwarding_rules(source_chat_id);

CREATE INDEX IF NOT EXISTS idx_rank_forwarding_schedule
ON rank_forwarding_rules(schedule_enabled, next_scheduled_at)
WHERE schedule_enabled = true;

CREATE TABLE IF NOT EXISTS rank_tracked_messages (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES rank_forwarding_rules(id) ON DELETE CASCADE,
    original_message_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    sender_id BIGINT,
    status TEXT NOT NULL DEFAULT 'tracking',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rank_tracked_lookup
ON rank_tracked_messages(chat_id, original_message_id);
