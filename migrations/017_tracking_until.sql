ALTER TABLE tokens_tracked
ADD COLUMN IF NOT EXISTS tracking_until TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_tokens_tracking_until
ON tokens_tracked(tracking_until)
WHERE tracking_until IS NOT NULL;
