-- Add tracking userbot selection to monitored_sources

ALTER TABLE monitored_sources
ADD COLUMN IF NOT EXISTS tracking_userbot_id BIGINT REFERENCES bots(id) ON DELETE SET NULL;

ALTER TABLE monitored_sources
ADD COLUMN IF NOT EXISTS tracking_fallback_enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_monitored_sources_tracking_userbot
    ON monitored_sources(tracking_userbot_id)
    WHERE tracking_userbot_id IS NOT NULL;
