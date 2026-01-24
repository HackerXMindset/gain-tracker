from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from alerts.templates import DEFAULT_GAIN_ALERT_TEMPLATE, normalise_template
from config import (
    CHART_GUARDRAILS_KEY,
    DEFAULT_CHART_GUARDRAILS,
    DEFAULT_GLOBAL_CHART_THRESHOLD,
    DROP_FLOOR_MC_DEFAULT,
    DROP_THRESHOLD_DEFAULT_PCT,
    GAIN_ALERT_TEMPLATE_KEY,
    GAIN_THRESHOLD_DEFAULT_PCT,
    GLOBAL_CHART_BOT_ID_KEY,
    GLOBAL_CHART_THRESHOLD_KEY,
    GUARDRAIL_SOURCE_MAP,
)
from models.base import BaseModel

logger = logging.getLogger(__name__)

_GAIN_TEMPLATE_CACHE: Optional[str] = None


class SettingsModel(BaseModel):
    async def get_gain_alert_settings(self) -> Dict[str, float]:
        try:
            gain_threshold = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                "gain_threshold_pct",
            )
            drop_threshold = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                "drop_threshold_pct",
            )
            drop_floor = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                "drop_floor_mc",
            )
            return {
                "gain_threshold_pct": float(gain_threshold) if gain_threshold else GAIN_THRESHOLD_DEFAULT_PCT,
                "drop_threshold_pct": float(drop_threshold) if drop_threshold else DROP_THRESHOLD_DEFAULT_PCT,
                "drop_floor_mc": float(drop_floor) if drop_floor else DROP_FLOOR_MC_DEFAULT,
            }
        except Exception as exc:
            logger.warning(
                "Failed to load gain alert settings from DB, using defaults: %s",
                exc,
            )
            return {
                "gain_threshold_pct": GAIN_THRESHOLD_DEFAULT_PCT,
                "drop_threshold_pct": DROP_THRESHOLD_DEFAULT_PCT,
                "drop_floor_mc": DROP_FLOOR_MC_DEFAULT,
            }

    async def set_gain_threshold_pct(self, threshold_pct: float) -> None:
        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, to_jsonb($2::numeric))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            "gain_threshold_pct",
            threshold_pct,
        )

    async def set_drop_threshold_pct(self, threshold_pct: float) -> None:
        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, to_jsonb($2::numeric))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            "drop_threshold_pct",
            threshold_pct,
        )

    async def set_drop_floor_mc(self, floor_mc: float) -> None:
        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, to_jsonb($2::numeric))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            "drop_floor_mc",
            floor_mc,
        )

    async def get_gain_alert_template_text(self) -> str:
        global _GAIN_TEMPLATE_CACHE

        if _GAIN_TEMPLATE_CACHE is not None:
            return _GAIN_TEMPLATE_CACHE

        try:
            template = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                GAIN_ALERT_TEMPLATE_KEY,
            )

            if isinstance(template, str) and template.startswith("\"") and template.endswith("\""):
                try:
                    template = json.loads(template)
                except json.JSONDecodeError:
                    logger.debug("Template stored with extra quotes; using raw string.")

            template = normalise_template(template) if template else ""
            if not template:
                return DEFAULT_GAIN_ALERT_TEMPLATE

            _GAIN_TEMPLATE_CACHE = template
            return template
        except Exception as exc:
            logger.warning(
                "Failed to load gain alert template from DB (%s). Using default.",
                exc,
            )
            _GAIN_TEMPLATE_CACHE = DEFAULT_GAIN_ALERT_TEMPLATE
            return _GAIN_TEMPLATE_CACHE

    async def set_gain_alert_template_text(self, template: str) -> None:
        cleaned = normalise_template(template)
        if not cleaned:
            cleaned = DEFAULT_GAIN_ALERT_TEMPLATE

        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, to_jsonb($2::text))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            GAIN_ALERT_TEMPLATE_KEY,
            cleaned,
        )

        global _GAIN_TEMPLATE_CACHE
        _GAIN_TEMPLATE_CACHE = cleaned

    async def get_global_chart_settings(self) -> Dict[str, Any]:
        defaults = {
            "chart_threshold_override": None,
            "chart_threshold_default": DEFAULT_GLOBAL_CHART_THRESHOLD,
            "chart_bot_id": None,
        }

        try:
            threshold_raw = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                GLOBAL_CHART_THRESHOLD_KEY,
            )
            bot_id_raw = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                GLOBAL_CHART_BOT_ID_KEY,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load global chart settings from DB (%s). Using defaults.",
                exc,
            )
            return defaults

        if threshold_raw is not None:
            try:
                defaults["chart_threshold_override"] = Decimal(str(threshold_raw))
            except (InvalidOperation, TypeError, ValueError):
                logger.warning("Invalid global chart threshold value %s; ignoring.", threshold_raw)

        if bot_id_raw is not None:
            try:
                defaults["chart_bot_id"] = int(bot_id_raw)
            except (TypeError, ValueError):
                logger.warning("Invalid global chart bot id %s; ignoring.", bot_id_raw)

        return defaults

    async def set_global_chart_settings(
        self,
        *,
        chart_threshold: Optional[float] = None,
        chart_bot_id: Optional[int] = None,
    ) -> None:
        if chart_threshold is not None:
            await self.db.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ($1, to_jsonb($2::numeric))
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                GLOBAL_CHART_THRESHOLD_KEY,
                chart_threshold,
            )
        if chart_bot_id is not None:
            await self.db.execute(
                """
                INSERT INTO settings (key, value)
                VALUES ($1, to_jsonb($2::bigint))
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                GLOBAL_CHART_BOT_ID_KEY,
                chart_bot_id,
            )

    async def set_global_chart_threshold(self, threshold: Optional[float]) -> None:
        if threshold is None:
            await self.db.execute(
                "DELETE FROM settings WHERE key = $1",
                GLOBAL_CHART_THRESHOLD_KEY,
            )
            return

        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, to_jsonb($2::numeric))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            GLOBAL_CHART_THRESHOLD_KEY,
            threshold,
        )

    async def set_global_chart_bot_id(self, bot_id: Optional[int]) -> None:
        if bot_id is None:
            await self.db.execute(
                "DELETE FROM settings WHERE key = $1",
                GLOBAL_CHART_BOT_ID_KEY,
            )
            return

        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, to_jsonb($2::bigint))
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            GLOBAL_CHART_BOT_ID_KEY,
            bot_id,
        )

    async def get_chart_guardrails(self) -> Dict[str, Any]:
        guardrails = DEFAULT_CHART_GUARDRAILS.copy()

        try:
            raw_value = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = $1",
                CHART_GUARDRAILS_KEY,
            )
        except Exception as exc:
            logger.warning("Failed to load chart guardrails from DB (%s); using defaults.", exc)
            return guardrails

        if raw_value is None:
            return guardrails

        if isinstance(raw_value, str):
            try:
                raw_value = json.loads(raw_value)
            except json.JSONDecodeError:
                logger.warning("Chart guardrails stored as invalid JSON string; using defaults.")
                return guardrails

        if not isinstance(raw_value, dict):
            logger.warning("Unexpected chart guardrails payload type %s; using defaults.", type(raw_value).__name__)
            return guardrails

        for key, default_value in DEFAULT_CHART_GUARDRAILS.items():
            if key not in raw_value or raw_value[key] is None:
                continue
            try:
                guardrails[key] = _coerce_guardrail_value(key, raw_value[key])
            except ValueError as exc:
                logger.warning(
                    "Invalid chart guardrail value for %s: %s (fallback=%s)",
                    key,
                    exc,
                    default_value,
                )

        return guardrails

    async def set_chart_guardrails(self, updates: Dict[str, Any]) -> None:
        if not isinstance(updates, dict):
            raise ValueError("Chart guardrail updates must be provided as a dict.")

        current = await self.get_chart_guardrails()
        merged = current.copy()

        for key, value in updates.items():
            if key not in DEFAULT_CHART_GUARDRAILS:
                logger.debug("Ignoring unknown guardrail key %s", key)
                continue
            if value is None:
                merged[key] = DEFAULT_CHART_GUARDRAILS[key]
                continue
            merged[key] = _coerce_guardrail_value(key, value)

        await self.db.execute(
            """
            INSERT INTO settings (key, value)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """,
            CHART_GUARDRAILS_KEY,
            json.dumps(merged),
        )

    async def resolve_chart_guardrails(self, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        guardrails = await self.get_chart_guardrails()

        if not source:
            return guardrails

        overrides: Dict[str, Any] = {}
        for key, source_field in GUARDRAIL_SOURCE_MAP.items():
            if source_field in source and source[source_field] is not None:
                overrides[key] = source[source_field]

        if not overrides:
            return guardrails

        merged = guardrails.copy()
        for key, value in overrides.items():
            try:
                merged[key] = _coerce_guardrail_value(key, value)
            except ValueError as exc:
                logger.warning("Invalid override for %s: %s (keeping global value)", key, exc)

        return merged


def clear_gain_alert_template_cache() -> None:
    global _GAIN_TEMPLATE_CACHE
    _GAIN_TEMPLATE_CACHE = None


def _coerce_guardrail_value(key: str, value: Any) -> Any:
    if value is None:
        return None

    if key in {"min_age_minutes", "checks_required"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid integer for {key}: {value}")

    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid number for {key}: {value}")

    return numeric
