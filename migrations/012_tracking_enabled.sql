ALTER TABLE monitored_sources
ADD COLUMN IF NOT EXISTS tracking_enabled BOOLEAN DEFAULT TRUE;

UPDATE monitored_sources
SET tracking_enabled = TRUE
WHERE tracking_enabled IS NULL;
