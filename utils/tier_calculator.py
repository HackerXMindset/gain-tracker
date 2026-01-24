"""
Tier Calculator - Determines monitoring tier based on token age.
"""

from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

TIER_DEFINITIONS = [
    ("tier_a", 10 * 60, 10),
    ("tier_b", 30 * 60, 30),
    ("tier_c", 2 * 60 * 60, 3 * 60),
    ("tier_d", 6 * 60 * 60, 5 * 60),
    ("tier_e", 24 * 60 * 60, 10 * 60),
    ("tier_f", 7 * 24 * 60 * 60, 30 * 60),
]


def calculate_tier_from_age(first_seen_at: datetime, current_time: Optional[datetime] = None) -> Tuple[str, int]:
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    if first_seen_at.tzinfo is None:
        first_seen_at = first_seen_at.replace(tzinfo=timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    age_seconds = (current_time - first_seen_at).total_seconds()

    for tier_name, max_age, poll_interval in TIER_DEFINITIONS:
        if age_seconds < max_age:
            return (tier_name, poll_interval)

    logger.debug("Token age %ss exceeds all tiers, using 1h polling", age_seconds)
    return ("tier_f", 60 * 60)


def get_poll_interval_for_tier(tier: str) -> int:
    for tier_name, _, poll_interval in TIER_DEFINITIONS:
        if tier_name == tier:
            return poll_interval
    logger.warning("Unknown tier '%s', defaulting to 1h poll interval", tier)
    return 60 * 60


def calculate_next_poll_time(first_seen_at: datetime, current_time: Optional[datetime] = None) -> Tuple[str, datetime]:
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    tier_name, poll_interval = calculate_tier_from_age(first_seen_at, current_time)
    next_poll = current_time + timedelta(seconds=poll_interval)
    return (tier_name, next_poll)


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"
