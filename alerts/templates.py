from __future__ import annotations

import re
from typing import Set


REQUIRED_GAIN_TEMPLATE_PLACEHOLDERS: Set[str] = set()

DEFAULT_GAIN_ALERT_TEMPLATE = (
    "{gain_emoji} ${token_symbol} {multiplier} | 💹From {first_market_cap} ↗️ {current_market_cap} within {elapsed_time}\n"
    "🔗 CA: {address}\n"
    "⚠️ Gain alerts are in beta and may be inaccurate."
)

_PLACEHOLDER_PATTERN = re.compile(r"{(\w+)}")


def missing_required_placeholders(template_text: str) -> Set[str]:
    found = set(_PLACEHOLDER_PATTERN.findall(template_text or ""))
    return REQUIRED_GAIN_TEMPLATE_PLACEHOLDERS - found


def normalise_template(template_text: str) -> str:
    return (template_text or "").strip()
