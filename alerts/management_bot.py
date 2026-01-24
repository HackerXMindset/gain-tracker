"""
Management bot wrapper for sending gain alerts.
"""

import logging
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)


class ManagementBot:
    def __init__(self, token: str) -> None:
        self.bot = Bot(token=token)

    async def close(self) -> None:
        await self.bot.session.close()

    async def send_message(
        self,
        chat_id: int,
        message: str,
        reply_to_message_id: Optional[int] = None,
        photo_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        try:
            if photo_bytes:
                input_file = BufferedInputFile(photo_bytes, filename="chart.jpg")
                sent_message = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=input_file,
                    caption=message,
                    reply_to_message_id=reply_to_message_id,
                )
            else:
                sent_message = await self.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_to_message_id=reply_to_message_id,
                    disable_web_page_preview=True,
                )
            return {"success": True, "message_id": getattr(sent_message, "message_id", None)}
        except Exception as exc:
            logger.error("Management bot failed to send to chat %s: %s", chat_id, exc, exc_info=True)
            return {"success": False, "error": str(exc)}
