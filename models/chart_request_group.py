from __future__ import annotations

from typing import List, Optional, Dict, Any

from models.base import BaseModel


class ChartRequestGroupModel(BaseModel):
    async def list_all(self) -> List[Dict[str, Any]]:
        rows = await self.db.fetch(
            "SELECT * FROM chart_request_groups ORDER BY added_at DESC"
        )
        return [dict(r) for r in rows]

    async def add_group(self, chat_id: int, label: Optional[str] = None) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchrow(
            """
            INSERT INTO chart_request_groups (chat_id, label)
            VALUES ($1, $2)
            ON CONFLICT (chat_id) DO NOTHING
            RETURNING *
            """,
            chat_id,
            label,
        )
        return dict(row) if row else None

    async def get_by_chat_id(self, chat_id: int) -> Optional[Dict[str, Any]]:
        row = await self.db.fetchrow(
            "SELECT * FROM chart_request_groups WHERE chat_id = $1",
            chat_id,
        )
        return dict(row) if row else None

    async def remove_by_chat(self, chat_id: int) -> bool:
        result = await self.db.execute(
            "DELETE FROM chart_request_groups WHERE chat_id = $1",
            chat_id,
        )
        return result == "DELETE 1"

    async def remove_group(self, chat_id: int) -> bool:
        return await self.remove_by_chat(chat_id)

    async def count_groups(self) -> int:
        result = await self.db.fetchval("SELECT COUNT(*) FROM chart_request_groups")
        return result or 0
