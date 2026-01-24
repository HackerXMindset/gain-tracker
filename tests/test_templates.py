from alerts.templates import DEFAULT_GAIN_ALERT_TEMPLATE


def test_default_template_renders() -> None:
    context = {
        "gain_emoji": "📈",
        "token_symbol": "TEST",
        "multiplier": "2.0x",
        "first_market_cap": "$1.0M",
        "current_market_cap": "$2.0M",
        "elapsed_time": "10m",
        "address": "So11111111111111111111111111111111111111112",
    }
    rendered = DEFAULT_GAIN_ALERT_TEMPLATE.format(**context)
    assert "TEST" in rendered
    assert "So111111" in rendered
