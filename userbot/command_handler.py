"""
Command Handler - Forward replies to tracked command messages.
"""

import logging
import traceback
from typing import List, Dict, Any

from telethon.errors import MessageIdInvalidError

from userbot.entity_utils import resolve_entity_safely, post_forward_timestamp

logger = logging.getLogger(__name__)


async def handle_potential_custom_reply(handler, event):
    """Forward replies to tracked command messages."""
    try:
        if not event.message.reply_to_msg_id:
            return

        tracked_messages = await handler.cmd_tracked_model.get_tracked_messages_for_reply(
            event.message.reply_to_msg_id,
            event.chat_id,
        )
        if not tracked_messages:
            return

        for tracked in tracked_messages:
            rule = await handler.cmd_fwd_model.get_by_id(tracked["rule_id"])
            if not rule or not rule["enabled"]:
                continue

            if handler.userbot_id != rule.get("forwarding_userbot_id"):
                continue

            if "Fetching leader board..." in (event.message.text or ""):
                continue

            allowed_reply_users = rule.get("allowed_reply_user_ids", [])
            if allowed_reply_users and event.sender_id not in allowed_reply_users:
                continue

            success = await forward_custom_reply(handler, rule, event.message)
            if success:
                logger.debug(
                    "[CMD_FWD] Forwarded reply %s for rule %s",
                    event.message.id,
                    rule["id"],
                )
    except Exception as exc:
        logger.error("[CMD_FWD] Error handling reply: %s", exc)
        logger.error("[CMD_FWD] Full traceback: %s", traceback.format_exc())


async def forward_custom_reply(handler, rule: dict, message) -> bool:
    try:
        if handler.userbot_id != rule.get("forwarding_userbot_id"):
            return False

        client = handler.session_manager.get_client()
        if not client:
            logger.error("[CMD_FWD] No client available for forwarding")
            return False

        excluded_texts = rule.get("excluded_message_texts", []) or []
        if message.text and excluded_texts and message.text in excluded_texts:
            return False

        entity = await resolve_entity_safely(client, rule["destination_channel_id"])

        try:
            await client.forward_messages(entity=entity, messages=message)
        except MessageIdInvalidError:
            logger.warning("[CMD_FWD] Could not forward message %s: message ID invalid", message.id)
            return False

        if rule.get("post_timestamp", False):
            timezone_name = rule.get("timestamp_timezone", "IST")
            await post_forward_timestamp(client, entity, rule["destination_channel_id"], timezone_name)

        return True

    except Exception as exc:
        logger.error("[CMD_FWD] Error forwarding reply: %s", exc)
        logger.error("[CMD_FWD] Full traceback: %s", traceback.format_exc())
        return False


async def track_outgoing_command(handler, chat_id: int, message_id: int, command_text: str):
    """Track an outgoing command sent by the scheduler/test button."""
    try:
        group = await handler.group_model.get_by_chat_id(chat_id)
        if not group:
            logger.warning("[CMD_FWD] No group found for chat %s, cannot track outgoing command", chat_id)
            return

        rules = await handler.cmd_fwd_model.get_enabled_rules_for_group(group["id"])
        if not rules:
            return

        for rule in rules:
            if rule["command_text"] == command_text:
                me = await handler.session_manager.get_me()
                if me:
                    await handler.cmd_tracked_model.track_command(
                        rule["id"],
                        message_id,
                        chat_id,
                        me.id,
                        command_text,
                    )
                break
    except Exception as exc:
        logger.error("[CMD_FWD] Error tracking outgoing command: %s", exc)
        logger.error("[CMD_FWD] Full traceback: %s", traceback.format_exc())
