from __future__ import annotations

from typing import Optional, List

import asyncpg

from models.base import BaseModel


class GroupModel(BaseModel):
    """Model for managing group records."""

    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)
        self.table_name = "groups"

    async def get_by_id(self, record_id: int) -> Optional[asyncpg.Record]:
        query = "SELECT * FROM groups WHERE id = $1"
        return await self.db.fetchrow(query, record_id)

    async def get_by_chat_id(self, tg_chat_id: int) -> Optional[asyncpg.Record]:
        query = "SELECT * FROM groups WHERE tg_chat_id = $1"
        return await self.db.fetchrow(query, tg_chat_id)

    async def get_enabled_groups(self) -> List[asyncpg.Record]:
        query = """
            SELECT g.*, ua.userbot_id, b.session_name as userbot_name
            FROM groups g
            LEFT JOIN userbot_assignments ua ON ua.group_id = g.id
            LEFT JOIN bots b ON b.id = ua.userbot_id
            WHERE g.enabled = true
            ORDER BY g.id
        """
        return await self.db.fetch(query)

    async def upsert_from_source(self, tg_chat_id: int, title: Optional[str] = None) -> asyncpg.Record:
        query = """
            INSERT INTO groups (tg_chat_id, title, display_name)
            VALUES ($1, $2, $2)
            ON CONFLICT (tg_chat_id) DO UPDATE
            SET title = COALESCE(groups.title, EXCLUDED.title),
                display_name = COALESCE(groups.display_name, EXCLUDED.display_name)
            RETURNING *
        """
        return await self.db.fetchrow(query, tg_chat_id, title)
