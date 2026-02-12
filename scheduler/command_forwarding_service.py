from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any

from db import db
from models import CommandForwardingRuleModel

logger = logging.getLogger(__name__)


class CommandForwardingService:
    def __init__(self, userbot_manager=None) -> None:
        self.userbot_manager = userbot_manager
        self.cmd_fwd_model = CommandForwardingRuleModel(db)
        self.running = False
        self._task: Optional[asyncio.Task] = None

    def set_userbot_manager(self, manager) -> None:
        self.userbot_manager = manager

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[CMD_FWD_SCHEDULER] Service started")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[CMD_FWD_SCHEDULER] Service stopped")

    async def _run_loop(self) -> None:
        while self.running:
            try:
                await self._process_command_schedules()
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[CMD_FWD_SCHEDULER] Error in scheduler loop: %s", exc, exc_info=True)
                await asyncio.sleep(10)

    async def _process_command_schedules(self) -> None:
        try:
            logger.debug("[CMD_FWD_SCHEDULER] Processing command forwarding schedules")
            ready_rules = await self.cmd_fwd_model.get_rules_ready_for_execution()
            logger.debug("[CMD_FWD_SCHEDULER] Found %s command rules ready for execution", len(ready_rules))

            for rule in ready_rules:
                try:
                    logger.info(
                        "[CMD_FWD_SCHEDULER] Processing scheduled command '%s' for rule %s",
                        rule["command_text"],
                        rule["id"],
                    )
                    await self._send_scheduled_command(rule)
                    await self.cmd_fwd_model.update_next_scheduled_time(rule["id"])
                    logger.info("[CMD_FWD_SCHEDULER] Successfully processed scheduled command for rule %s", rule["id"])
                except Exception as rule_error:
                    logger.error(
                        "[CMD_FWD_SCHEDULER] Error processing command rule %s: %s",
                        rule["id"],
                        rule_error,
                    )
        except Exception as exc:
            logger.error("[CMD_FWD_SCHEDULER] Error processing command schedules: %s", exc, exc_info=True)

    async def _send_scheduled_command(self, rule: Dict[str, Any]):
        try:
            source_chat_id = rule["source_chat_id"]
            command_text = rule["command_text"]
            forwarding_userbot_id = rule["forwarding_userbot_id"]

            logger.info(
                "[CMD_FWD_SCHEDULER] Sending scheduled command '%s' to chat %s via userbot %s",
                command_text,
                source_chat_id,
                forwarding_userbot_id,
            )

            if not self.userbot_manager:
                logger.error("[CMD_FWD_SCHEDULER] UserbotManager not available for sending command")
                return False

            worker = self.userbot_manager.get_worker(forwarding_userbot_id)
            if not worker:
                logger.error("[CMD_FWD_SCHEDULER] No worker found for userbot %s", forwarding_userbot_id)
                return False

            client = worker.session_manager.get_client()
            if not client:
                logger.error("[CMD_FWD_SCHEDULER] No client available for userbot %s", forwarding_userbot_id)
                return False

            entity = await self._resolve_entity(client, source_chat_id)
            if not entity:
                logger.error(
                    "[CMD_FWD_SCHEDULER] Unable to resolve entity for chat %s (userbot may not be in chat)",
                    source_chat_id,
                )
                return False

            sent_message = await client.send_message(entity, command_text)
            logger.info(
                "[CMD_FWD_SCHEDULER] Successfully sent scheduled command '%s' to chat %s",
                command_text,
                source_chat_id,
            )

            if worker.message_handler:
                await worker.message_handler.track_outgoing_command(
                    source_chat_id,
                    sent_message.id,
                    command_text,
                )

            return True

        except Exception as exc:
            logger.error("[CMD_FWD_SCHEDULER] Error sending scheduled command: %s", exc, exc_info=True)
            return False

    async def send_test_command(self, rule: Dict[str, Any], source_chat_id: int) -> bool:
        try:
            command_text = rule["command_text"]
            forwarding_userbot_id = rule["forwarding_userbot_id"]

            if not self.userbot_manager:
                logger.error("[CMD_FWD_SCHEDULER] UserbotManager not available for test command")
                return False

            worker = self.userbot_manager.get_worker(forwarding_userbot_id)
            if not worker:
                logger.error("[CMD_FWD_SCHEDULER] No worker found for userbot %s", forwarding_userbot_id)
                return False

            client = worker.session_manager.get_client()
            if not client:
                logger.error("[CMD_FWD_SCHEDULER] No client available for userbot %s", forwarding_userbot_id)
                return False

            entity = await self._resolve_entity(client, source_chat_id)
            if not entity:
                logger.error(
                    "[CMD_FWD_SCHEDULER] Unable to resolve entity for chat %s (userbot may not be in chat)",
                    source_chat_id,
                )
                return False

            sent_message = await client.send_message(entity, command_text)
            logger.info(
                "[CMD_FWD_SCHEDULER] Sent test command '%s' to chat %s",
                command_text,
                source_chat_id,
            )

            if worker.message_handler:
                await worker.message_handler.track_outgoing_command(
                    source_chat_id,
                    sent_message.id,
                    command_text,
                )

            return True
        except Exception as exc:
            logger.error("[CMD_FWD_SCHEDULER] Error sending test command: %s", exc, exc_info=True)
            return False

    async def _resolve_entity(self, client, target_chat_id: int):
        try:
            return await client.get_entity(target_chat_id)
        except Exception as exc:
            logger.error("[CMD_FWD_SCHEDULER] Failed to resolve entity for chat %s: %s", target_chat_id, exc)

        target_id: int
        if target_chat_id < 0:
            if str(target_chat_id).startswith("-100"):
                target_id = abs(target_chat_id) - 1000000000000
            else:
                target_id = abs(target_chat_id)
        else:
            target_id = target_chat_id

        try:
            async for dialog in client.iter_dialogs():
                entity = getattr(dialog, "entity", None)
                entity_id = getattr(entity, "id", None)
                if entity_id == target_id:
                    return entity
        except Exception as exc:
            logger.error("[CMD_FWD_SCHEDULER] Error iterating dialogs: %s", exc, exc_info=True)

        return None


_command_forwarding_service: Optional[CommandForwardingService] = None


def get_command_forwarding_service() -> CommandForwardingService:
    global _command_forwarding_service
    if _command_forwarding_service is None:
        _command_forwarding_service = CommandForwardingService()
    return _command_forwarding_service
