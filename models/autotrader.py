from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime

from models.base import BaseModel


class AutoTraderRunModel(BaseModel):
    async def create_run(self, data: Dict[str, Any]) -> int:
        query = """
        INSERT INTO autotrader_runs (
            name, created_by_user_id, destination_chat_id, destination_type, status,
            start_at, stop_at, budget_total, per_coin_spend, remaining_cash,
            coin_cap, hold_seconds, report_interval_seconds, breakout_multiple,
            bankrupt_floor, target_value, channel_mode, channels, freshness_secs,
            max_retries
        )
        VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20
        )
        RETURNING id
        """
        return await self.db.fetchval(
            query,
            data.get("name"),
            data.get("created_by_user_id"),
            data.get("destination_chat_id"),
            data.get("destination_type"),
            data.get("status", "pending"),
            data.get("start_at"),
            data.get("stop_at"),
            data["budget_total"],
            data["per_coin_spend"],
            data["remaining_cash"],
            data.get("coin_cap"),
            data["hold_seconds"],
            data.get("report_interval_seconds"),
            data.get("breakout_multiple"),
            data.get("bankrupt_floor"),
            data.get("target_value"),
            data.get("channel_mode", "single"),
            data.get("channels"),
            data.get("freshness_secs"),
            data.get("max_retries"),
        )

    async def update_status(self, run_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE autotrader_runs SET status=$2 WHERE id=$1",
            run_id,
            status,
        )

    async def get_run(self, run_id: int) -> Optional[dict]:
        return await self.db.fetchrow("SELECT * FROM autotrader_runs WHERE id=$1", run_id)

    async def list_pending(self, limit: int = 20):
        return await self.db.fetch(
            "SELECT * FROM autotrader_runs WHERE status='pending' ORDER BY created_at ASC LIMIT $1",
            limit,
        )

    async def list_running(self, limit: int = 20):
        return await self.db.fetch(
            "SELECT * FROM autotrader_runs WHERE status='running' ORDER BY updated_at ASC LIMIT $1",
            limit,
        )

    async def update_remaining_cash(self, run_id: int, remaining: float) -> None:
        await self.db.execute(
            "UPDATE autotrader_runs SET remaining_cash=$2, updated_at=NOW() WHERE id=$1",
            run_id,
            remaining,
        )


class AutoTraderPositionModel(BaseModel):
    async def create_position(
        self,
        run_id: int,
        token_id: int,
        buy_amount: float,
        buy_price: Optional[float],
        buy_mc: Optional[float],
        qty: Optional[float],
    ) -> int:
        return await self.db.fetchval(
            """
            INSERT INTO autotrader_positions (run_id, token_id, buy_amount, buy_price, buy_mc, qty)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING id
            """,
            run_id,
            token_id,
            buy_amount,
            buy_price,
            buy_mc,
            qty,
        )

    async def list_open(self, run_id: int):
        return await self.db.fetch(
            "SELECT * FROM autotrader_positions WHERE run_id=$1 AND status='open'",
            run_id,
        )

    async def close_position(
        self,
        position_id: int,
        sell_amount: float,
        sell_price: Optional[float],
        realized_pnl: Optional[float],
        status: str = "sold",
    ) -> None:
        await self.db.execute(
            """
            UPDATE autotrader_positions
            SET sell_amount=$2, sell_price=$3, realized_pnl=$4, status=$5, updated_at=NOW()
            WHERE id=$1
            """,
            position_id,
            sell_amount,
            sell_price,
            realized_pnl,
            status,
        )


class AutoTraderEventModel(BaseModel):
    async def log(self, run_id: int, event_type: str, message: str, token_id: Optional[int] = None) -> None:
        await self.db.execute(
            """
            INSERT INTO autotrader_events (run_id, token_id, event_type, message)
            VALUES ($1,$2,$3,$4)
            """,
            run_id,
            token_id,
            event_type,
            message,
        )

    async def list_for_period(self, run_id: int, start: datetime, end: datetime, limit: int = 200, offset: int = 0):
        return await self.db.fetch(
            """
            SELECT * FROM autotrader_events
            WHERE run_id=$1 AND created_at BETWEEN $2 AND $3
            ORDER BY created_at ASC
            LIMIT $4 OFFSET $5
            """,
            run_id,
            start,
            end,
            limit,
            offset,
        )


class AutoTraderReportModel(BaseModel):
    async def enqueue_report(
        self,
        run_id: int,
        period_start: datetime,
        period_end: datetime,
        delivered_to: Optional[int],
    ) -> int:
        return await self.db.fetchval(
            """
            INSERT INTO autotrader_reports (run_id, period_start, period_end, delivered_to)
            VALUES ($1,$2,$3,$4)
            RETURNING id
            """,
            run_id,
            period_start,
            period_end,
            delivered_to,
        )

    async def set_status(self, report_id: int, status: str) -> None:
        await self.db.execute(
            "UPDATE autotrader_reports SET status=$2 WHERE id=$1",
            report_id,
            status,
        )
