from __future__ import annotations

import asyncio
import heapq
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple, Optional, List

from config import settings
from db import db
from models.snapshot_tasks import SnapshotTasksModel
from services.snapshot_executor import SnapshotExecutor
from services import get_jupiter_service, get_dexpaprika_service, get_dexscreener_client
from models.analytics import AnalyticsModel
from models.token import TokenModel

logger = logging.getLogger(__name__)


class SnapshotScheduler:
    def __init__(self) -> None:
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._heap: List[Tuple[datetime, int]] = []
        self._scheduled: Dict[int, datetime] = {}
        self.snapshot_model = SnapshotTasksModel(db)
        self.analytics_model = AnalyticsModel(db)
        self.jupiter = get_jupiter_service()
        self.dexpaprika = get_dexpaprika_service()
        self.dex = get_dexscreener_client()
        self.token_model = TokenModel()
        self.executor = SnapshotExecutor()

        self.tolerance_minutes = settings.snapshot_tolerance_minutes
        self.late_grace_minutes = settings.snapshot_late_grace_minutes

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[SNAPSHOT] Scheduler started")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[SNAPSHOT] Scheduler stopped")

    def schedule(self, task_id: int, target_time: datetime) -> None:
        target_time = target_time if target_time.tzinfo else target_time.replace(tzinfo=timezone.utc)
        prev = self._scheduled.get(task_id)
        if prev is None or target_time != prev or prev <= datetime.now(timezone.utc):
            self._scheduled[task_id] = target_time
            heapq.heappush(self._heap, (target_time, task_id))

    async def enqueue_due_tasks(self) -> None:
        now = datetime.now(timezone.utc)
        rows = await self.snapshot_model.fetch_due(now, self.late_grace_minutes, limit=500)
        for row in rows:
            self.schedule(row["id"], row["target_time"])

    async def _loop(self) -> None:
        try:
            while self.running:
                try:
                    await self.enqueue_due_tasks()
                    now = datetime.now(timezone.utc)
                    due: List[int] = []
                    while self._heap and self._heap[0][0] <= now:
                        _, task_id = heapq.heappop(self._heap)
                        if self._scheduled.get(task_id) is None:
                            continue
                        due.append(task_id)
                    if due:
                        tasks = [self._process_task(task_id) for task_id in due]
                        await asyncio.gather(*tasks, return_exceptions=True)
                    await asyncio.sleep(1)
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.error("[SNAPSHOT] Loop error: %s", exc, exc_info=True)
                    await asyncio.sleep(5)
        finally:
            logger.info("[SNAPSHOT] Loop exited")

    async def _process_task(self, task_id: int) -> None:
        task = await db.fetchrow("SELECT * FROM snapshot_tasks WHERE id = $1", task_id)
        if not task:
            self._scheduled.pop(task_id, None)
            return

        target_time = task["target_time"]
        status = task["status"]
        now = datetime.now(timezone.utc)

        # Skip if already successful/late-success
        if status == "success":
            self._scheduled.pop(task_id, None)
            return

        late_deadline = target_time + timedelta(minutes=self.late_grace_minutes)
        if now > late_deadline:
            await self.snapshot_model.mark_result(task_id, "failed", last_error_message="missed_grace")
            self._scheduled.pop(task_id, None)
            return

        # Mark due when inside tolerance window
        if status == "pending" and now >= target_time - timedelta(minutes=self.tolerance_minutes):
            await self.snapshot_model.set_status(task_id, "due")

        await self.executor.execute(task_id)

        # Clean cache if terminal
        new_status = await db.fetchval("SELECT status FROM snapshot_tasks WHERE id = $1", task_id)
        if new_status in ("success", "failed", "late"):
            self._scheduled.pop(task_id, None)
