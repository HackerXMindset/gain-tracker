from decimal import Decimal

from alerts.thresholds import compute_threshold, should_fire_gain_alert


def test_compute_threshold() -> None:
    baseline = Decimal("100")
    pct = Decimal("0.30")
    assert compute_threshold(baseline, pct) == Decimal("130")


def test_should_fire_gain_alert() -> None:
    baseline = Decimal("100")
    pct = Decimal("0.30")
    assert should_fire_gain_alert(Decimal("130"), baseline, pct) is True
    assert should_fire_gain_alert(Decimal("129.9"), baseline, pct) is False
