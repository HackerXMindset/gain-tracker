from __future__ import annotations

import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

from config import settings
from models import AutoTraderRunModel, AutoTraderEventModel

logger = logging.getLogger(__name__)


class AutoTraderService:
    """
    Placeholder service for AutoTrader.
    Phase 3/4 engine will plug real trading here; for now we transition runs and log.
    """

    def __init__(self) -> None:
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.runs = AutoTraderRunModel()
        self.events = AutoTraderEventModel()

    async def start(self) -> None:
        if self.running:
            return
        if not settings.enable_autotrader:
            logger.info("[AUTOTRADER] Disabled via config.")
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="autotrader_service")
        logger.info("[AUTOTRADER] Service started")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[AUTOTRADER] Service stopped")

    async def _loop(self) -> None:
        while self.running:
            try:
                await self._process_pending()
                await self._process_running()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[AUTOTRADER] Loop error: %s", exc, exc_info=True)
                await asyncio.sleep(5)

    async def _process_pending(self) -> None:
        rows = await self.runs.db.fetch(
            "SELECT * FROM autotrader_runs WHERE status='pending' ORDER BY created_at ASC LIMIT 5"
        )
        for row in rows:
            run_id = row["id"]
            await self.runs.update_status(run_id, "running")
            await self.events.log(run_id, "info", "Run started")

    async def _process_running(self) -> None:
        rows = await self.runs.db.fetch(
            "SELECT * FROM autotrader_runs WHERE status='running' ORDER BY updated_at ASC LIMIT 10"
        )
        for row in rows:
            run_id = row["id"]
            # Placeholder: in next phase, process coins. For now, complete immediately.
            await self.events.log(run_id, "info", "Run completed (engine placeholder)")
            await self.runs.update_status(run_id, "completed")
