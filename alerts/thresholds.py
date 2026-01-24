from __future__ import annotations

from decimal import Decimal


def compute_threshold(baseline_mc: Decimal, gain_threshold_pct: Decimal) -> Decimal:
    return baseline_mc * (Decimal(1) + gain_threshold_pct)


def should_fire_gain_alert(
    current_mc: Decimal,
    baseline_mc: Decimal,
    gain_threshold_pct: Decimal,
) -> bool:
    if baseline_mc <= 0:
        return False
    return current_mc >= compute_threshold(baseline_mc, gain_threshold_pct)
