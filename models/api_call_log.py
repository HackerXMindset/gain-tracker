from __future__ import annotations

from typing import Optional
from datetime import datetime

from models.base import BaseModel


class ApiCallLogModel(BaseModel):
    async def record(
        self,
        api_name: str,
        phase: str,
        status_code: Optional[int],
        error: Optional[str],
        latency_ms: Optional[int],
        token_id: Optional[int] = None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO api_call_log (token_id, api_name, phase, status_code, error, latency_ms, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            """,
            token_id,
            api_name,
            phase,
            status_code,
            error,
            latency_ms,
        )
