-- Add userbot metadata fields and assignment table

ALTER TABLE bots ADD COLUMN IF NOT EXISTS display_name TEXT;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS phone TEXT;

CREATE TABLE IF NOT EXISTS userbot_assignments (
    id BIGSERIAL PRIMARY KEY,
    userbot_id BIGINT REFERENCES bots(id) ON DELETE CASCADE,
    group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(userbot_id, group_id),
    UNIQUE(group_id)
);
