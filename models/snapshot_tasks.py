from __future__ import annotations

import logging
from typing import Optional, List
from datetime import datetime, timedelta

import asyncpg

from models.base import BaseModel

logger = logging.getLogger(__name__)


class SnapshotTasksModel(BaseModel):
    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)

    async def create_or_get(self, token_id: int, timeframe_seconds: int, target_time: datetime) -> asyncpg.Record:
        return await self.db.fetchrow(
            """
            INSERT INTO snapshot_tasks (token_id, timeframe_seconds, target_time, status)
            VALUES ($1, $2, $3, 'pending')
            ON CONFLICT (token_id, timeframe_seconds, target_time)
            DO UPDATE SET target_time = EXCLUDED.target_time
            RETURNING *
            """,
            token_id,
            timeframe_seconds,
            target_time,
        )

    async def mark_result(
        self,
        task_id: int,
        status: str,
        recorded_mc: Optional[float] = None,
        recorded_source: Optional[str] = None,
        last_error_api: Optional[str] = None,
        last_error_code: Optional[int] = None,
        last_error_message: Optional[str] = None,
    ) -> None:
        await self.db.execute(
            """
            UPDATE snapshot_tasks
            SET status = $2,
                recorded_mc = COALESCE($3, recorded_mc),
                recorded_source = COALESCE($4, recorded_source),
                last_error_api = $5,
                last_error_code = $6,
                last_error_message = $7,
                last_error_at = CASE WHEN $5 IS NOT NULL THEN NOW() ELSE last_error_at END,
                attempts = attempts + 1,
                updated_at = NOW()
            WHERE id = $1
            """,
            task_id,
            status,
            recorded_mc,
            recorded_source,
            last_error_api,
            last_error_code,
            last_error_message,
        )

    async def fetch_due(self, now: datetime, late_grace_minutes: int, limit: int = 100) -> List[asyncpg.Record]:
        return await self.db.fetch(
            """
            SELECT *
            FROM snapshot_tasks
            WHERE status IN ('pending','due','failed','late')
              AND target_time <= $1 + ($2 || ' minutes')::interval
            ORDER BY target_time ASC
            LIMIT $3
            """,
            now,
            late_grace_minutes,
            limit,
        )

    async def backfill_for_token(self, token_id: int, first_seen_at: datetime, timeframes: List[int]) -> None:
        for seconds in timeframes:
            target_time = first_seen_at + timedelta(seconds=seconds)
            await self.create_or_get(token_id, seconds, target_time)

    async def set_status(self, task_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE snapshot_tasks SET status = $2, updated_at = NOW() WHERE id = $1",
            task_id,
            status,
        )
