"""
Userbot Manager - manages userbot workers for gain alert monitoring.
"""

import asyncio
import logging
from typing import Dict, Optional

from models import BotModel
from db import db
from userbot.worker import UserbotWorker

logger = logging.getLogger(__name__)


class UserbotManager:
    def __init__(self) -> None:
        self.workers: Dict[int, UserbotWorker] = {}
        self.bot_model = BotModel(db)
        self.running = False
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_all_workers(self) -> None:
        self.running = True
        userbots = await self.bot_model.get_active_userbots()

        startup_tasks = []
        for userbot in userbots:
            session_string = userbot.get("session_string")
            if session_string:
                startup_tasks.append(self.start_worker(userbot["id"], session_string))

        if startup_tasks:
            await asyncio.gather(*startup_tasks, return_exceptions=True)

        logger.info("Started %s userbot worker(s)", len(self.workers))

    async def start_worker(self, userbot_id: int, session_string: str) -> None:
        if userbot_id in self.workers:
            logger.warning("Userbot %s already running", userbot_id)
            return

        worker = UserbotWorker(userbot_id, session_string)
        await worker.start()
        self.workers[userbot_id] = worker
        logger.info("Started userbot worker %s", userbot_id)

    async def stop_worker(self, userbot_id: int) -> None:
        worker = self.workers.get(userbot_id)
        if not worker:
            return
        await worker.stop()
        self.workers.pop(userbot_id, None)

    async def restart_worker(self, userbot_id: int) -> None:
        worker = self.workers.get(userbot_id)
        if worker:
            await worker.restart()
            return

        userbot = await self.bot_model.get_by_id(userbot_id)
        if userbot and userbot.get("session_string"):
            await self.start_worker(userbot_id, userbot["session_string"])

    async def stop_all_workers(self) -> None:
        self.running = False
        stop_tasks = [self.stop_worker(uid) for uid in list(self.workers.keys())]
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        logger.info("Stopped all userbot workers")

    def get_all_workers(self) -> Dict[int, UserbotWorker]:
        return self.workers

    def get_worker(self, userbot_id: int) -> Optional[UserbotWorker]:
        return self.workers.get(userbot_id)

    async def sync_workers_with_database(self) -> None:
        db_userbots = await self.bot_model.get_active_userbots()
        db_userbot_ids = {u["id"] for u in db_userbots if u.get("session_string")}

        running_ids = set(self.workers.keys())

        to_start = db_userbot_ids - running_ids
        for userbot_id in to_start:
            userbot = next(u for u in db_userbots if u["id"] == userbot_id)
            await self.start_worker(userbot_id, userbot["session_string"])

        to_stop = running_ids - db_userbot_ids
        for userbot_id in to_stop:
            await self.stop_worker(userbot_id)

        logger.info("Synced workers: started %s, stopped %s", len(to_start), len(to_stop))
