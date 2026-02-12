-- Scheduler heartbeat and backlog sizes
CREATE TABLE IF NOT EXISTS scheduler_state (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_poll_heartbeat TIMESTAMPTZ,
    last_snapshot_heartbeat TIMESTAMPTZ,
    poll_queue_size INT DEFAULT 0,
    snapshot_queue_size INT DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO scheduler_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;
