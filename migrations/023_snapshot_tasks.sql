-- Snapshot tasks for precise timeframe capture
CREATE TABLE IF NOT EXISTS snapshot_tasks (
    id BIGSERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    timeframe_seconds INTEGER NOT NULL,
    target_time TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','due','success','late','failed')),
    attempts SMALLINT NOT NULL DEFAULT 0,
    last_error_api TEXT,
    last_error_code INT,
    last_error_message TEXT,
    last_error_at TIMESTAMPTZ,
    recorded_mc NUMERIC(24,6),
    recorded_source TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshot_tasks_token_tf_target
    ON snapshot_tasks(token_id, timeframe_seconds, target_time);

CREATE INDEX IF NOT EXISTS idx_snapshot_tasks_status_due
    ON snapshot_tasks(status, target_time)
    WHERE status IN ('pending','due','failed','late');

-- Trigger to auto-update updated_at (inline definition to avoid missing function)
CREATE OR REPLACE FUNCTION snapshot_tasks_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_snapshot_tasks_updated ON snapshot_tasks;
CREATE TRIGGER trg_snapshot_tasks_updated
BEFORE UPDATE ON snapshot_tasks
FOR EACH ROW
EXECUTE FUNCTION snapshot_tasks_set_updated_at();
