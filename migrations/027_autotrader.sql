-- AutoTrader core tables
CREATE TABLE IF NOT EXISTS autotrader_runs (
    id BIGSERIAL PRIMARY KEY,
    name TEXT,
    created_by_user_id BIGINT,
    destination_chat_id BIGINT,
    destination_type TEXT, -- chat/DM
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','stopped','completed','failed')),
    start_at TIMESTAMPTZ,
    stop_at TIMESTAMPTZ,
    budget_total NUMERIC(24,6) NOT NULL,
    per_coin_spend NUMERIC(24,6) NOT NULL,
    remaining_cash NUMERIC(24,6) NOT NULL,
    coin_cap INTEGER,
    hold_seconds INTEGER NOT NULL,
    report_interval_seconds INTEGER,
    breakout_multiple NUMERIC(10,2),
    bankrupt_floor NUMERIC(24,6),
    target_value NUMERIC(24,6),
    channel_mode TEXT NOT NULL DEFAULT 'single' CHECK (channel_mode IN ('single','multi','all')),
    channels TEXT[],
    freshness_secs INTEGER NOT NULL DEFAULT 15,
    max_retries INTEGER NOT NULL DEFAULT 10,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS autotrader_positions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES autotrader_runs(id) ON DELETE CASCADE,
    token_id BIGINT NOT NULL REFERENCES tokens_tracked(id) ON DELETE CASCADE,
    buy_amount NUMERIC(24,6) NOT NULL,
    buy_price NUMERIC(24,12),
    buy_mc NUMERIC(24,6),
    qty NUMERIC(38,18),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','sold','stopped','expired')),
    sell_amount NUMERIC(24,6),
    sell_price NUMERIC(24,12),
    realized_pnl NUMERIC(24,6),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS autotrader_events (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT REFERENCES autotrader_runs(id) ON DELETE CASCADE,
    token_id BIGINT REFERENCES tokens_tracked(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    message TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS autotrader_reports (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES autotrader_runs(id) ON DELETE CASCADE,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    summary JSONB,
    delivered_to BIGINT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_autotrader_runs_status ON autotrader_runs(status);
CREATE INDEX IF NOT EXISTS idx_autotrader_positions_run ON autotrader_positions(run_id, status);
CREATE INDEX IF NOT EXISTS idx_autotrader_events_run ON autotrader_events(run_id);
CREATE INDEX IF NOT EXISTS idx_autotrader_reports_run ON autotrader_reports(run_id, status);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION autotrader_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_autotrader_runs_updated ON autotrader_runs;
CREATE TRIGGER trg_autotrader_runs_updated
BEFORE UPDATE ON autotrader_runs
FOR EACH ROW EXECUTE FUNCTION autotrader_set_updated_at();

DROP TRIGGER IF EXISTS trg_autotrader_positions_updated ON autotrader_positions;
CREATE TRIGGER trg_autotrader_positions_updated
BEFORE UPDATE ON autotrader_positions
FOR EACH ROW EXECUTE FUNCTION autotrader_set_updated_at();

DROP TRIGGER IF EXISTS trg_autotrader_reports_updated ON autotrader_reports;
CREATE TRIGGER trg_autotrader_reports_updated
BEFORE UPDATE ON autotrader_reports
FOR EACH ROW EXECUTE FUNCTION autotrader_set_updated_at();
