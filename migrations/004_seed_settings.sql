-- Default settings for gain alerts and charts

INSERT INTO settings (key, value) VALUES
    ('gain_threshold_pct', '0.30'),
    ('drop_threshold_pct', '0.70'),
    ('drop_floor_mc', '8000'),
    (
        'gain_alert_template',
        to_jsonb($${gain_emoji} ${token_symbol} {multiplier} | 💹From {first_market_cap} ↗️ {current_market_cap} within {elapsed_time}
🔗 CA: {address}
⚠️ Gain alerts are in beta and may be inaccurate.$$::text)
    ),
    (
        'chart_guardrails',
        jsonb_build_object(
            'min_age_minutes', 5,
            'min_liquidity_usd', 10000,
            'min_volume_usd', 5000,
            'min_multiplier', 1.5,
            'max_price_change_pct', 50,
            'checks_required', 0
        )
    )
ON CONFLICT (key) DO NOTHING;
