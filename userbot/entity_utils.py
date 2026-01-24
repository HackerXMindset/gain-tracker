"""
Entity Utils - Telegram entity resolution helpers.
"""

import logging
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
