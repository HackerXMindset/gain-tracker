"""
Chart Guardrail Evaluator - Evaluates token metrics against configured guardrails.
"""

import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class GuardrailCheckResult:
    def __init__(self, name: str, passed: bool, actual_value: Any, threshold_value: Any, reason: str = ""):
        self.name = name
        self.passed = passed
        self.actual_value = actual_value
        self.threshold_value = threshold_value
        self.reason = reason

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"{self.name}: {status} (actual={self.actual_value}, threshold={self.threshold_value})"


class GuardrailEvaluationResult:
    def __init__(self, passed: bool, checks: List[GuardrailCheckResult], checks_required: int, checks_passed: int):
        self.passed = passed
        self.checks = checks
        self.checks_required = checks_required
        self.checks_passed = checks_passed

    def get_failed_checks(self) -> List[GuardrailCheckResult]:
        return [check for check in self.checks if not check.passed]

    def get_passed_checks(self) -> List[GuardrailCheckResult]:
        return [check for check in self.checks if check.passed]

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"GuardrailEvaluation: {status} "
            f"({self.checks_passed}/{len(self.checks)} checks passed, {self.checks_required} required)"
        )


async def evaluate_chart_guardrails(
    token_data: Dict[str, Any],
    pair_data: Optional[Dict[str, Any]],
    guardrails: Dict[str, Any],
    current_mc: Decimal,
    first_seen_mc: Decimal,
    first_seen_at: Optional[datetime],
    address: str,
) -> GuardrailEvaluationResult:
    checks: List[GuardrailCheckResult] = []

    min_age_minutes = guardrails.get("min_age_minutes", 5)
    min_liquidity_usd = guardrails.get("min_liquidity_usd", 10000)
    min_volume_usd = guardrails.get("min_volume_usd", 5000)
    min_multiplier = guardrails.get("min_multiplier", 1.5)
    max_price_change_pct = guardrails.get("max_price_change_pct", 50)
    checks_required = guardrails.get("checks_required", 0)

    age_minutes = None
    if first_seen_at:
        now = datetime.now(timezone.utc)
        if first_seen_at.tzinfo is None:
            first_seen_at = first_seen_at.replace(tzinfo=timezone.utc)
        age_seconds = int((now - first_seen_at).total_seconds())
        age_minutes = age_seconds / 60.0
        passed = age_minutes >= min_age_minutes
        checks.append(
            GuardrailCheckResult(
                name="age",
                passed=passed,
                actual_value=f"{age_minutes:.1f}m",
                threshold_value=f"{min_age_minutes}m",
                reason=f"Token age {age_minutes:.1f}m vs required {min_age_minutes}m",
            )
        )
    else:
        checks.append(
            GuardrailCheckResult(
                name="age",
                passed=False,
                actual_value="N/A",
                threshold_value=f"{min_age_minutes}m",
                reason="Token age unavailable",
            )
        )

    liquidity_usd = None
    if pair_data:
        liquidity = pair_data.get("liquidity") or {}
        liquidity_usd = liquidity.get("usd")

        if liquidity_usd is not None:
            try:
                liquidity_usd = float(liquidity_usd)
                passed = liquidity_usd >= min_liquidity_usd
                checks.append(
                    GuardrailCheckResult(
                        name="liquidity",
                        passed=passed,
                        actual_value=f"${liquidity_usd:,.0f}",
                        threshold_value=f"${min_liquidity_usd:,.0f}",
                        reason=f"Liquidity ${liquidity_usd:,.0f} vs required ${min_liquidity_usd:,.0f}",
                    )
                )
            except (ValueError, TypeError):
                checks.append(
                    GuardrailCheckResult(
                        name="liquidity",
                        passed=False,
                        actual_value="invalid",
                        threshold_value=f"${min_liquidity_usd:,.0f}",
                        reason="Invalid liquidity data",
                    )
                )
        else:
            checks.append(
                GuardrailCheckResult(
                    name="liquidity",
                    passed=False,
                    actual_value="N/A",
                    threshold_value=f"${min_liquidity_usd:,.0f}",
                    reason="Liquidity data unavailable",
                )
            )
    else:
        checks.append(
            GuardrailCheckResult(
                name="liquidity",
                passed=False,
                actual_value="N/A",
                threshold_value=f"${min_liquidity_usd:,.0f}",
                reason="No pair data available",
            )
        )

    volume_24h = None
    if pair_data:
        volume = pair_data.get("volume") or {}
        volume_24h = volume.get("h24")

        if volume_24h is not None:
            try:
                volume_24h = float(volume_24h)
                passed = volume_24h >= min_volume_usd
                checks.append(
                    GuardrailCheckResult(
                        name="volume_24h",
                        passed=passed,
                        actual_value=f"${volume_24h:,.0f}",
                        threshold_value=f"${min_volume_usd:,.0f}",
                        reason=f"24h volume ${volume_24h:,.0f} vs required ${min_volume_usd:,.0f}",
                    )
                )
            except (ValueError, TypeError):
                checks.append(
                    GuardrailCheckResult(
                        name="volume_24h",
                        passed=False,
                        actual_value="invalid",
                        threshold_value=f"${min_volume_usd:,.0f}",
                        reason="Invalid volume data",
                    )
                )
        else:
            checks.append(
                GuardrailCheckResult(
                    name="volume_24h",
                    passed=False,
                    actual_value="N/A",
                    threshold_value=f"${min_volume_usd:,.0f}",
                    reason="Volume data unavailable",
                )
            )
    else:
        checks.append(
            GuardrailCheckResult(
                name="volume_24h",
                passed=False,
                actual_value="N/A",
                threshold_value=f"${min_volume_usd:,.0f}",
                reason="No pair data available",
            )
        )

    multiplier = None
    if first_seen_mc and first_seen_mc > 0:
        try:
            multiplier = float(current_mc / first_seen_mc)
            passed = multiplier >= min_multiplier
            checks.append(
                GuardrailCheckResult(
                    name="multiplier",
                    passed=passed,
                    actual_value=f"{multiplier:.2f}x",
                    threshold_value=f"{min_multiplier:.2f}x",
                    reason=f"Multiplier {multiplier:.2f}x vs required {min_multiplier:.2f}x",
                )
            )
        except (ValueError, ZeroDivisionError, TypeError):
            checks.append(
                GuardrailCheckResult(
                    name="multiplier",
                    passed=False,
                    actual_value="invalid",
                    threshold_value=f"{min_multiplier:.2f}x",
                    reason="Invalid multiplier calculation",
                )
            )
    else:
        checks.append(
            GuardrailCheckResult(
                name="multiplier",
                passed=False,
                actual_value="N/A",
                threshold_value=f"{min_multiplier:.2f}x",
                reason="First seen MC unavailable or zero",
            )
        )

    price_change_24h = None
    if pair_data:
        price_change = pair_data.get("priceChange") or {}
        price_change_24h = price_change.get("h24")

        if price_change_24h is not None:
            try:
                price_change_24h = float(price_change_24h)
                passed = abs(price_change_24h) <= max_price_change_pct
                checks.append(
                    GuardrailCheckResult(
                        name="price_stability",
                        passed=passed,
                        actual_value=f"{price_change_24h:+.2f}%",
                        threshold_value=f"+/-{max_price_change_pct:.0f}%",
                        reason=(
                            f"Price change {price_change_24h:+.2f}% vs "
                            f"threshold +/-{max_price_change_pct:.0f}%"
                        ),
                    )
                )
            except (ValueError, TypeError):
                checks.append(
                    GuardrailCheckResult(
                        name="price_stability",
                        passed=False,
                        actual_value="invalid",
                        threshold_value=f"+/-{max_price_change_pct:.0f}%",
                        reason="Invalid price change data",
                    )
                )
        else:
            checks.append(
                GuardrailCheckResult(
                    name="price_stability",
                    passed=False,
                    actual_value="N/A",
                    threshold_value=f"+/-{max_price_change_pct:.0f}%",
                    reason="Price change data unavailable",
                )
            )
    else:
        checks.append(
            GuardrailCheckResult(
                name="price_stability",
                passed=False,
                actual_value="N/A",
                threshold_value=f"+/-{max_price_change_pct:.0f}%",
                reason="No pair data available",
            )
        )

    total_checks = len(checks)
    checks_passed_count = sum(1 for check in checks if check.passed)

    if checks_required == 0:
        evaluation_passed = checks_passed_count == total_checks
    else:
        evaluation_passed = checks_passed_count >= checks_required

    result = GuardrailEvaluationResult(
        passed=evaluation_passed,
        checks=checks,
        checks_required=checks_required if checks_required > 0 else total_checks,
        checks_passed=checks_passed_count,
    )

    log_level = logging.INFO if evaluation_passed else logging.WARNING
    logger.log(
        log_level,
        "[CHART_GUARDRAIL] Token %s evaluation: %s (%d/%d checks passed, %d required)",
        address[:8],
        "PASS" if evaluation_passed else "FAIL",
        checks_passed_count,
        total_checks,
        result.checks_required,
    )

    for check in checks:
        logger.debug(
            "[CHART_GUARDRAIL] Token %s check '%s': %s - %s",
            address[:8],
            check.name,
            "PASS" if check.passed else "FAIL",
            check.reason,
        )

    return result


def format_guardrail_summary(result: GuardrailEvaluationResult) -> str:
    lines = []
    lines.append(f"Guardrail Evaluation: {'PASS' if result.passed else 'FAIL'}")
    lines.append(
        f"Checks: {result.checks_passed}/{len(result.checks)} passed ({result.checks_required} required)"
    )

    if not result.passed:
        lines.append("Failed checks:")
        for check in result.get_failed_checks():
            lines.append(f" - {check.name}: {check.actual_value} (need {check.threshold_value})")

    return "\n".join(lines)
