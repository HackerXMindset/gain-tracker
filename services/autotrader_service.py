from __future__ import annotations

import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone

from config import settings
from models import (
    AutoTraderRunModel,
    AutoTraderEventModel,
    AutoTraderPositionModel,
)
from services import get_dexscreener_client
from models.token import TokenModel

logger = logging.getLogger(__name__)


class AutoTraderService:
    """
    Placeholder service for AutoTrader.
    Phase 3/4 engine will plug real trading here; for now we transition runs and log.
    """

    def __init__(self) -> None:
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.runs = AutoTraderRunModel()
        self.events = AutoTraderEventModel()
        self.positions = AutoTraderPositionModel()
        self.token_model = TokenModel()
        self.dex = get_dexscreener_client()

    async def start(self) -> None:
        if self.running:
            return
        if not settings.enable_autotrader:
            logger.info("[AUTOTRADER] Disabled via config.")
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="autotrader_service")
        logger.info("[AUTOTRADER] Service started")

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[AUTOTRADER] Service stopped")

    async def _loop(self) -> None:
        while self.running:
            try:
                await self._process_pending()
                await self._process_running()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[AUTOTRADER] Loop error: %s", exc, exc_info=True)
                await asyncio.sleep(5)

    async def _process_pending(self) -> None:
        rows = await self.runs.db.fetch(
            "SELECT * FROM autotrader_runs WHERE status='pending' ORDER BY created_at ASC LIMIT 5"
        )
        for row in rows:
            run_id = row["id"]
            await self.runs.update_status(run_id, "running")
            await self.events.log(run_id, "info", "Run started")

    async def _process_running(self) -> None:
        rows = await self.runs.db.fetch(
            "SELECT * FROM autotrader_runs WHERE status='running' ORDER BY updated_at ASC LIMIT 10"
        )
        for row in rows:
            run_id = row["id"]
            try:
                await self._process_run(row)
            except Exception as exc:
                logger.error("[AUTOTRADER] Run %s error: %s", run_id, exc, exc_info=True)
                await self.events.log(run_id, "error", f"Run error: {exc}")
                await self.runs.update_status(run_id, "failed")

    async def _process_run(self, run: dict) -> None:
        run_id = run["id"]
        coin_cap = run.get("coin_cap") or settings.autotrader_default_coin_cap
        per_coin = float(run["per_coin_spend"])
        remaining = float(run["remaining_cash"])
        hold_seconds = int(run["hold_seconds"])
        freshness_secs = int(run.get("freshness_secs") or settings.autotrader_freshness_secs)
        max_retries = int(run.get("max_retries") or settings.autotrader_max_retries)

        open_positions = await self.positions.list_open(run_id)
        open_count = len(open_positions)

        # Sell due positions
        now = datetime.now(timezone.utc)
        for pos in open_positions:
            age = (now - pos["created_at"]).total_seconds()
            if age >= hold_seconds:
                sell_amount, sell_price = await self._fetch_sell_value(pos, max_retries, freshness_secs)
                realized = None
                if sell_amount is not None:
                    realized = sell_amount - float(pos["buy_amount"])
                    remaining += sell_amount
                    await self.positions.close_position(pos["id"], sell_amount, sell_price, realized, status="sold")
                    await self.events.log(run_id, "sell", f"Sold token {pos['token_id']} for ${sell_amount:,.2f}")
                else:
                    await self.events.log(run_id, "warn", f"Could not fetch fresh price for token {pos['token_id']}")

        # Update cash after sells
        await self.runs.update_remaining_cash(run_id, remaining)

        # Check coin cap
        if open_count >= coin_cap:
            await self.events.log(run_id, "info", f"Coin cap reached ({open_count}/{coin_cap})")
            return

        to_buy = coin_cap - open_count
        if remaining <= 0:
            await self.events.log(run_id, "warn", "No cash remaining")
            return

        tokens = await self._pick_fresh_tokens(run, limit=to_buy)
        for token in tokens:
            if remaining <= 0:
                await self.events.log(run_id, "warn", "No cash remaining")
                break
            spend = per_coin if remaining >= per_coin else remaining
            ok = await self._attempt_buy(run_id, token, spend, max_retries, freshness_secs)
            if ok:
                remaining -= spend
                await self.runs.update_remaining_cash(run_id, remaining)

        # If nothing to do and no positions, mark completed
        open_positions = await self.positions.list_open(run_id)
        if not open_positions and remaining < per_coin:
            await self.runs.update_status(run_id, "completed")
            await self.events.log(run_id, "info", "Run completed (cash exhausted or cap reached)")

    async def _pick_fresh_tokens(self, run: dict, limit: int):
        # Simplified: pick newest active tokens
        rows = await self.token_model.db.fetch(
            """
            SELECT id, address
            FROM tokens_tracked
            WHERE status='active'
            ORDER BY first_seen_at DESC
            LIMIT $1
            """,
            limit,
        )
        return rows

    async def _attempt_buy(self, run_id: int, token: dict, spend: float, max_retries: int, freshness_secs: int) -> bool:
        token_id = token["id"]
        address = token["address"]
        price, mc = await self._fetch_fresh_price(address, max_retries, freshness_secs)
        if price is None or mc is None or price <= 0:
            await self.events.log(run_id, "skip", f"Stale or missing price for {address[:8]}")
            return False
        qty = spend / price
        await self.positions.create_position(run_id, token_id, spend, price, mc, qty)
        await self.events.log(run_id, "buy", f"Bought {address[:8]} spend ${spend:,.2f} @ ${price:.8f}")
        return True

    async def _fetch_fresh_price(self, address: str, max_retries: int, freshness_secs: int):
        attempt = 0
        last_data = None
        while attempt < max_retries:
            attempt += 1
            pair = await self.dex.fetch_token(address, chain_id="solana", use_cache=False)
            if pair:
                mc = self.dex.get_market_cap(pair)
                price = self.dex.get_price(pair)
                ts = datetime.now(timezone.utc)
                last_data = (price, mc, ts)
                # use immediate freshness (just fetched)
                if price and mc:
                    return price, mc
            await asyncio.sleep(0.5)
        return (last_data[0], last_data[1]) if last_data else (None, None)

    async def _fetch_sell_value(self, pos: dict, max_retries: int, freshness_secs: int):
        token_id = pos["token_id"]
        token = await self.token_model.get_by_id(token_id)
        if not token:
            return None, None
        price, mc = await self._fetch_fresh_price(token["address"], max_retries, freshness_secs)
        if price is None:
            return None, None
        qty = float(pos["qty"] or 0)
        if qty <= 0:
            return None, price
        sell_amount = qty * price
        return sell_amount, price
