from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict


# Gain alert defaults (parity with main app)
GAIN_THRESHOLD_DEFAULT_PCT = 0.30
DROP_THRESHOLD_DEFAULT_PCT = 0.70
DROP_FLOOR_MC_DEFAULT = 8000.0

GAIN_ALERT_TEMPLATE_KEY = "gain_alert_template"
GLOBAL_CHART_THRESHOLD_KEY = "chart_global_mc_threshold"
GLOBAL_CHART_BOT_ID_KEY = "chart_global_bot_id"
CHART_GUARDRAILS_KEY = "chart_guardrails"
DEFAULT_GLOBAL_CHART_THRESHOLD = Decimal("100000")

# Market cap validation bounds
MIN_VALID_MARKET_CAP = 1000.0
MAX_VALID_MARKET_CAP = 1_000_000_000_000.0

DEFAULT_CHART_GUARDRAILS: Dict[str, Any] = {
    "min_age_minutes": 5,
    "min_liquidity_usd": 10_000,
    "min_volume_usd": 5_000,
    "min_multiplier": 1.5,
    "max_price_change_pct": 50,
    "checks_required": 0,
}

GUARDRAIL_SOURCE_MAP = {
    "min_age_minutes": "chart_min_age_minutes",
    "min_liquidity_usd": "chart_min_liquidity_usd",
    "min_volume_usd": "chart_min_volume_usd",
    "min_multiplier": "chart_min_multiplier",
    "max_price_change_pct": "chart_max_price_change_pct",
    "checks_required": "chart_checks_required",
}
