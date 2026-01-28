from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List, Optional

import asyncpg

from models.base import BaseModel

logger = logging.getLogger(__name__)


class TokenModel(BaseModel):
    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)
        self.table_name = "tokens_tracked"

    async def get_by_address(self, address: str) -> Optional[asyncpg.Record]:
        return await self.db.fetchrow(
            "SELECT * FROM tokens_tracked WHERE address = $1",
            address,
        )

    async def get_by_id(self, token_id: int) -> Optional[asyncpg.Record]:
        return await self.db.fetchrow(
            "SELECT * FROM tokens_tracked WHERE id = $1",
            token_id,
        )

    async def create_or_update(
        self,
        address: str,
        market_cap: Decimal,
        ticker: Optional[str] = None,
    ) -> asyncpg.Record:
        query = """
            INSERT INTO tokens_tracked (address, first_seen_mc, last_mc, peak_mc, ticker, last_checked_at)
            VALUES ($1, $2, $2, $2, $3, NOW())
            ON CONFLICT (address) DO UPDATE SET
                last_mc = $2,
                ticker = COALESCE($3, tokens_tracked.ticker),
                last_checked_at = NOW()
            RETURNING *
        """
        return await self.db.fetchrow(query, address, market_cap, ticker)

    async def update_market_cap(
        self,
        token_id: int,
        market_cap: Decimal,
        ticker: Optional[str] = None,
    ) -> asyncpg.Record:
        query = """
            UPDATE tokens_tracked
            SET last_mc = $1,
                first_seen_mc = CASE
                    WHEN first_seen_mc IS NULL OR first_seen_mc <= 0 THEN $1
                    ELSE first_seen_mc
                END,
                ticker = COALESCE($3, ticker),
                last_checked_at = NOW()
            WHERE id = $2
            RETURNING *
        """
        return await self.db.fetchrow(query, market_cap, token_id, ticker)

    async def update_tier(self, token_id: int, tier: str, next_poll_at) -> None:
        await self.db.execute(
            """
            UPDATE tokens_tracked
            SET current_tier = $1, next_poll_at = $2
            WHERE id = $3
            """,
            tier,
            next_poll_at,
            token_id,
        )

    async def update_last_alert_mc(self, token_id: int, alert_mc: Decimal) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET last_alert_mc = $1 WHERE id = $2",
            alert_mc,
            token_id,
        )

    async def update_peak_mc(self, token_id: int, peak_mc: Decimal) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET peak_mc = $1 WHERE id = $2",
            peak_mc,
            token_id,
        )

    async def update_peak_reached_at(self, token_id: int) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET peak_reached_at = NOW() WHERE id = $1",
            token_id,
        )

    async def update_dex_refresh_time(self, token_id: int) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET dex_screener_refreshed_at = NOW() WHERE id = $1",
            token_id,
        )

    async def set_stop_reason(self, token_id: int, reason: Optional[str]) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET stop_reason = $1 WHERE id = $2",
            reason,
            token_id,
        )

    async def get_all_active_scheduled_tokens(self) -> List[asyncpg.Record]:
        return await self.db.fetch(
            """
            SELECT * FROM tokens_tracked
            WHERE (
                status = 'active'
                OR (status = 'stopped' AND tracking_until IS NOT NULL AND tracking_until > NOW())
            )
              AND next_poll_at IS NOT NULL
            ORDER BY next_poll_at ASC
            """
        )

    async def update_original_message_id(self, token_id: int, message_id: int) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET original_message_id = $1 WHERE id = $2",
            message_id,
            token_id,
        )

    async def set_status(
        self,
        token_id: int,
        status: str,
        tracking_until=None,
    ) -> None:
        if tracking_until is None:
            if status == "active":
                await self.db.execute(
                    "UPDATE tokens_tracked SET status = $1, tracking_until = NULL WHERE id = $2",
                    status,
                    token_id,
                )
            else:
                await self.db.execute(
                    "UPDATE tokens_tracked SET status = $1 WHERE id = $2",
                    status,
                    token_id,
                )
            return
        await self.db.execute(
            "UPDATE tokens_tracked SET status = $1, tracking_until = $2 WHERE id = $3",
            status,
            tracking_until,
            token_id,
        )

    async def update_last_seen_mc(self, token_id: int, market_cap: Decimal) -> None:
        await self.db.execute(
            "UPDATE tokens_tracked SET last_mc = $1 WHERE id = $2",
            market_cap,
            token_id,
        )

    async def update_last_api_error(
        self,
        token_address: str,
        api_name: Optional[str],
        status_code: Optional[int],
        message: Optional[str],
    ) -> None:
        await self.db.execute(
            """
            UPDATE tokens_tracked
            SET last_api_error_api = $2,
                last_api_error_code = $3,
                last_api_error_message = $4,
                last_api_error_at = CASE WHEN $2 IS NULL THEN NULL ELSE NOW() END
            WHERE address = $1
            """,
            token_address,
            api_name,
            status_code,
            message,
        )

    async def get_id_by_address(self, address: str) -> Optional[int]:
        row = await self.db.fetchrow("SELECT id FROM tokens_tracked WHERE address = $1", address)
        return row["id"] if row else None

    async def update_last_api_error(
        self,
        address: str,
        api_name: str,
        status_code: Optional[int],
        message: Optional[str],
    ) -> None:
        await self.db.execute(
            """
            UPDATE tokens_tracked
            SET last_api_error_api = $1,
                last_api_error_code = $2,
                last_api_error_message = $3,
                last_api_error_at = NOW()
            WHERE address = $4
            """,
            api_name,
            status_code,
            message,
            address,
        )

    async def get_token_stats(self) -> Dict[str, int]:
        row = await self.db.fetchrow(
            """
            SELECT
                COUNT(*) as total_tokens,
                COUNT(*) FILTER (WHERE status = 'active') as active_tokens
            FROM tokens_tracked
            """
        )
        return dict(row) if row else {}
