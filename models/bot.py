from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncpg

from models.base import BaseModel


class BotModel(BaseModel):
    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)
        self.table_name = "bots"

    async def get_by_session_name(self, session_name: str) -> Optional[asyncpg.Record]:
        return await self.db.fetchrow(
            "SELECT * FROM bots WHERE session_name = $1",
            session_name,
        )

    async def get_by_id(self, bot_id: int) -> Optional[asyncpg.Record]:
        return await self.db.fetchrow(
            "SELECT * FROM bots WHERE id = $1",
            bot_id,
        )

    async def create(self, data: Dict[str, Any]) -> asyncpg.Record:
        columns = list(data.keys())
        placeholders = [f"${idx + 1}" for idx in range(len(columns))]
        values = list(data.values())
        query = f"""
            INSERT INTO bots ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
            RETURNING *
        """
        return await self.db.fetchrow(query, *values)

    async def delete(self, bot_id: int) -> bool:
        result = await self.db.execute(
            "DELETE FROM bots WHERE id = $1",
            bot_id,
        )
        return result.split()[-1] == "1"

    async def get_by_phone(self, phone: str) -> Optional[asyncpg.Record]:
        session_name = f"userbot_{phone.replace('+', '')[-8:]}"
        return await self.db.fetchrow(
            "SELECT * FROM bots WHERE session_name = $1",
            session_name,
        )

    async def get_active_userbots(self) -> List[asyncpg.Record]:
        return await self.db.fetch(
            """
            SELECT * FROM bots
            WHERE kind = 'userbot'
            ORDER BY last_seen DESC
            """
        )

    async def get_userbots_with_assignments(self) -> List[asyncpg.Record]:
        return await self.db.fetch(
            """
            SELECT
                b.*,
                COUNT(ua.group_id) AS assigned_groups,
                ARRAY_AGG(ua.group_id) FILTER (WHERE ua.group_id IS NOT NULL) AS group_ids
            FROM bots b
            LEFT JOIN userbot_assignments ua ON ua.userbot_id = b.id
            WHERE b.kind = 'userbot'
            GROUP BY b.id
            ORDER BY b.status DESC, b.last_seen DESC
            """
        )

    async def assign_to_group(self, userbot_id: int, group_id: int) -> asyncpg.Record:
        async with self.db.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM userbot_assignments WHERE group_id = $1",
                    group_id,
                )
                return await conn.fetchrow(
                    """
                    INSERT INTO userbot_assignments (userbot_id, group_id)
                    VALUES ($1, $2)
                    RETURNING *
                    """,
                    userbot_id,
                    group_id,
                )

    async def unassign_from_group(self, group_id: int) -> bool:
        result = await self.db.execute(
            "DELETE FROM userbot_assignments WHERE group_id = $1",
            group_id,
        )
        return result.split()[-1] == "1"

    async def get_assigned_groups(self, userbot_id: int) -> List[asyncpg.Record]:
        return await self.db.fetch(
            """
            SELECT g.*
            FROM groups g
            JOIN userbot_assignments ua ON ua.group_id = g.id
            WHERE ua.userbot_id = $1
            """,
            userbot_id,
        )

    async def set_status(self, bot_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE bots SET status = $1, last_seen = NOW() WHERE id = $2",
            status,
            bot_id,
        )

    async def update_identity(
        self,
        bot_id: int,
        telegram_id: Optional[int],
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
    ) -> None:
        await self.db.execute(
            """
            UPDATE bots
            SET telegram_id = $1,
                username = $2,
                first_name = $3,
                last_name = $4,
                last_seen = NOW()
            WHERE id = $5
            """,
            telegram_id,
            username,
            first_name,
            last_name,
            bot_id,
        )
