"""
Chart Fetcher - Fetches token chart images by posting CA to random groups and capturing bot replies.
"""

import asyncio
import logging
import random
from typing import Optional, Tuple, Dict
from io import BytesIO

from telethon.tl.custom import Message as TelethonMessage
from telethon.errors import FloodWaitError, ChatWriteForbiddenError

logger = logging.getLogger(__name__)


class ChartFetcher:
    def __init__(self, db_pool, userbot_manager) -> None:
        self.db = db_pool
        self.userbot_manager = userbot_manager
        self._pending_requests: Dict[int, Tuple[asyncio.Future, int]] = {}
        logger.info("[CHART_FETCH] ChartFetcher initialized")

    async def fetch_chart_for_token(
        self,
        contract_address: str,
        chart_bot_id: int,
        timeout: int = 60,
    ) -> Optional[bytes]:
        try:
            group_chat_id = await self._get_random_chart_group()
            if not group_chat_id:
                logger.warning("[CHART_FETCH] No chart request groups configured")
                return None

            result = await self._post_ca_with_random_userbot(group_chat_id, contract_address)
            if not result:
                logger.warning("[CHART_FETCH] Failed to post CA %s to group %s", contract_address, group_chat_id)
                return None

            chat_id, message_id = result

            future = asyncio.Future()
            self._pending_requests[message_id] = (future, chart_bot_id)

            logger.info(
                "[CHART_FETCH] Posted CA %s to group %s, message_id=%s, waiting for bot %s",
                contract_address,
                chat_id,
                message_id,
                chart_bot_id,
            )

            try:
                photo_bytes = await asyncio.wait_for(future, timeout=timeout)
                if photo_bytes is not None:
                    logger.info(
                        "[CHART_FETCH] Chart fetched for %s, size=%s bytes",
                        contract_address,
                        len(photo_bytes),
                    )
                return photo_bytes
            except asyncio.TimeoutError:
                logger.warning(
                    "[CHART_FETCH] Timeout waiting for chart bot %s to reply to message %s",
                    chart_bot_id,
                    message_id,
                )
                return None
            finally:
                self._pending_requests.pop(message_id, None)
        except Exception as exc:
            logger.error("[CHART_FETCH] Error fetching chart for %s: %s", contract_address, exc)
            return None

    async def _get_random_chart_group(self) -> Optional[int]:
        try:
            result = await self.db.fetch(
                "SELECT chat_id FROM chart_request_groups ORDER BY RANDOM() LIMIT 1"
            )
            if not result:
                return None
            chat_id = result[0]["chat_id"]
            logger.debug("[CHART_FETCH] Selected chart group %s", chat_id)
            return chat_id
        except Exception as exc:
            logger.error("[CHART_FETCH] Error getting random chart group: %s", exc)
            return None

    async def _post_ca_with_random_userbot(
        self,
        chat_id: int,
        contract_address: str,
    ) -> Optional[Tuple[int, int]]:
        try:
            all_workers = self.userbot_manager.get_all_workers()
            if not all_workers:
                logger.warning("[CHART_FETCH] No userbots available")
                return None

            worker = random.choice(list(all_workers.values()))
            userbot_id = worker.userbot_id
            client = worker.session_manager.get_client()
            if not client:
                logger.warning("[CHART_FETCH] Userbot %s client not connected", userbot_id)
                return None

            sent_message = await client.send_message(
                chat_id,
                contract_address,
                link_preview=False,
            )
            logger.info(
                "[CHART_FETCH] Posted CA to group %s, message_id=%s, userbot=%s",
                chat_id,
                sent_message.id,
                userbot_id,
            )
            return (chat_id, sent_message.id)
        except FloodWaitError as exc:
            logger.error("[CHART_FETCH] Flood wait: %s seconds", exc.seconds)
            return None
        except ChatWriteForbiddenError:
            logger.error("[CHART_FETCH] Bot cannot write to group %s", chat_id)
            return None
        except Exception as exc:
            logger.error("[CHART_FETCH] Error posting CA to group %s: %s", chat_id, exc)
            return None

    async def handle_chart_bot_reply(self, message: TelethonMessage) -> None:
        try:
            reply_to_msg_id = message.reply_to_msg_id
            if not reply_to_msg_id:
                return

            pending = self._pending_requests.get(reply_to_msg_id)
            if not pending:
                return

            future, expected_chart_bot_id = pending

            if message.sender_id != expected_chart_bot_id:
                logger.debug(
                    "[CHART_FETCH] Ignoring reply from bot %s, expected %s",
                    message.sender_id,
                    expected_chart_bot_id,
                )
                return

            self._pending_requests.pop(reply_to_msg_id, None)

            if future.done():
                logger.warning("[CHART_FETCH] Future for message %s already resolved", reply_to_msg_id)
                return

            if not message.photo:
                logger.warning(
                    "[CHART_FETCH] Bot %s replied to %s without photo",
                    expected_chart_bot_id,
                    reply_to_msg_id,
                )
                future.set_result(None)
                return

            photo_bytes_io = BytesIO()
            await message.download_media(file=photo_bytes_io)
            photo_bytes = photo_bytes_io.getvalue()

            logger.info(
                "[CHART_FETCH] Downloaded chart photo for message %s (%s bytes)",
                reply_to_msg_id,
                len(photo_bytes),
            )

            future.set_result(photo_bytes)
        except Exception as exc:
            logger.error("[CHART_FETCH] Error handling chart bot reply: %s", exc)
            if message:
                future_entry = self._pending_requests.pop(message.reply_to_msg_id, None)
                if future_entry:
                    future, _ = future_entry
                    if not future.done():
                        future.set_result(None)
