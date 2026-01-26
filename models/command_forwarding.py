from __future__ import annotations

from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
import logging
import traceback

import asyncpg

from models.base import BaseModel

logger = logging.getLogger(__name__)


class CommandForwardingRuleModel(BaseModel):
    """Model for managing command forwarding rules."""

    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)
        self.table_name = "command_forwarding_rules"

    async def create(self, data: Dict[str, Any]) -> asyncpg.Record:
        columns = list(data.keys())
        placeholders = [f"${idx + 1}" for idx in range(len(columns))]
        values = list(data.values())
        query = f"""
            INSERT INTO {self.table_name} ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            RETURNING *
        """
        return await self.db.fetchrow(query, *values)

    async def update(self, record_id: int, data: Dict[str, Any]) -> Optional[asyncpg.Record]:
        if not data:
            return await self.get_by_id(record_id)

        set_clauses = []
        values = []
        param_idx = 1

        for key, value in data.items():
            set_clauses.append(f"{key} = ${param_idx}")
            values.append(value)
            param_idx += 1

        values.append(record_id)
        query = f"""
            UPDATE {self.table_name}
            SET {', '.join(set_clauses)}, updated_at = NOW()
            WHERE id = ${param_idx}
            RETURNING *
        """
        return await self.db.fetchrow(query, *values)

    async def delete(self, record_id: int) -> bool:
        query = f"DELETE FROM {self.table_name} WHERE id = $1"
        result = await self.db.execute(query, record_id)
        return result.split()[-1] == "1"

    async def get_by_id(self, record_id: int) -> Optional[asyncpg.Record]:
        query = """
            SELECT cfr.*,
                   COALESCE(g.display_name, g.title, 'Unknown Group') as source_group_title
            FROM command_forwarding_rules cfr
            LEFT JOIN groups g ON g.id = cfr.source_group_id
            WHERE cfr.id = $1
        """
        return await self.db.fetchrow(query, record_id)

    async def get_by_source_group(self, source_group_id: int) -> List[asyncpg.Record]:
        query = """
            SELECT cfr.*, COALESCE(g.display_name, g.title, 'Unknown Group') as source_group_title
            FROM command_forwarding_rules cfr
            JOIN groups g ON g.id = cfr.source_group_id
            WHERE cfr.source_group_id = $1
            ORDER BY cfr.created_at DESC
        """
        return await self.db.fetch(query, source_group_id)

    async def get_enabled_rules_for_group(self, source_group_id: int) -> List[asyncpg.Record]:
        try:
            logger.debug("Getting enabled command forwarding rules for group: %s", source_group_id)
            query = """
                SELECT * FROM command_forwarding_rules
                WHERE source_group_id = $1 AND enabled = true
                ORDER BY created_at DESC
            """
            result = await self.db.fetch(query, source_group_id)
            logger.debug("Found %s enabled command forwarding rules for group %s", len(result), source_group_id)
            for rule in result:
                logger.debug(
                    "Rule %s: command='%s', userbot=%s, destination=%s, monitored_users=%s, reply_users=%s, schedule_enabled=%s",
                    rule["id"],
                    rule["command_text"],
                    rule.get("forwarding_userbot_id"),
                    rule.get("destination_channel_id"),
                    rule.get("allowed_command_user_ids"),
                    rule.get("allowed_reply_user_ids"),
                    rule.get("schedule_enabled"),
                )
            return result
        except Exception as exc:
            logger.error("Failed to get enabled command rules for group %s: %s", source_group_id, exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            raise

    async def create_rule(
        self,
        source_group_id: int,
        command_text: str,
        destination_channel_id: int,
        allowed_command_user_ids: List[int],
        allowed_reply_user_ids: List[int],
        forwarding_userbot_id: int,
        schedule_enabled: bool = False,
        schedule_interval_minutes: Optional[int] = None,
        post_timestamp: bool = False,
        timestamp_timezone: str = "IST",
        excluded_message_texts: Optional[List[str]] = None,
    ) -> asyncpg.Record:
        try:
            logger.info(
                "Creating command forwarding rule: source_group=%s, command='%s', destination=%s, monitored_users=%s, reply_users=%s, userbot=%s, schedule_enabled=%s, schedule_interval=%s, post_timestamp=%s, timezone=%s, excluded_texts=%s",
                source_group_id,
                command_text,
                destination_channel_id,
                allowed_command_user_ids,
                allowed_reply_user_ids,
                forwarding_userbot_id,
                schedule_enabled,
                schedule_interval_minutes,
                post_timestamp,
                timestamp_timezone,
                excluded_message_texts,
            )

            next_scheduled_at = None
            if schedule_enabled and schedule_interval_minutes:
                next_scheduled_at = datetime.utcnow() + timedelta(minutes=schedule_interval_minutes)

            data = {
                "source_group_id": source_group_id,
                "command_text": command_text,
                "destination_channel_id": destination_channel_id,
                "allowed_command_user_ids": allowed_command_user_ids,
                "allowed_reply_user_ids": allowed_reply_user_ids,
                "forwarding_userbot_id": forwarding_userbot_id,
                "schedule_enabled": schedule_enabled,
                "schedule_interval_minutes": schedule_interval_minutes,
                "next_scheduled_at": next_scheduled_at,
                "post_timestamp": post_timestamp,
                "timestamp_timezone": timestamp_timezone,
                "excluded_message_texts": excluded_message_texts or [],
            }

            result = await self.create(data)
            logger.info("Successfully created command forwarding rule with ID: %s", result["id"])
            return result
        except Exception as exc:
            logger.error("Failed to create command forwarding rule: %s", exc)
            logger.error(
                "Parameters: source_group=%s, command='%s', destination=%s",
                source_group_id,
                command_text,
                destination_channel_id,
            )
            logger.error("Full traceback: %s", traceback.format_exc())
            raise

    async def toggle_enabled(self, rule_id: int) -> bool:
        query = """
            UPDATE command_forwarding_rules
            SET enabled = NOT enabled, updated_at = NOW()
            WHERE id = $1
            RETURNING enabled
        """
        result = await self.db.fetchval(query, rule_id)
        return result

    async def toggle_schedule_enabled(self, rule_id: int) -> bool:
        query = """
            UPDATE command_forwarding_rules
            SET schedule_enabled = NOT schedule_enabled,
                next_scheduled_at = CASE
                    WHEN NOT schedule_enabled AND schedule_interval_minutes IS NOT NULL
                    THEN NOW() + INTERVAL '1 minute' * schedule_interval_minutes
                    ELSE NULL
                END,
                updated_at = NOW()
            WHERE id = $1
            RETURNING schedule_enabled
        """
        result = await self.db.fetchval(query, rule_id)
        return result

    async def toggle_timestamp_posting(self, rule_id: int) -> bool:
        query = """
            UPDATE command_forwarding_rules
            SET post_timestamp = NOT post_timestamp, updated_at = NOW()
            WHERE id = $1
            RETURNING post_timestamp
        """
        result = await self.db.fetchval(query, rule_id)
        return result

    async def update_timezone(self, rule_id: int, timezone: str) -> Optional[asyncpg.Record]:
        query = """
            UPDATE command_forwarding_rules
            SET timestamp_timezone = $1, updated_at = NOW()
            WHERE id = $2
            RETURNING *
        """
        return await self.db.fetchrow(query, timezone, rule_id)

    async def update_schedule(
        self,
        rule_id: int,
        schedule_enabled: bool,
        schedule_interval_minutes: Optional[int] = None,
    ) -> Optional[asyncpg.Record]:
        next_scheduled_at = None
        if schedule_enabled and schedule_interval_minutes:
            next_scheduled_at = datetime.utcnow() + timedelta(minutes=schedule_interval_minutes)

        query = """
            UPDATE command_forwarding_rules
            SET schedule_enabled = $1,
                schedule_interval_minutes = $2,
                next_scheduled_at = $3,
                updated_at = NOW()
            WHERE id = $4
            RETURNING *
        """
        return await self.db.fetchrow(
            query,
            schedule_enabled,
            schedule_interval_minutes,
            next_scheduled_at,
            rule_id,
        )

    async def get_rules_ready_for_execution(self) -> List[asyncpg.Record]:
        query = """
            SELECT cfr.*, g.tg_chat_id as source_chat_id
            FROM command_forwarding_rules cfr
            JOIN groups g ON g.id = cfr.source_group_id
            WHERE cfr.enabled = true
            AND cfr.schedule_enabled = true
            AND cfr.next_scheduled_at IS NOT NULL
            AND cfr.next_scheduled_at <= NOW()
            ORDER BY cfr.next_scheduled_at ASC
        """
        return await self.db.fetch(query)

    async def update_next_scheduled_time(self, rule_id: int) -> Optional[asyncpg.Record]:
        query = """
            UPDATE command_forwarding_rules
            SET last_scheduled_at = NOW(),
                next_scheduled_at = CASE
                    WHEN schedule_interval_minutes IS NOT NULL
                    THEN NOW() + INTERVAL '1 minute' * schedule_interval_minutes
                    ELSE NULL
                END,
                updated_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        return await self.db.fetchrow(query, rule_id)

    async def get_all_with_details(self) -> List[asyncpg.Record]:
        query = """
            SELECT cfr.*,
                   COALESCE(g.display_name, g.title, 'Unknown Group') as source_group_title,
                   g.tg_chat_id as source_group_chat_id
            FROM command_forwarding_rules cfr
            JOIN groups g ON g.id = cfr.source_group_id
            ORDER BY cfr.enabled DESC, cfr.created_at DESC
        """
        return await self.db.fetch(query)

    async def add_excluded_text(self, rule_id: int, text: str) -> Optional[asyncpg.Record]:
        try:
            logger.debug("Adding excluded text to rule %s: '%s'", rule_id, text)
            query = """
                UPDATE command_forwarding_rules
                SET excluded_message_texts = CASE
                    WHEN $1 = ANY(excluded_message_texts) THEN excluded_message_texts
                    ELSE array_append(excluded_message_texts, $1)
                END,
                    updated_at = NOW()
                WHERE id = $2
                RETURNING *
            """
            result = await self.db.fetchrow(query, text, rule_id)
            logger.info("Successfully added excluded text to rule %s", rule_id)
            return result
        except Exception as exc:
            logger.error("Failed to add excluded text to rule %s: %s", rule_id, exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            raise

    async def remove_excluded_text(self, rule_id: int, text: str) -> Optional[asyncpg.Record]:
        try:
            logger.debug("Removing excluded text from rule %s: '%s'", rule_id, text)
            query = """
                UPDATE command_forwarding_rules
                SET excluded_message_texts = array_remove(excluded_message_texts, $1),
                    updated_at = NOW()
                WHERE id = $2
                RETURNING *
            """
            result = await self.db.fetchrow(query, text, rule_id)
            logger.info("Successfully removed excluded text from rule %s", rule_id)
            return result
        except Exception as exc:
            logger.error("Failed to remove excluded text from rule %s: %s", rule_id, exc)
            logger.error("Full traceback: %s", traceback.format_exc())
            raise


class CommandTrackedMessageModel(BaseModel):
    """Model for managing tracked command messages."""

    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)
        self.table_name = "command_tracked_messages"

    async def track_command(
        self,
        rule_id: int,
        original_message_id: int,
        chat_id: int,
        sender_id: int,
        command_text: str,
    ) -> Optional[asyncpg.Record]:
        try:
            query = """
                INSERT INTO command_tracked_messages (rule_id, original_message_id, chat_id, sender_id, command_text)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (original_message_id, chat_id, rule_id) DO NOTHING
                RETURNING *
            """
            return await self.db.fetchrow(
                query,
                rule_id,
                original_message_id,
                chat_id,
                sender_id,
                command_text,
            )
        except Exception as exc:
            logger.error("Failed to track command: %s", exc)
            return None

    async def get_tracked_messages_for_reply(
        self,
        reply_to_message_id: int,
        chat_id: int,
    ) -> List[asyncpg.Record]:
        query = """
            SELECT * FROM command_tracked_messages
            WHERE original_message_id = $1 AND chat_id = $2 AND status = 'tracking'
            AND created_at > NOW() - INTERVAL '3 minutes'
        """
        return await self.db.fetch(query, reply_to_message_id, chat_id)

    async def mark_forwarded(
        self,
        tracked_id: int,
        reply_sender_id: int,
        reply_message_id: int,
    ) -> bool:
        try:
            query = """
                UPDATE command_tracked_messages
                SET status = 'forwarded',
                    reply_sender_id = $1,
                    last_reply_message_id = $2,
                    updated_at = NOW()
                WHERE id = $3
            """
            await self.db.execute(query, reply_sender_id, reply_message_id, tracked_id)
            return True
        except Exception as exc:
            logger.error("Failed to mark message as forwarded: %s", exc)
            return False

    async def cleanup_old_tracking(self, hours_old: int = 1) -> int:
        query = """
            DELETE FROM command_tracked_messages
            WHERE status = 'tracking' AND created_at < NOW() - INTERVAL '1 hour' * $1
        """
        result = await self.db.execute(query, hours_old)
        return int(result.split()[-1]) if result else 0
