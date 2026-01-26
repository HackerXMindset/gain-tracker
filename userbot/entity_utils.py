"""
Entity Utils - Telegram entity resolution helpers.
"""

import logging
import traceback
from datetime import datetime, timedelta, timezone
from telethon.tl.types import PeerChannel, PeerChat, PeerUser

logger = logging.getLogger(__name__)


async def resolve_entity_safely(client, target_chat_id: int):
    try:
        return await client.get_entity(target_chat_id)
    except Exception as exc:
        logger.debug("Entity resolution failed for %s: %s", target_chat_id, exc)

        try:
            if target_chat_id < 0:
                if str(target_chat_id).startswith("-100"):
                    channel_id = abs(target_chat_id) - 1000000000000
                    return PeerChannel(channel_id)
                return PeerChat(abs(target_chat_id))
            return PeerUser(target_chat_id)
        except Exception as peer_error:
            logger.debug("Peer construction failed for %s: %s", target_chat_id, peer_error)
            return target_chat_id


async def post_forward_timestamp(client, entity, destination_channel_id: int, timezone_name: str):
    """Post timestamp after forwarding a message in specified timezone."""
    try:
        timezone_offsets = {
            "IST": timedelta(hours=5, minutes=30),
            "UTC": timedelta(hours=0),
            "GMT": timedelta(hours=0),
            "EST": timedelta(hours=-5),
            "PST": timedelta(hours=-8),
            "CST": timedelta(hours=-6),
            "JST": timedelta(hours=9),
            "AEST": timedelta(hours=10),
            "CET": timedelta(hours=1),
        }

        offset = timezone_offsets.get(timezone_name, timedelta(hours=5, minutes=30))
        tz = timezone(offset)
        local_time = datetime.now(tz)
        timestamp_text = f"Forwarded at: {local_time.strftime('%d/%m/%Y %H:%M:%S')} {timezone_name}"

        await client.send_message(entity=entity, message=timestamp_text)
        logger.info("[MessageHandler] Posted %s timestamp to channel %s", timezone_name, destination_channel_id)
    except Exception as exc:
        logger.error("[MessageHandler] Error posting timestamp: %s", exc)
        logger.error("[MessageHandler] Full traceback: %s", traceback.format_exc())
