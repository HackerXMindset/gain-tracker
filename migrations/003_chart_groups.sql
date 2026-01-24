-- Chart request groups for chart bot fetches

CREATE TABLE IF NOT EXISTS chart_request_groups (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL UNIQUE,
    label TEXT,
    added_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chart_request_groups_chat_id_negative CHECK (chat_id < 0)
);
