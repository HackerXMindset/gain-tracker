"""
Message Handler - Processes incoming messages for gain alert monitoring.
"""

import logging
from typing import Any, Dict, Optional

from telethon import events

from models import MonitoredSourceModel
from scheduler import get_dex_service
from userbot.token_monitor import TokenMonitor
from userbot.utils import UserbotUtils
from db import db

logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, userbot_id: int, session_manager) -> None:
        self.userbot_id = userbot_id
        self.session_manager = session_manager
        self.db = db
        self.monitored_source_model = MonitoredSourceModel(db)
        self.token_monitor = TokenMonitor(userbot_id)
        self.utils = UserbotUtils()

    async def setup_event_handlers(self) -> None:
        client = self.session_manager.get_client()
        if not client:
            logger.error("Cannot setup handlers - client not available")
            return

        @client.on(events.NewMessage())
        async def handle_all_messages(event):
            await self._process_event(event, is_edit=False)

        @client.on(events.MessageEdited())
        async def handle_all_edited(event):
            await self._process_event(event, is_edit=True)

        logger.info("Setup event handlers for incoming and edited messages")

    async def _process_event(self, event, is_edit: bool = False) -> None:
        direction = "outgoing" if event.out else "incoming"
        if is_edit or direction != "incoming":
            return

        try:
            dex_service = get_dex_service()
            chart_fetcher = getattr(dex_service, "chart_fetcher", None)
            if chart_fetcher:
                await chart_fetcher.handle_chart_bot_reply(event.message)
        except Exception as exc:
            logger.debug("[CHART_FETCH] Error handling chart reply: %s", exc)

        await self._handle_monitored_gain_alert(event)

    async def _handle_monitored_gain_alert(self, event) -> None:
        chat_id = event.chat_id
        sender_id = event.sender_id if hasattr(event, "sender_id") else None

        try:
            monitored = None
            if sender_id is not None:
                monitored = await self.monitored_source_model.is_monitored(chat_id, sender_id)

            if not monitored:
                monitored = await self.monitored_source_model.is_monitored(chat_id, None)

            if not monitored:
                return

            # Check if this userbot should track this source
            tracking_userbot_id = monitored.get("tracking_userbot_id")
            if tracking_userbot_id is not None and tracking_userbot_id != self.userbot_id:
                tracking_fallback = monitored.get("tracking_fallback_enabled", True)
                if not tracking_fallback:
                    logger.debug(
                        "[MONITOR_DETECT] Skipping chat %s - assigned to userbot %s (fallback disabled)",
                        chat_id,
                        tracking_userbot_id,
                    )
                    return
                assigned_active = await self.monitored_source_model.is_userbot_active(tracking_userbot_id)
                if assigned_active:
                    logger.debug(
                        "[MONITOR_DETECT] Skipping chat %s - assigned userbot %s is online",
                        chat_id,
                        tracking_userbot_id,
                    )
                    return
                logger.info(
                    "[MONITOR_DETECT] Fallback tracking chat %s (userbot %s offline)",
                    chat_id,
                    tracking_userbot_id,
                )

            if monitored["chat_type"] == "group" and monitored["user_id"] != sender_id:
                logger.debug(
                    "[MONITOR_DETECT] Skipping chat %s user %s; expected %s",
                    chat_id,
                    sender_id,
                    monitored["user_id"],
                )
                return

            message = event.message
            text = self.utils.get_message_text(message)

            if not text:
                logger.debug("[MONITOR_DETECT] Chat %s message has no text/content", chat_id)
                return

            addresses = self.utils.extract_token_addresses(text)
            if not addresses:
                logger.debug("[MONITOR_DETECT] Chat %s message has no contract addresses", chat_id)
                return

            logger.info(
                "[MONITOR_DETECT] Chat %s matched monitored %s entry %s; found %s address(es)",
                chat_id,
                monitored["chat_type"],
                monitored["id"],
                len(addresses),
            )

            tracked_user_id = monitored.get("user_id")

            for address, blockchain in addresses:
                await self.token_monitor.process_monitored_token(
                    address=address,
                    blockchain=blockchain,
                    chat_id=chat_id,
                    message_id=message.id if message else None,
                    user_id=tracked_user_id,
                    chat_type=monitored["chat_type"],
                )

        except Exception as exc:
            logger.error(
                "[MONITOR_DETECT] Error handling monitored source message in chat %s: %s",
                chat_id,
                exc,
                exc_info=True,
            )
