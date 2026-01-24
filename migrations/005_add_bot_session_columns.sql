-- Add userbot session storage fields to bots table

ALTER TABLE bots ADD COLUMN IF NOT EXISTS session_string TEXT;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS telegram_id BIGINT;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS username TEXT;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE bots ADD COLUMN IF NOT EXISTS last_name TEXT;

CREATE INDEX IF NOT EXISTS idx_bots_telegram_id ON bots(telegram_id);
