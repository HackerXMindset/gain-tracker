from __future__ import annotations

import asyncio
import heapq
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from alerts.dispatcher import GainAlertDispatcher
from alerts.thresholds import compute_threshold, should_fire_gain_alert
from charts.chart_fetcher import ChartFetcher
from db import db
from models import MonitoredSourceModel, SettingsModel, TokenModel
from services import get_dexscreener_client, get_jupiter_service
from utils.tier_calculator import calculate_next_poll_time, format_duration
from utils.structured_logging import log_event

logger = logging.getLogger(__name__)

_dex_service_instance: Optional["DexService"] = None


def get_dex_service() -> "DexService":
    global _dex_service_instance
    if _dex_service_instance is None:
        _dex_service_instance = DexService()
    return _dex_service_instance


class DexService:
    def __init__(self) -> None:
        self.token_model = TokenModel()
        self.source_model = MonitoredSourceModel(db)
        self.settings_model = SettingsModel(db)
        self.dex_client = get_dexscreener_client()
        self.jupiter_service = get_jupiter_service()
        self.dispatcher = GainAlertDispatcher(self.settings_model, self.source_model, self.dex_client)

        self.userbot_manager = None
        self.chart_fetcher: Optional[ChartFetcher] = None
        self.management_bot = None

        self.running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._poll_heap: List[Tuple[datetime, int, str]] = []
        self._tokens_in_heap: set[int] = set()
        self._semaphore = asyncio.Semaphore(5)

    def set_userbot_manager(self, manager) -> None:
        self.userbot_manager = manager
        if manager:
            logger.info("UserbotManager set on Dex service")
            self.chart_fetcher = ChartFetcher(db, manager)
        else:
            logger.info("UserbotManager cleared on Dex service")
            self.chart_fetcher = None

    def set_management_bot(self, management_bot) -> None:
        self.management_bot = management_bot
        if management_bot:
            logger.info("Management bot set on Dex service")
        else:
            logger.info("Management bot cleared on Dex service")

    async def start(self) -> None:
        if self.running:
            return

        self.running = True
        await self.dex_client.start()
        await self.jupiter_service.start()
        await self._load_tokens_into_scheduler()
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
        logger.info("Dex service started with scheduler")

    async def stop(self) -> None:
        if not self.running:
            return

        self.running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

        await self.dex_client.stop()
        await self.jupiter_service.stop()
        logger.info("Dex service stopped")

    async def get_service_stats(self) -> Dict[str, Any]:
        try:
            token_stats = await self.token_model.get_token_stats()
        except Exception as exc:
            logger.error("Error fetching token stats: %s", exc, exc_info=True)
            token_stats = {}

        return {
            "running": self.running,
            "scheduler_active": self._scheduler_task is not None and not self._scheduler_task.done(),
            "tokens_in_queue": len(self._poll_heap),
            "tokens": token_stats,
        }

    async def _load_tokens_into_scheduler(self) -> None:
        try:
            tokens = await self.token_model.get_all_active_scheduled_tokens()
            for token in tokens:
                next_poll = token.get("next_poll_at")
                token_id = token["id"]
                if next_poll:
                    heapq.heappush(self._poll_heap, (next_poll, token_id, token["address"]))
                    self._tokens_in_heap.add(token_id)
            logger.info("Loaded %s tokens into scheduler", len(tokens))
        except Exception as exc:
            logger.error("Error loading tokens into scheduler: %s", exc, exc_info=True)

    async def _run_scheduler(self) -> None:
        logger.info("[SCHEDULER] Starting scheduler loop")
        while self.running:
            try:
                now = datetime.now(timezone.utc)
                tokens_to_poll = []

                while self._poll_heap and self._poll_heap[0][0] <= now:
                    _, token_id, address = heapq.heappop(self._poll_heap)
                    self._tokens_in_heap.discard(token_id)
                    tokens_to_poll.append((token_id, address))

                if tokens_to_poll:
                    logger.debug("[SCHEDULER] Polling %s token(s)", len(tokens_to_poll))
                    tasks = [self._poll_token(token_id, address) for token_id, address in tokens_to_poll]
                    await asyncio.gather(*tasks, return_exceptions=True)

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[SCHEDULER] Error in scheduler loop: %s", exc, exc_info=True)
                await asyncio.sleep(10)

        logger.info("[SCHEDULER] Scheduler loop stopped")

    async def _poll_token(self, token_id: int, address: str) -> None:
        async with self._semaphore:
            try:
                token = await db.fetchrow("SELECT * FROM tokens_tracked WHERE id = $1", token_id)
                if not token or token.get("status") != "active":
                    logger.debug("[POLL] Token %s inactive, skipping", address[:8])
                    return

                raw_chain_id = self._determine_chain_id(token, address)
                chain_id = self._normalise_chain_id(raw_chain_id, address)

                market_cap: Optional[Decimal] = None
                ticker: Optional[str] = None

                if chain_id == "solana":
                    jup_data = await self.jupiter_service.get_token_data(address, use_cache=False)
                    if jup_data:
                        market_cap = self.jupiter_service.get_market_cap(jup_data)
                        ticker = ticker or self.jupiter_service.get_ticker(jup_data)

                if market_cap is None:
                    pairs = await self.dex_client.fetch_token_pairs(
                        address,
                        chain_id=chain_id,
                        use_cache=False,
                    )
                    if pairs is None:
                        pair_data = None
                    elif not pairs:
                        logger.info("[POLL] %s has no DexScreener pools; stopping token", address[:8])
                        await self._stop_token(token_id, address, "dex_no_pools")
                        return
                    else:
                        pair_data = self.dex_client._select_preferred_pair(pairs)

                    if pair_data:
                        market_cap = self.dex_client.get_market_cap(pair_data)
                        ticker = self.dex_client.get_ticker(pair_data)

                if market_cap and market_cap > 0:
                    await self.token_model.update_market_cap(token_id, market_cap, ticker)
                    await self.token_model.update_dex_refresh_time(token_id)

                    peak_mc = token.get("peak_mc") or Decimal(0)
                    if market_cap > peak_mc:
                        await self.token_model.update_peak_mc(token_id, market_cap)

                    await self._evaluate_gain_alert(token, market_cap, address, ticker)

                    should_stop, stop_reason = await self._evaluate_stop_loss(token, market_cap)
                    if should_stop:
                        await self._stop_token(token_id, address, stop_reason or "stop_loss")
                        return
                else:
                    logger.debug("[POLL] %s missing market cap", address[:8])

                first_seen_at = token.get("first_seen_at")
                if first_seen_at:
                    tier_name, next_poll = calculate_next_poll_time(first_seen_at)
                    await self.token_model.update_tier(token_id, tier_name, next_poll)

                    if token_id not in self._tokens_in_heap:
                        heapq.heappush(self._poll_heap, (next_poll, token_id, address))
                        self._tokens_in_heap.add(token_id)
                        logger.debug("[POLL] %s rescheduled to %s at %s", address[:8], tier_name, next_poll)
                    else:
                        logger.debug("[POLL] %s already in heap, skipping reschedule", address[:8])
            except Exception as exc:
                logger.error("[POLL] Error polling token %s: %s", address[:8], exc, exc_info=True)
                try:
                    if token_id not in self._tokens_in_heap:
                        next_poll = datetime.now(timezone.utc) + timedelta(seconds=30)
                        heapq.heappush(self._poll_heap, (next_poll, token_id, address))
                        self._tokens_in_heap.add(token_id)
                except Exception:
                    pass

    async def _evaluate_gain_alert(
        self,
        token: Dict[str, Any],
        current_mc: Decimal,
        address: str,
        ticker: Optional[str],
    ) -> None:
        try:
            token_id = token["id"]
            last_alert_mc = token.get("last_alert_mc") or Decimal(0)
            first_seen_mc = token.get("first_seen_mc") or Decimal(0)
            first_seen_at = token.get("first_seen_at")

            settings_dict = await self.settings_model.get_gain_alert_settings()
            gain_threshold_pct = Decimal(str(settings_dict["gain_threshold_pct"]))

            baseline_mc = last_alert_mc if last_alert_mc and last_alert_mc > 0 else first_seen_mc
            if not baseline_mc or baseline_mc <= 0:
                logger.debug(
                    "[GAIN_ALERT] %s has no valid baseline (first_seen_mc=%s, last_alert_mc=%s)",
                    address[:8],
                    first_seen_mc,
                    last_alert_mc,
                )
                return

            if first_seen_mc <= 0:
                logger.debug("[GAIN_ALERT] %s has invalid first_seen_mc=%s", address[:8], first_seen_mc)
                return

            threshold_mc = compute_threshold(baseline_mc, gain_threshold_pct)
            if not should_fire_gain_alert(current_mc, baseline_mc, gain_threshold_pct):
                return

            multiplier_value = float(current_mc / first_seen_mc)
            elapsed = self._format_elapsed_time(first_seen_at)
            ticker_display = ticker or address[:8]

            template_context = {
                "address": address,
                "token_symbol": ticker_display,
                "multiplier": f"{multiplier_value:.1f}x",
                "first_market_cap": self._format_mc_shorthand(first_seen_mc),
                "current_market_cap": self._format_mc_shorthand(current_mc),
                "elapsed_time": elapsed,
                "gain_emoji": self._multiplier_to_emoji(multiplier_value),
            }

            log_event(
                logger,
                "gain_alert_triggered",
                token_address=address,
                current_mc=str(current_mc),
                baseline_mc=str(baseline_mc),
                gain_threshold_pct=str(gain_threshold_pct),
            )

            dispatched = await self.dispatcher.dispatch_gain_alert(
                token,
                template_context,
                address,
                current_mc,
                userbot_manager=self.userbot_manager,
                management_bot=self.management_bot,
                chart_fetcher=self.chart_fetcher,
                format_mc_shorthand=self._format_mc_shorthand,
            )

            if dispatched:
                await self.token_model.update_last_alert_mc(token_id, current_mc)
                await self.promote_to_tier_b(token_id)
                logger.info("[GAIN_ALERT] %s bookkeeping complete: last_alert_mc updated", address[:8])
            else:
                logger.debug("[GAIN_ALERT] %s had no eligible destinations; skipping bookkeeping", address[:8])
        except Exception as exc:
            logger.error("Error evaluating gain alert for %s: %s", address[:8], exc, exc_info=True)

    async def _evaluate_stop_loss(self, token: Dict[str, Any], current_mc: Decimal) -> Tuple[bool, Optional[str]]:
        try:
            settings_dict = await self.settings_model.get_gain_alert_settings()
            drop_threshold_pct = settings_dict["drop_threshold_pct"]
            drop_floor_mc = Decimal(str(settings_dict["drop_floor_mc"]))

            first_seen_mc = token.get("first_seen_mc")
            if not first_seen_mc or first_seen_mc <= 0:
                return (False, None)

            drop_threshold = first_seen_mc * Decimal(str(drop_threshold_pct))
            if current_mc <= drop_threshold:
                return (True, "mc_drop_70")
            if current_mc <= drop_floor_mc:
                return (True, "mc_below_floor")
            return (False, None)
        except Exception as exc:
            logger.error("Error evaluating stop-loss: %s", exc, exc_info=True)
            return (False, None)

    async def _stop_token(self, token_id: int, address: str, reason: str) -> None:
        try:
            await self.token_model.set_status(token_id, "stopped")
            await self.token_model.set_stop_reason(token_id, reason)
            logger.info("[STOP] Token %s stopped: %s", address[:8], reason)
        except Exception as exc:
            logger.error("Error stopping token %s: %s", address[:8], exc, exc_info=True)

    async def add_token(self, token_address: str) -> Dict[str, Any]:
        try:
            existing = await self.token_model.get_by_address(token_address)
            if existing:
                return {
                    "success": False,
                    "error": "Token already being tracked",
                    "token": dict(existing),
                }

            initial_mc = Decimal("0")
            token = await self.token_model.create_or_update(token_address, initial_mc, ticker=None)
            logger.info("[INIT] Registered %s for tracking", token_address[:8])
            return {"success": True, "token": dict(token), "initial_mc": float(initial_mc)}
        except Exception as exc:
            logger.error("Error adding token %s: %s", token_address[:8], exc, exc_info=True)
            return {"success": False, "error": str(exc)}

    async def promote_to_tier_b(self, token_id: int) -> None:
        try:
            next_poll = datetime.now(timezone.utc) + timedelta(seconds=30)
            await self.token_model.update_tier(token_id, "tier_b", next_poll)

            token = await db.fetchrow("SELECT * FROM tokens_tracked WHERE id = $1", token_id)
            if token:
                if token_id not in self._tokens_in_heap:
                    heapq.heappush(self._poll_heap, (next_poll, token_id, token["address"]))
                    self._tokens_in_heap.add(token_id)
                    logger.info("[TIER_B] Token %s promoted to Tier B", token_id)
                else:
                    logger.debug("[TIER_B] Token %s already in heap", token_id)
        except Exception as exc:
            logger.error("Error promoting token %s to Tier B: %s", token_id, exc, exc_info=True)

    async def add_token_to_scheduler(self, token_id: int) -> None:
        try:
            token = await db.fetchrow("SELECT * FROM tokens_tracked WHERE id = $1", token_id)
            if not token:
                logger.warning("[SCHEDULER] Cannot add token %s: not found", token_id)
                return

            next_poll = token.get("next_poll_at")
            address = token.get("address")
            if not next_poll or not address:
                logger.warning("[SCHEDULER] Cannot add token %s: missing next_poll_at or address", token_id)
                return

            if token_id not in self._tokens_in_heap:
                heapq.heappush(self._poll_heap, (next_poll, token_id, address))
                self._tokens_in_heap.add(token_id)
                logger.info("[SCHEDULER] Added token %s to scheduler", address[:8])
            else:
                logger.debug("[SCHEDULER] Token %s already in heap", token_id)
        except Exception as exc:
            logger.error("Error adding token %s to scheduler: %s", token_id, exc, exc_info=True)

    @staticmethod
    def _determine_chain_id(token: Dict[str, Any], address: str) -> str:
        heuristic = None
        if address.lower().startswith("0x") and len(address) == 42:
            heuristic = "bsc"
        elif len(address) in (32, 44):
            heuristic = "solana"

        blockchain = None
        if token:
            blockchain = token.get("blockchain") or token.get("chain")
        if heuristic:
            return heuristic
        if blockchain:
            return str(blockchain).upper()
        return "sol"

    @staticmethod
    def _normalise_chain_id(chain_id: Optional[str], address: str) -> str:
        if not chain_id:
            if address.lower().startswith("0x") and len(address) == 42:
                candidate = "bsc"
            else:
                candidate = "solana"
        else:
            candidate = str(chain_id).lower()

        if candidate in ("sol", "solana", "solana-mainnet"):
            return "solana"
        if candidate in ("bsc", "bnb", "bep20", "binance"):
            return "bsc"
        return candidate

    @staticmethod
    def _format_elapsed_time(first_seen_at: Optional[datetime]) -> str:
        if not first_seen_at:
            return "N/A"
        now = datetime.now(timezone.utc)
        if first_seen_at.tzinfo is None:
            first_seen_at = first_seen_at.replace(tzinfo=timezone.utc)
        elapsed_seconds = int((now - first_seen_at).total_seconds())
        return format_duration(elapsed_seconds)

    @staticmethod
    def _format_mc_shorthand(mc: Decimal) -> str:
        value = float(mc)
        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:.0f}"

    @staticmethod
    def _multiplier_to_emoji(multiplier_value: float) -> str:
        if multiplier_value >= 100:
            return "⭐"
        if multiplier_value >= 50:
            return "💫"
        if multiplier_value >= 20:
            return "🌙"
        if multiplier_value >= 10:
            return "🚀"
        if multiplier_value >= 5:
            return "🔥"
        if multiplier_value >= 3:
            return "🌕"
        if multiplier_value >= 1.5:
            return "🎉"
        return "📈"
