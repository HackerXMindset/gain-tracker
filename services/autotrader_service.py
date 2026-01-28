from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from config import settings
from models import (
    AutoTraderRunModel,
    AutoTraderEventModel,
    AutoTraderPositionModel,
    AutoTraderReportModel,
)
from services import get_dexscreener_client
from models.token import TokenModel
from models.analytics import AnalyticsModel
from models.monitored_source import MonitoredSourceModel

logger = logging.getLogger(__name__)


class AutoTraderService:
    """
    Placeholder service for AutoTrader.
    Phase 3/4 engine will plug real trading here; for now we transition runs and log.
    """

    def __init__(self, management_bot=None) -> None:
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.runs = AutoTraderRunModel()
        self.events = AutoTraderEventModel()
        self.positions = AutoTraderPositionModel()
        self.reports = AutoTraderReportModel()
        self.token_model = TokenModel()
        self.dex = get_dexscreener_client()
        self.analytics = AnalyticsModel()
        self.sources = MonitoredSourceModel()
        self.management_bot = management_bot

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
                await self._process_reports()
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
        breakout_multiple = float(run.get("breakout_multiple") or 10.0)
        bankrupt_floor = run.get("bankrupt_floor")

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
                    # Breakout / bankruptcy alerts
                    buy_amt = float(pos["buy_amount"])
                    if buy_amt > 0 and sell_amount >= buy_amt * breakout_multiple:
                        await self.events.log(run_id, "alert", f"Breakout {sell_amount/buy_amt:.1f}x for token {pos['token_id']}")
                    if bankrupt_floor is not None and sell_amount <= float(bankrupt_floor):
                        await self.events.log(run_id, "alert", f"Bankruptcy threshold hit for token {pos['token_id']}")
                else:
                    await self.events.log(run_id, "warn", f"Could not fetch fresh price for token {pos['token_id']}")

        # Update cash after sells
        await self.runs.update_remaining_cash(run_id, remaining)

        # Stop rules
        if await self._meets_stop_rules(run, remaining):
            await self.runs.update_status(run_id, "completed")
            await self.events.log(run_id, "info", "Run stopped by stop rule")
            return

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

    async def _process_reports(self) -> None:
        reports = await self.reports.db.fetch(
            "SELECT * FROM autotrader_reports WHERE status='pending' ORDER BY created_at ASC LIMIT 10"
        )
        for rpt in reports:
            run = await self.runs.get_run(rpt["run_id"])
            if not run:
                await self.reports.set_status(rpt["id"], "failed")
                continue
            events = await self.events.list_for_period(rpt["run_id"], rpt["period_start"], rpt["period_end"], limit=200, offset=0)
            summary = self._summarize_events(events)
            text = self._render_report(run, rpt, summary, events)
            if run.get("destination_chat_id") and self.management_bot:
                await self.management_bot.send_message(run["destination_chat_id"], text)
                await self.reports.set_status(rpt["id"], "sent")
            else:
                logger.info("[AUTOTRADER] Report %s for run %s\n%s", rpt["id"], rpt["run_id"], text)
                await self.reports.set_status(rpt["id"], "sent")

    def _summarize_events(self, events):
        buys = [e for e in events if e["event_type"] == "buy"]
        sells = [e for e in events if e["event_type"] == "sell"]
        skips = [e for e in events if e["event_type"] == "skip"]
        alerts = [e for e in events if e["event_type"] == "alert"]
        return {
            "buys": len(buys),
            "sells": len(sells),
            "skips": len(skips),
            "alerts": len(alerts),
        }

    def _render_report(self, run: dict, rpt: dict, summary: dict, events) -> str:
        lines = [
            f"AutoTrader Report (Run {rpt['run_id']})",
            f"Period: {rpt['period_start']} → {rpt['period_end']}",
            f"Buys: {summary['buys']} | Sells: {summary['sells']} | Skips: {summary['skips']} | Alerts: {summary['alerts']}",
            "",
        ]
        for e in events[:100]:
            lines.append(f"{e['created_at']}: {e['event_type']} — {e['message']}")
        if len(events) > 100:
            lines.append(f"... +{len(events)-100} more")
        return "\n".join(lines)

    async def _meets_stop_rules(self, run: dict, remaining: float) -> bool:
        target_value = run.get("target_value")
        bankrupt_floor = run.get("bankrupt_floor")
        stop_at = run.get("stop_at")
        now = datetime.now(timezone.utc)
        if stop_at and stop_at <= now:
            return True
        if bankrupt_floor is not None and remaining <= float(bankrupt_floor):
            return True
        if target_value is not None and remaining >= float(target_value):
            return True
        return False

    async def _pick_fresh_tokens(self, run: dict, limit: int):
        mode = run.get("channel_mode", "single")
        channels = run.get("channels") or []

        base_query = """
            SELECT t.id, t.address
            FROM tokens_tracked t
            WHERE t.status='active'
        """
        params = []
        if mode in {"single", "multi"} and channels:
            base_query += " AND t.first_seen_source = ANY($1)"
            params.append(channels)
            base_query += " ORDER BY t.first_seen_at DESC LIMIT $2"
            params.append(limit)
            return await self.token_model.db.fetch(base_query, *params)
        else:
            base_query += " ORDER BY t.first_seen_at DESC LIMIT $1"
            return await self.token_model.db.fetch(base_query, limit)

    async def _attempt_buy(self, run_id: int, token: dict, spend: float, max_retries: int, freshness_secs: int) -> bool:
        token_id = token["id"]
        address = token["address"]
        price, mc = await self._fetch_fresh_price(address, max_retries, freshness_secs)
        if price is None or mc is None or price <= 0:
            await self.events.log(run_id, "skip", f"Stale or missing price for {address[:8]}")
            return False
        # Liquidity/fee parity with /invest: require liquidity >= 0.1 * mc
        pair = await self.dex.fetch_token(address, chain_id="solana", use_cache=False)
        liq = self.dex.get_liquidity(pair) if pair else None
        if liq is None or mc is None or (liq is not None and mc is not None and liq < (mc * Decimal("0.10"))):
            await self.events.log(run_id, "skip", f"Low liquidity for {address[:8]}")
            return False
        eff_price, eff_qty, fees = self._apply_fees_and_slippage(spend, price, liq)
        if eff_qty <= 0:
            await self.events.log(run_id, "skip", f"Fees/slippage zeroed qty for {address[:8]}")
            return False
        await self.positions.create_position(run_id, token_id, spend, eff_price, mc, eff_qty)
        await self.events.log(run_id, "buy", f"Bought {address[:8]} spend ${spend:,.2f} @ ${eff_price:.8f} (qty {eff_qty:.6f}, fees {fees})")
        return True

    async def _fetch_fresh_price(self, address: str, max_retries: int, freshness_secs: int):
        # Try cached first
        cached = self.dex.get_cached_pair(address, chain_id="solana", freshness_secs=freshness_secs)
        if cached:
            price = self.dex.get_price(cached)
            mc = self.dex.get_market_cap(cached)
            if price and mc:
                return price, mc

        attempt = 0
        last_data = None
        while attempt < max_retries:
            attempt += 1
            pair = await self.dex.fetch_token(address, chain_id="solana", use_cache=False)
            if pair:
                mc = self.dex.get_market_cap(pair)
                price = self.dex.get_price(pair)
                last_data = (price, mc)
                if price and mc:
                    return price, mc
            await asyncio.sleep(0.5)
        return last_data if last_data else (None, None)

    def _apply_fees_and_slippage(self, spend: float, price: Decimal, liquidity: Optional[Decimal]) -> Tuple[Decimal, Decimal, str]:
        """
        Approximate /invest model:
        - Slippage proportional to trade size vs liquidity (cap 5%)
        - Trojan fee 1% of notional
        - Gas cost fixed $0.70 (0.0035 SOL @ $200)
        """
        liq = liquidity or Decimal("0")
        spend_dec = Decimal(str(spend))
        slippage_pct = Decimal("0")
        if liq > 0:
            try:
                slippage_pct = min(Decimal("0.05"), spend_dec / liq)
            except (InvalidOperation, ZeroDivisionError):
                slippage_pct = Decimal("0.05")
        fee_pct = Decimal("0.01")
        gas_cost = Decimal("0.70")

        fee_cost = spend_dec * fee_pct
        net_after_fees = spend_dec - fee_cost - gas_cost
        if net_after_fees <= 0:
            return price, Decimal("0"), f"fee={fee_cost:.4f},gas={gas_cost:.4f},slip={slippage_pct:.4f}"

        effective_price = price * (Decimal("1") + slippage_pct)
        qty = net_after_fees / effective_price if effective_price > 0 else Decimal("0")
        return effective_price, qty, f"fee={fee_cost:.4f},gas={gas_cost:.4f},slip={slippage_pct:.4f}"

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
