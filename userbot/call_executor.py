"""
Call Executor - Sends gain alert messages via userbot.
"""

import logging
from io import BytesIO
from typing import Dict, Optional

from telethon.errors import RPCError

from userbot.entity_utils import resolve_entity_safely
from userbot.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class CallExecutor:
    def __init__(self, userbot_id: int, session_manager) -> None:
        self.userbot_id = userbot_id
        self.session_manager = session_manager
        self.rate_limiter = RateLimiter(max_calls=30, time_window=60)

    async def send_alert_message(
        self,
        target_chat_id: int,
        message: str,
        reply_to_message_id: Optional[int] = None,
        photo_bytes: Optional[bytes] = None,
    ) -> Dict[str, Optional[str]]:
        try:
            client = self.session_manager.get_client()
            if not client:
                return {"success": False, "error": "Client not initialized"}

            if not self.rate_limiter.can_make_call():
                logger.warning("Rate limit exceeded for userbot %s", self.userbot_id)
                return {"success": False, "error": "Rate limit exceeded"}

            resolved_entity = await resolve_entity_safely(client, target_chat_id)

            try:
                if photo_bytes:
                    file_obj = BytesIO(photo_bytes)
                    file_obj.name = "chart.jpg"
                    sent_message = await client.send_file(
                        resolved_entity,
                        file=file_obj,
                        caption=message,
                        reply_to=reply_to_message_id,
                    )
                else:
                    sent_message = await client.send_message(
                        resolved_entity,
                        message,
                        link_preview=False,
                        reply_to=reply_to_message_id,
                    )
            except Exception as exc:
                if reply_to_message_id and "message_id_invalid" in str(exc).lower():
                    logger.warning(
                        "Reply %s failed for %s, retrying without reply",
                        reply_to_message_id,
                        target_chat_id,
                    )
                    if photo_bytes:
                        file_obj = BytesIO(photo_bytes)
                        file_obj.name = "chart.jpg"
                        sent_message = await client.send_file(
                            resolved_entity,
                            file=file_obj,
                            caption=message,
                        )
                    else:
                        sent_message = await client.send_message(
                            resolved_entity,
                            message,
                            link_preview=False,
                        )
                else:
                    raise

            self.rate_limiter.record_call()
            message_id = getattr(sent_message, "id", None)
            logger.info("Sent gain alert to chat %s via userbot %s", target_chat_id, self.userbot_id)
            return {"success": True, "message_id": message_id}
        except RPCError as rpc_error:
            logger.error("RPC error sending gain alert: %s", rpc_error)
            return {"success": False, "error": str(rpc_error)}
        except Exception as exc:
            logger.error("Error sending gain alert: %s", exc)
            return {"success": False, "error": str(exc)}
