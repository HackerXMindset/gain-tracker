-- Gain alert tables and routing config

CREATE TABLE IF NOT EXISTS monitored_sources (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    chat_type TEXT NOT NULL CHECK (chat_type IN ('group', 'channel', 'dm')),
    user_id BIGINT,
    added_by_admin_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    display_name TEXT,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sensitivity_pct NUMERIC(6, 5),
    assigned_userbot_id BIGINT REFERENCES bots(id) ON DELETE SET NULL,
    template_text TEXT,
    use_management_bot BOOLEAN NOT NULL DEFAULT FALSE,
    chart_enabled BOOLEAN DEFAULT FALSE,
    chart_bot_id BIGINT,
    chart_mc_threshold NUMERIC(20, 2) DEFAULT 100000.00,
    chart_min_age_minutes INT,
    chart_min_liquidity_usd NUMERIC(20, 2),
    chart_min_volume_usd NUMERIC(20, 2),
    chart_min_multiplier NUMERIC(10, 5),
    chart_max_price_change_pct NUMERIC(6, 3),
    chart_checks_required INT,
    last_guardrail_result JSONB,
    CHECK (
        (chat_type = 'group' AND user_id IS NOT NULL)
        OR (chat_type IN ('channel', 'dm') AND user_id IS NULL)
    ),
    CONSTRAINT chart_mc_threshold_positive
        CHECK (chart_mc_threshold IS NULL OR chart_mc_threshold > 0),
    CONSTRAINT chart_min_age_positive
        CHECK (chart_min_age_minutes IS NULL OR chart_min_age_minutes >= 0),
    CONSTRAINT chart_min_liquidity_positive
        CHECK (chart_min_liquidity_usd IS NULL OR chart_min_liquidity_usd >= 0),
    CONSTRAINT chart_min_volume_positive
        CHECK (chart_min_volume_usd IS NULL OR chart_min_volume_usd >= 0),
    CONSTRAINT chart_min_multiplier_valid
        CHECK (chart_min_multiplier IS NULL OR chart_min_multiplier >= 1.0),
    CONSTRAINT chart_max_price_change_valid
        CHECK (
            chart_max_price_change_pct IS NULL
            OR (chart_max_price_change_pct >= 0 AND chart_max_price_change_pct <= 100)
        ),
    CONSTRAINT chart_checks_required_valid
        CHECK (chart_checks_required IS NULL OR (chart_checks_required >= 0 AND chart_checks_required <= 5)),
    UNIQUE(chat_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_monitored_sources_chat ON monitored_sources(chat_id);
CREATE INDEX IF NOT EXISTS idx_monitored_sources_user ON monitored_sources(user_id) WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_monitored_sources_unique_channel_dm
    ON monitored_sources(chat_id)
    WHERE user_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_monitored_sources_chart_bot
    ON monitored_sources(chart_bot_id)
    WHERE chart_bot_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS monitored_source_targets (
    id SERIAL PRIMARY KEY,
    source_id INT NOT NULL REFERENCES monitored_sources(id) ON DELETE CASCADE,
    target_chat_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_id, target_chat_id)
);

CREATE INDEX IF NOT EXISTS idx_monitored_source_targets_source
    ON monitored_source_targets(source_id);
CREATE INDEX IF NOT EXISTS idx_monitored_source_targets_chat
    ON monitored_source_targets(target_chat_id);

CREATE TABLE IF NOT EXISTS token_group_alerts (
    id SERIAL PRIMARY KEY,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    first_seen_mc NUMERIC(20, 2) NOT NULL,
    last_alert_mc NUMERIC(20, 2),
    original_message_id BIGINT NOT NULL,
    original_user_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    first_seen_at TIMESTAMPTZ,
    last_alert_at TIMESTAMPTZ,
    last_alert_message_id BIGINT,
    UNIQUE(token_id, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_token_group_alerts_token ON token_group_alerts(token_id);
CREATE INDEX IF NOT EXISTS idx_token_group_alerts_chat ON token_group_alerts(chat_id);
CREATE INDEX IF NOT EXISTS idx_token_group_alerts_lookup ON token_group_alerts(token_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_token_group_alerts_last_alert_at
    ON token_group_alerts(last_alert_at DESC)
    WHERE last_alert_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS alert_queue (
    id SERIAL PRIMARY KEY,
    token_id BIGINT REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    token_address TEXT NOT NULL,
    alert_message TEXT NOT NULL,
    target_chat_id BIGINT NOT NULL,
    reply_to_message_id BIGINT,
    attempt_count INT DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    status TEXT DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT check_alert_queue_status
        CHECK (status IN ('pending', 'sent', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_alert_queue_status ON alert_queue(status, created_at);
CREATE INDEX IF NOT EXISTS idx_alert_queue_token_id ON alert_queue(token_id);
CREATE INDEX IF NOT EXISTS idx_alert_queue_pending ON alert_queue(created_at) WHERE status = 'pending';
