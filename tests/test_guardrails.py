import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from charts.guardrail_evaluator import evaluate_chart_guardrails


def test_guardrails_pass() -> None:
    now = datetime.now(timezone.utc)
    guardrails = {
        "min_age_minutes": 5,
        "min_liquidity_usd": 10000,
        "min_volume_usd": 5000,
        "min_multiplier": 1.5,
        "max_price_change_pct": 50,
        "checks_required": 0,
    }
    pair_data = {
        "liquidity": {"usd": 20000},
        "volume": {"h24": 10000},
        "priceChange": {"h24": 10},
    }
    result = asyncio.run(
        evaluate_chart_guardrails(
            token_data={},
            pair_data=pair_data,
            guardrails=guardrails,
            current_mc=Decimal("20000"),
            first_seen_mc=Decimal("10000"),
            first_seen_at=now - timedelta(minutes=10),
            address="So11111111111111111111111111111111111111112",
        )
    )
    assert result.passed is True
