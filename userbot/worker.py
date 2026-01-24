"""
Userbot Worker - minimal orchestrator for gain alert monitoring.
"""

import logging
from typing import Dict, Any

from models import BotModel
from db import db
from userbot.message_handler import MessageHandler
from userbot.call_executor import CallExecutor
from userbot.session_manager import SessionManager

logger = logging.getLogger(__name__)


class UserbotWorker:
    def __init__(self, userbot_id: int, session_string: str) -> None:
        self.userbot_id = userbot_id
        self.session_string = session_string
        self.running = False
        self.bot_model = BotModel(db)
        self.session_manager = SessionManager(userbot_id, session_string)
        self.message_handler = MessageHandler(userbot_id, self.session_manager)
        self.call_executor = CallExecutor(userbot_id, self.session_manager)

    async def start(self) -> None:
        if self.running:
            logger.warning("Userbot %s already running", self.userbot_id)
            return

        if not await self.session_manager.initialize_client():
            await self.bot_model.set_status(self.userbot_id, "error")
            raise RuntimeError("Failed to initialize Telegram client")

        me = await self.session_manager.get_me()
        await self.bot_model.update_identity(
            self.userbot_id,
            me.id,
            me.username,
            me.first_name,
            me.last_name,
        )

        await self.message_handler.setup_event_handlers()
        await self.bot_model.set_status(self.userbot_id, "active")
        self.running = True
        logger.info("Userbot %s started", self.userbot_id)

    async def stop(self) -> None:
        if not self.running:
            return

        await self.session_manager.disconnect_client()
        await self.bot_model.set_status(self.userbot_id, "inactive")
        self.running = False
        logger.info("Userbot %s stopped", self.userbot_id)

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def get_worker_info(self) -> Dict[str, Any]:
        return {
            "userbot_id": self.userbot_id,
            "running": self.running,
            "user_info": self.session_manager.get_user_info(),
        }

    async def health_check(self) -> Dict[str, Any]:
        if not self.running:
            return {"healthy": False, "error": "Worker not running"}

        info = self.session_manager.get_user_info()
        if not info.get("connected"):
            return {"healthy": False, "error": "Client disconnected", "session": info}

        return {"healthy": True, "session": info}
