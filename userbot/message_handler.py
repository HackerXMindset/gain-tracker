"""
Message Handler - Processes incoming messages for gain alert monitoring.
"""

import logging
import time
from typing import Any, Dict

from telethon import events

from models import (
    MonitoredSourceModel,
    CommandForwardingRuleModel,
    CommandTrackedMessageModel,
    GroupModel,
)
from scheduler import get_dex_service
from userbot.token_monitor import TokenMonitor
from userbot.utils import UserbotUtils
from userbot.command_handler import handle_potential_custom_reply, track_outgoing_command
from db import db

logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, userbot_id: int, session_manager) -> None:
        self.userbot_id = userbot_id
        self.session_manager = session_manager
        self.db = db
        self.monitored_source_model = MonitoredSourceModel(db)
        self.cmd_fwd_model = CommandForwardingRuleModel(db)
        self.cmd_tracked_model = CommandTrackedMessageModel(db)
        self.group_model = GroupModel(db)
        self.token_monitor = TokenMonitor(userbot_id)
        self.utils = UserbotUtils()
        self.cache: Dict[str, Any] = {}
        self.cache_time: Dict[str, float] = {}

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

        message = event.message
        raw_text = self.utils.get_message_text(message)
        sender_id = event.sender_id if hasattr(event, "sender_id") else None
        chat_id = event.chat_id
        snippet = (raw_text[:300] + "…") if raw_text and len(raw_text) > 300 else raw_text
        logger.info(
            "[MSG_RX] chat=%s sender=%s msg_id=%s text=%r",
            chat_id,
            sender_id,
            getattr(message, "id", None),
            snippet,
        )

        try:
            dex_service = get_dex_service()
            chart_fetcher = getattr(dex_service, "chart_fetcher", None)
            if chart_fetcher:
                await chart_fetcher.handle_chart_bot_reply(event.message)
        except Exception as exc:
            logger.debug("[CHART_FETCH] Error handling chart reply: %s", exc)

        await self._handle_monitored_gain_alert(event)
        await handle_potential_custom_reply(self, event)

    def is_fresh(self, cache_key: str, seconds: int = 60) -> bool:
        last = self.cache_time.get(cache_key)
        if not last:
            return False
        return (time.time() - last) < seconds

    async def track_outgoing_command(self, chat_id: int, message_id: int, command_text: str) -> None:
        await track_outgoing_command(self, chat_id, message_id, command_text)

    async def handle_outgoing_command(self, chat_id: int, message_id: int, command_text: str) -> None:
        await track_outgoing_command(self, chat_id, message_id, command_text)

    async def _handle_monitored_gain_alert(self, event) -> None:
        chat_id = event.chat_id
        sender_id = event.sender_id if hasattr(event, "sender_id") else None

        try:
            message = event.message
            text = self.utils.get_message_text(message)

            if not text:
                logger.debug("[MONITOR_DETECT] Chat %s message has no text/content", chat_id)
                return

            addresses = self.utils.extract_token_addresses(text)
            if not addresses:
                logger.debug("[MONITOR_DETECT] Chat %s message has no contract addresses", chat_id)
                return

            monitored = await self.monitored_source_model.get_matching_source(chat_id, sender_id)

            if not monitored:
                cache_key = f"no_source:{chat_id}"
                if not self.is_fresh(cache_key, seconds=120):
                    logger.warning(
                        "[MONITOR_DETECT] Address(es) detected in chat %s but chat is not registered as a monitored source; skipping",
                        chat_id,
                    )
                    self.cache_time[cache_key] = time.time()
                return

            if monitored.get("tracking_enabled") is False:
                logger.debug(
                    "[MONITOR_DETECT] Tracking disabled for chat %s (source %s)",
                    chat_id,
                    monitored.get("id"),
                )
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

            if monitored["chat_type"] == "group" and monitored.get("user_id") is not None and monitored["user_id"] != sender_id:
                logger.debug(
                    "[MONITOR_DETECT] Skipping chat %s user %s; expected %s",
                    chat_id,
                    sender_id,
                    monitored["user_id"],
                )
                return

            if monitored["chat_type"] == "group" and monitored.get("user_id") is None and sender_id is not None:
                if await self.monitored_source_model.is_user_excluded(chat_id, sender_id):
                    logger.debug(
                        "[MONITOR_DETECT] Skipping excluded user %s in chat %s",
                        sender_id,
                        chat_id,
                    )
                    return

            logger.info(
                "[MONITOR_DETECT] Chat %s matched monitored %s entry %s; found %s address(es)",
                chat_id,
                monitored["chat_type"],
                monitored["id"],
                len(addresses),
            )

            tracked_user_id = monitored.get("user_id")
            if monitored.get("chat_type") == "group" and tracked_user_id is None:
                tracked_user_id = sender_id

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
