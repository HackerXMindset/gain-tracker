-- Command forwarding rules and tracked messages (Rank UI)

ALTER TABLE groups ADD COLUMN IF NOT EXISTS display_name TEXT;

CREATE TABLE IF NOT EXISTS command_forwarding_rules (
    id BIGSERIAL PRIMARY KEY,
    source_group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE,
    command_text TEXT NOT NULL,
    destination_channel_id BIGINT NOT NULL,
    allowed_command_user_ids BIGINT[] NOT NULL DEFAULT '{}',
    allowed_reply_user_ids BIGINT[] NOT NULL DEFAULT '{}',
    forwarding_userbot_id BIGINT REFERENCES bots(id) ON DELETE SET NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    schedule_enabled BOOLEAN NOT NULL DEFAULT false,
    schedule_interval_minutes INT,
    next_scheduled_at TIMESTAMPTZ,
    last_scheduled_at TIMESTAMPTZ,
    post_timestamp BOOLEAN NOT NULL DEFAULT false,
    timestamp_timezone TEXT NOT NULL DEFAULT 'IST',
    excluded_message_texts TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cmd_fwd_rules_source_group ON command_forwarding_rules(source_group_id);
CREATE INDEX IF NOT EXISTS idx_cmd_fwd_rules_enabled ON command_forwarding_rules(enabled);
CREATE INDEX IF NOT EXISTS idx_cmd_fwd_rules_schedule ON command_forwarding_rules(schedule_enabled);
CREATE INDEX IF NOT EXISTS idx_cmd_fwd_rules_next_schedule ON command_forwarding_rules(next_scheduled_at);

CREATE TABLE IF NOT EXISTS command_tracked_messages (
    id BIGSERIAL PRIMARY KEY,
    rule_id BIGINT REFERENCES command_forwarding_rules(id) ON DELETE CASCADE,
    original_message_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    sender_id BIGINT,
    command_text TEXT,
    status TEXT NOT NULL DEFAULT 'tracking',
    reply_sender_id BIGINT,
    last_reply_message_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT command_tracked_messages_status_check
        CHECK (status IN ('tracking', 'forwarded')),
    UNIQUE (original_message_id, chat_id, rule_id)
);

CREATE INDEX IF NOT EXISTS idx_cmd_tracked_messages_chat ON command_tracked_messages(chat_id);
CREATE INDEX IF NOT EXISTS idx_cmd_tracked_messages_rule ON command_tracked_messages(rule_id);
CREATE INDEX IF NOT EXISTS idx_cmd_tracked_messages_status ON command_tracked_messages(status);
