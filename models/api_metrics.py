from __future__ import annotations

import logging

from models.base import BaseModel

logger = logging.getLogger(__name__)


class ApiMetricsModel(BaseModel):
    async def record_check(self, api_name: str, success: bool) -> None:
        error_inc = 0 if success else 1
        try:
            await self.db.execute(
                """
                INSERT INTO api_request_metrics (api_name, total_checks, total_errors, updated_at)
                VALUES ($1, 1, $2, NOW())
                ON CONFLICT (api_name) DO UPDATE
                SET total_checks = api_request_metrics.total_checks + 1,
                    total_errors = api_request_metrics.total_errors + $2,
                    updated_at = NOW()
                """,
                api_name,
                error_inc,
            )
            await self.db.execute(
                """
                INSERT INTO api_request_metrics_daily (api_name, day, total_checks, total_errors, updated_at)
                VALUES ($1, (NOW() AT TIME ZONE 'UTC')::date, 1, $2, NOW())
                ON CONFLICT (api_name, day) DO UPDATE
                SET total_checks = api_request_metrics_daily.total_checks + 1,
                    total_errors = api_request_metrics_daily.total_errors + $2,
                    updated_at = NOW()
                """,
                api_name,
                error_inc,
            )
            await self.db.execute(
                """
                INSERT INTO api_request_metrics_hourly (api_name, hour_ts, total_checks, total_errors, updated_at)
                VALUES ($1, date_trunc('hour', NOW() AT TIME ZONE 'UTC'), 1, $2, NOW())
                ON CONFLICT (api_name, hour_ts) DO UPDATE
                SET total_checks = api_request_metrics_hourly.total_checks + 1,
                    total_errors = api_request_metrics_hourly.total_errors + $2,
                    updated_at = NOW()
                """,
                api_name,
                error_inc,
            )
        except Exception as exc:
            logger.debug("Failed to record API metrics for %s: %s", api_name, exc)

    async def get_all(self) -> list:
        return await self.db.fetch(
            "SELECT api_name, total_checks, total_errors FROM api_request_metrics ORDER BY api_name"
        )

    async def get_daily(self) -> list:
        return await self.db.fetch(
            """
            SELECT api_name, total_checks, total_errors
            FROM api_request_metrics_daily
            WHERE day = (NOW() AT TIME ZONE 'UTC')::date
            ORDER BY api_name
            """
        )

    async def get_last_24h(self) -> list:
        return await self.db.fetch(
            """
            SELECT api_name,
                   SUM(total_checks) AS total_checks,
                   SUM(total_errors) AS total_errors
            FROM api_request_metrics_hourly
            WHERE hour_ts >= (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'
            GROUP BY api_name
            ORDER BY api_name
            """
        )
