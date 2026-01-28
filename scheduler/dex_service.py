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
from models import AnalyticsModel, MonitoredSourceModel, SettingsModel, TokenModel
from models.snapshot_tasks import SnapshotTasksModel
from services import get_dexscreener_client, get_jupiter_service, get_dexpaprika_service
from services.gain_alert_api import GainAlertAPI
from utils.tier_calculator import calculate_next_poll_time, format_duration
from config import settings
from utils.structured_logging import log_event

logger = logging.getLogger(__name__)

_dex_service_instance: Optional["DexService"] = None

SNAPSHOT_TOLERANCE_MINUTES = 10
SNAPSHOT_PRIORITY_WINDOW_SECONDS = 120
SNAPSHOT_PRIORITY_LEAD_SECONDS = 30


def get_dex_service() -> "DexService":
    global _dex_service_instance
    if _dex_service_instance is None:
        _dex_service_instance = DexService()
    return _dex_service_instance


class DexService:
    def __init__(self) -> None:
        self.token_model = TokenModel()
        self.analytics_model = AnalyticsModel()
        self.snapshot_model = SnapshotTasksModel(db)
        self.source_model = MonitoredSourceModel(db)
        self.settings_model = SettingsModel(db)
        self.dex_client = get_dexscreener_client()
        self.jupiter_service = get_jupiter_service()
        self.dexpaprika_service = get_dexpaprika_service()
        self.gain_alert_api = GainAlertAPI()
        self.dispatcher = GainAlertDispatcher(self.settings_model, self.source_model, self.dex_client)

        self.userbot_manager = None
        self.chart_fetcher: Optional[ChartFetcher] = None
        self.management_bot = None

        self.running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._poll_heap: List[Tuple[datetime, int, str]] = []
        self._snapshot_heap: List[Tuple[datetime, int, str]] = []
        self._scheduled_times: Dict[int, datetime] = {}
        self._snapshot_times: Dict[int, datetime] = {}
        self._semaphore = asyncio.Semaphore(5)
        self._hold_timeframes_cache: List[Dict[str, Any]] = []
        self._hold_timeframes_cache_ts: Optional[datetime] = None
        self._snapshot_tasks_cache: Dict[int, datetime] = {}

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
        await self.dexpaprika_service.start()
        if settings.new_scheduler:
            await self._create_snapshot_tasks_for_existing()
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
        await self.dexpaprika_service.stop()
        logger.info("Dex service stopped")

    async def _create_snapshot_tasks_for_existing(self) -> None:
        rows = await db.fetch("SELECT id, first_seen_at FROM tokens_tracked WHERE first_seen_at IS NOT NULL")
        timeframes = await self.analytics_model.get_hold_timeframes(defaults_only=False)
        seconds_list = [int(tf["seconds"]) for tf in timeframes if tf.get("seconds")]
        for row in rows:
            await self.snapshot_model.backfill_for_token(row["id"], row["first_seen_at"], seconds_list)

    async def get_service_stats(self) -> Dict[str, Any]:
        try:
            token_stats = await self.token_model.get_token_stats()
        except Exception as exc:
            logger.error("Error fetching token stats: %s", exc, exc_info=True)
            token_stats = {}

        return {
            "running": self.running,
            "scheduler_active": self._scheduler_task is not None and not self._scheduler_task.done(),
            "tokens_in_queue": len(self._poll_heap) + len(self._snapshot_heap),
            "tokens": token_stats,
        }

    async def _load_tokens_into_scheduler(self) -> None:
        try:
            tokens = await self.token_model.get_all_active_scheduled_tokens()
            for token in tokens:
                next_poll = token.get("next_poll_at")
                token_id = token["id"]
                if next_poll:
                    self._schedule_poll(token_id, token["address"], next_poll)
                if settings.new_scheduler:
                    await self._backfill_snapshot_tasks_for_token(token)
            logger.info("Loaded %s tokens into scheduler", len(tokens))
        except Exception as exc:
            logger.error("Error loading tokens into scheduler: %s", exc, exc_info=True)

    async def _backfill_snapshot_tasks_for_token(self, token: Dict[str, Any]) -> None:
        first_seen_at = token.get("first_seen_at")
        if not first_seen_at:
            return
        timeframes = await self.analytics_model.get_hold_timeframes(defaults_only=False)
        seconds_list = [int(tf["seconds"]) for tf in timeframes if tf.get("seconds")]
        await self.snapshot_model.backfill_for_token(token["id"], first_seen_at, seconds_list)

    async def _sync_snapshot_tasks_into_heap(self, now: datetime) -> None:
        # No-op when using dedicated snapshot scheduler
        return

    def _schedule_poll(self, token_id: int, address: str, next_poll: Optional[datetime]) -> None:
        if not next_poll or not address:
            return
        now = datetime.now(timezone.utc)
        prev = self._scheduled_times.get(token_id)
        if prev is None or next_poll < prev or prev <= now:
            self._scheduled_times[token_id] = next_poll
            heapq.heappush(self._poll_heap, (next_poll, token_id, address))
            logger.debug("[SCHEDULER] Scheduled %s at %s", address[:8], next_poll)

    def _schedule_snapshot(self, token_id: int, address: str, target_time: Optional[datetime]) -> None:
        if settings.new_scheduler:
            return
        if not target_time:
            return
        now = datetime.now(timezone.utc)
        prev = self._snapshot_times.get(token_id)
        if prev is None or target_time != prev or prev <= now:
            self._snapshot_times[token_id] = target_time
            # store task_id placeholder as token_id; address looked up later
            heapq.heappush(self._snapshot_heap, (target_time, token_id, token_id))
            logger.debug("[SCHEDULER] Snapshot scheduled %s at %s", address[:8] if address else str(token_id), target_time)

    async def _run_scheduler(self) -> None:
        logger.info("[SCHEDULER] Starting scheduler loop")
        while self.running:
            try:
                now = datetime.now(timezone.utc)
                tokens_to_poll: Dict[int, str] = {}

                if not settings.new_scheduler:
                    while self._snapshot_heap and self._snapshot_heap[0][0] <= now:
                        scheduled_at, task_id, token_id = heapq.heappop(self._snapshot_heap)
                        if self._snapshot_times.get(task_id) != scheduled_at:
                            continue
                        tokens_to_poll[task_id] = None

                while self._poll_heap and self._poll_heap[0][0] <= now:
                    scheduled_at, token_id, address = heapq.heappop(self._poll_heap)
                    if self._scheduled_times.get(token_id) != scheduled_at:
                        continue
                    tokens_to_poll[token_id] = address

                if tokens_to_poll:
                    logger.debug("[SCHEDULER] Polling %s token(s)", len(tokens_to_poll))
                    tasks = [self._poll_token(token_id, address) for token_id, address in tokens_to_poll.items()]
                    await asyncio.gather(*tasks, return_exceptions=True)

                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[SCHEDULER] Error in scheduler loop: %s", exc, exc_info=True)
                await asyncio.sleep(10)

        logger.info("[SCHEDULER] Scheduler loop stopped")

    async def _poll_token(self, token_id: int, address: Optional[str]) -> None:
        async with self._semaphore:
            try:
                # If token_id is actually a snapshot_task id (new scheduler), resolve it
                if settings.new_scheduler:
                    task = await db.fetchrow("SELECT * FROM snapshot_tasks WHERE id = $1", token_id)
                    if task:
                        token_id = task["token_id"]

                token = await db.fetchrow("SELECT * FROM tokens_tracked WHERE id = $1", token_id)
                if not token:
                    logger.debug("[POLL] Token %s missing, skipping", (address or 'unknown')[:8])
                    return

                if address is None:
                    address = token.get("address")
                
                status = token.get("status")
                tracking_until = token.get("tracking_until")
                now = datetime.now(timezone.utc)
                history_only = status != "active"

                if history_only:
                    if not tracking_until or tracking_until <= now:
                        logger.debug("[POLL] Token %s tracking window ended, skipping", address[:8])
                        return

                raw_chain_id = self._determine_chain_id(token, address)
                chain_id = self._normalise_chain_id(raw_chain_id, address)

                market_cap: Optional[Decimal] = None
                ticker: Optional[str] = None

                is_solana = chain_id == "solana"
                jup_data = None
                dexpaprika_data = None
                pair_data = None
                dex_pairs_checked = False
                dex_no_pools = False

                async def _fetch_jupiter_mc() -> Tuple[Optional[Decimal], Optional[str]]:
                    nonlocal jup_data
                    if not is_solana:
                        return None, None
                    if jup_data is None:
                        jup_data = await self.jupiter_service.get_token_data(address, use_cache=False)
                    if not jup_data:
                        return None, None
                    return (
                        self.jupiter_service.get_market_cap(jup_data),
                        self.jupiter_service.get_ticker(jup_data),
                    )

                async def _fetch_dexpaprika_mc() -> Tuple[Optional[Decimal], Optional[str]]:
                    nonlocal dexpaprika_data
                    if not is_solana:
                        return None, None
                    if dexpaprika_data is None:
                        dexpaprika_data = await self.dexpaprika_service.get_token_data(
                            address, network="solana", use_cache=False
                        )
                    if not dexpaprika_data:
                        return None, None
                    return (
                        self.dexpaprika_service.get_market_cap(dexpaprika_data),
                        None,
                    )

                async def _prepare_dex_pair() -> None:
                    nonlocal pair_data, dex_pairs_checked, dex_no_pools
                    if dex_pairs_checked:
                        return
                    dex_pairs_checked = True
                    pairs = await self.dex_client.fetch_token_pairs(
                        address,
                        chain_id=chain_id,
                        use_cache=False,
                    )
                    if pairs is None:
                        pair_data = None
                        return
                    if not pairs:
                        dex_no_pools = True
                        return
                    pair_data = self.dex_client._select_preferred_pair(pairs)

                async def _fetch_dex_mc(stop_on_empty: bool) -> Tuple[Optional[Decimal], Optional[str], bool]:
                    await _prepare_dex_pair()
                    if dex_no_pools and stop_on_empty:
                        return None, None, True
                    if pair_data:
                        return (
                            self.dex_client.get_market_cap(pair_data),
                            self.dex_client.get_ticker(pair_data),
                            False,
                        )
                    return None, None, False

                async def _get_default_hold_timeframes() -> List[Dict[str, Any]]:
                    now_local = datetime.now(timezone.utc)
                    if (
                        self._hold_timeframes_cache_ts
                        and (now_local - self._hold_timeframes_cache_ts).total_seconds() < 300
                    ):
                        return self._hold_timeframes_cache
                    rows = await self.analytics_model.get_hold_timeframes(defaults_only=False)
                    self._hold_timeframes_cache = [dict(r) for r in rows]
                    self._hold_timeframes_cache.sort(key=lambda tf: int(tf.get("seconds") or 0))
                    self._hold_timeframes_cache_ts = now_local
                    return self._hold_timeframes_cache

                async def _snapshot_due(first_seen_at: Optional[datetime]) -> List[Dict[str, Any]]:
                    if not first_seen_at:
                        return []
                    if first_seen_at.tzinfo is None:
                        fs = first_seen_at.replace(tzinfo=timezone.utc)
                    else:
                        fs = first_seen_at
                    now_local = datetime.now(timezone.utc)
                    age_seconds = (now_local - fs).total_seconds()
                    if age_seconds < 0:
                        return []
                    timeframes = await _get_default_hold_timeframes()
                    if not timeframes:
                        return []
                    tolerance_minutes = SNAPSHOT_TOLERANCE_MINUTES
                    tolerance_seconds = tolerance_minutes * 60
                    due: List[Dict[str, Any]] = []
                    for tf in timeframes:
                        seconds = int(tf.get("seconds") or 0)
                        if seconds <= 0:
                            continue
                        if abs(age_seconds - seconds) <= tolerance_seconds:
                            target_time = fs + timedelta(seconds=seconds)
                            existing = await self.analytics_model.get_mc_at_time(
                                token_id, target_time, tolerance_minutes=tolerance_minutes
                            )
                            if existing is None:
                                due.append(tf)
                    return due

                async def _get_next_snapshot_at(first_seen_at: Optional[datetime]) -> Optional[datetime]:
                    if not first_seen_at:
                        return None
                    if first_seen_at.tzinfo is None:
                        fs = first_seen_at.replace(tzinfo=timezone.utc)
                    else:
                        fs = first_seen_at
                    now_local = datetime.now(timezone.utc)
                    timeframes = await _get_default_hold_timeframes()
                    if not timeframes:
                        return None
                    tolerance_minutes = SNAPSHOT_TOLERANCE_MINUTES
                    for tf in timeframes:
                        seconds = int(tf.get("seconds") or 0)
                        if seconds <= 0:
                            continue
                        target_time = fs + timedelta(seconds=seconds)
                        if target_time <= now_local:
                            continue
                        existing = await self.analytics_model.get_mc_at_time(
                            token_id, target_time, tolerance_minutes=tolerance_minutes
                        )
                        if existing is None:
                            return target_time
                    return None

                # Ongoing monitoring (Jupiter -> Dex)
                if is_solana:
                    market_cap, ticker = await _fetch_jupiter_mc()

                if market_cap is None:
                    market_cap, ticker, should_stop = await _fetch_dex_mc(stop_on_empty=True)
                    if should_stop:
                        logger.info("[POLL] %s has no DexScreener pools; stopping token", address[:8])
                        await self._stop_token(token_id, address, "dex_no_pools", token.get("first_seen_at"))
                        return

                # Timeframe snapshots handled by dedicated scheduler when enabled
                if not settings.new_scheduler:
                    due_timeframes = await _snapshot_due(token.get("first_seen_at"))
                    if due_timeframes:
                        snapshot_errors = []
                        snapshot_source = None
                        snapshot_mc, snapshot_ticker = await _fetch_dexpaprika_mc()
                        if snapshot_mc is None:
                            dp_err = self.dexpaprika_service.get_last_error(address) or "no_data"
                            snapshot_errors.append(f"dexpaprika:{dp_err}")
                            snapshot_mc, snapshot_ticker = await _fetch_jupiter_mc()
                        if snapshot_mc is None:
                            jup_err = self.jupiter_service.get_last_error(address) or "no_data"
                            snapshot_errors.append(f"jupiter:{jup_err}")
                            snapshot_mc, snapshot_ticker, _ = await _fetch_dex_mc(stop_on_empty=False)
                            if snapshot_mc is None:
                                dx_err = self.dex_client.get_last_error(address) or "no_data"
                                snapshot_errors.append(f"dexscreener:{dx_err}")
                            else:
                                snapshot_source = "dexscreener"
                        else:
                            snapshot_source = "jupiter"
                        if snapshot_mc is not None and snapshot_source is None:
                            snapshot_source = "dexpaprika"
                        if snapshot_mc and snapshot_mc > 0:
                            await self.analytics_model.record_mc_history(token_id, snapshot_mc)
                            for tf in due_timeframes:
                                seconds = int(tf.get("seconds") or 0)
                                if seconds <= 0:
                                    continue
                                target_time = (
                                    token.get("first_seen_at").replace(tzinfo=timezone.utc)
                                    if token.get("first_seen_at") and token.get("first_seen_at").tzinfo is None
                                    else token.get("first_seen_at")
                                )
                                if target_time:
                                    target_time = target_time + timedelta(seconds=seconds)
                                    await self.analytics_model.record_timeframe_attempt(
                                        token_id,
                                        seconds,
                                        target_time,
                                        status="success",
                                        reason="recorded",
                                        source=snapshot_source,
                                        detail=None,
                                    )
                        else:
                            detail = "; ".join(snapshot_errors) if snapshot_errors else "no_data"
                            for tf in due_timeframes:
                                seconds = int(tf.get("seconds") or 0)
                                if seconds <= 0:
                                    continue
                                target_time = (
                                    token.get("first_seen_at").replace(tzinfo=timezone.utc)
                                    if token.get("first_seen_at") and token.get("first_seen_at").tzinfo is None
                                    else token.get("first_seen_at")
                                )
                                if target_time:
                                    target_time = target_time + timedelta(seconds=seconds)
                                    await self.analytics_model.record_timeframe_attempt(
                                        token_id,
                                        seconds,
                                        target_time,
                                        status="failed",
                                        reason="no_snapshot",
                                        source=None,
                                        detail=detail,
                                    )

                if market_cap and market_cap > 0:
                    await self.token_model.update_market_cap(token_id, market_cap, ticker)
                    await self.token_model.update_dex_refresh_time(token_id)

                    peak_mc = token.get("peak_mc") or Decimal(0)
                    if market_cap > peak_mc:
                        await self.token_model.update_peak_mc(token_id, market_cap)
                        await self.token_model.update_peak_reached_at(token_id)

                    # Check for milestone achievements
                    first_seen_mc = token.get("first_seen_mc") or Decimal(0)
                    first_seen_at = token.get("first_seen_at")
                    if first_seen_mc > 0 and first_seen_at:
                        await self._check_and_record_milestones(
                            token_id, market_cap, first_seen_mc, first_seen_at
                        )

                    if not history_only and market_cap and market_cap > 0:
                        baseline_mc = token.get("last_alert_mc") or Decimal(0)
                        first_seen_mc = token.get("first_seen_mc") or Decimal(0)
                        if not baseline_mc or baseline_mc <= 0:
                            baseline_mc = first_seen_mc
                        if baseline_mc and baseline_mc > 0:
                            settings_dict = await self.settings_model.get_gain_alert_settings()
                            gain_threshold_pct = Decimal(str(settings_dict["gain_threshold_pct"]))
                            if should_fire_gain_alert(market_cap, baseline_mc, gain_threshold_pct):
                                alert_mc, alert_ticker = await self.gain_alert_api.fetch_alert_mc(address)
                                if alert_mc is None:
                                    alert_mc = market_cap
                                effective_alert_ticker = alert_ticker or ticker
                                await self._evaluate_gain_alert(
                                    token, alert_mc, address, effective_alert_ticker
                                )

                    if not history_only:
                        should_stop, stop_reason = await self._evaluate_stop_loss(token, market_cap)
                        if should_stop:
                            await self._stop_token(token_id, address, stop_reason or "stop_loss", first_seen_at)
                            return
                else:
                    logger.debug("[POLL] %s missing market cap", address[:8])

                first_seen_at = token.get("first_seen_at")
                if first_seen_at:
                    if history_only and tracking_until and tracking_until <= datetime.now(timezone.utc):
                        return
                    tier_name, next_poll = calculate_next_poll_time(first_seen_at)
                    next_snapshot_at = None
                    if not settings.new_scheduler:
                        next_snapshot_at = await _get_next_snapshot_at(first_seen_at)
                    now_local = datetime.now(timezone.utc)
                    if next_snapshot_at and next_snapshot_at > now_local:
                        self._schedule_snapshot(token_id, address, next_snapshot_at)
                        priority_cutoff = next_snapshot_at - timedelta(seconds=SNAPSHOT_PRIORITY_LEAD_SECONDS)
                        if (next_snapshot_at - now_local).total_seconds() <= SNAPSHOT_PRIORITY_WINDOW_SECONDS:
                            if priority_cutoff <= now_local:
                                priority_cutoff = now_local + timedelta(seconds=1)
                            if next_poll is None or priority_cutoff < next_poll:
                                next_poll = priority_cutoff
                        if next_poll is None or next_snapshot_at < next_poll:
                            next_poll = next_snapshot_at
                    await self.token_model.update_tier(token_id, tier_name, next_poll)

                    self._schedule_poll(token_id, address, next_poll)
                    logger.debug("[POLL] %s rescheduled to %s at %s", address[:8], tier_name, next_poll)
            except Exception as exc:
                logger.error("[POLL] Error polling token %s: %s", address[:8], exc, exc_info=True)
                try:
                    next_poll = datetime.now(timezone.utc) + timedelta(seconds=30)
                    self._schedule_poll(token_id, address, next_poll)
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

    async def _stop_token(
        self,
        token_id: int,
        address: str,
        reason: str,
        first_seen_at: Optional[datetime] = None,
    ) -> None:
        try:
            tracking_until = None
            if first_seen_at:
                max_hold_seconds = await self.analytics_model.get_max_hold_seconds()
                if max_hold_seconds > 0:
                    tracking_until = first_seen_at + timedelta(seconds=max_hold_seconds)
                    if tracking_until <= datetime.now(timezone.utc):
                        tracking_until = None
            await self.token_model.set_status(token_id, "stopped", tracking_until)
            await self.token_model.set_stop_reason(token_id, reason)
            logger.info("[STOP] Token %s stopped: %s", address[:8], reason)
        except Exception as exc:
            logger.error("Error stopping token %s: %s", address[:8], exc, exc_info=True)

    async def _check_and_record_milestones(
        self,
        token_id: int,
        current_mc: Decimal,
        first_seen_mc: Decimal,
        first_seen_at: datetime,
    ) -> None:
        """
        Check if token has hit any new milestones and record them.
        Only records each milestone once (database UNIQUE constraint enforces this).
        """
        try:
            multiplier = float(current_mc / first_seen_mc)

            # Define milestones in descending order for efficiency
            milestones = [
                (100.0, "100x"),
                (10.0, "10x"),
                (5.0, "5x"),
                (2.0, "2x"),
            ]

            now = datetime.now(timezone.utc)
            if first_seen_at.tzinfo is None:
                first_seen_at = first_seen_at.replace(tzinfo=timezone.utc)
            time_to_milestone = int((now - first_seen_at).total_seconds())

            for threshold, milestone_type in milestones:
                if multiplier >= threshold:
                    # Record milestone (will silently skip if already exists due to UNIQUE constraint)
                    await self.analytics_model.record_milestone(
                        token_id=token_id,
                        milestone_type=milestone_type,
                        achieved_at=now,
                        market_cap_at_milestone=current_mc,
                        first_seen_mc=first_seen_mc,
                        multiplier=Decimal(str(multiplier)),
                        time_to_milestone_seconds=time_to_milestone,
                    )

                    logger.debug(
                        "[MILESTONE] Token %s reached %s (current multiplier: %.2fx)",
                        token_id,
                        milestone_type,
                        multiplier,
                    )

        except Exception as exc:
            logger.error(
                "Error checking milestones for token %s: %s",
                token_id,
                exc,
                exc_info=True,
            )

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
                self._schedule_poll(token_id, token["address"], next_poll)
                logger.info("[TIER_B] Token %s promoted to Tier B", token_id)
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

            self._schedule_poll(token_id, address, next_poll)
            logger.info("[SCHEDULER] Added token %s to scheduler", address[:8])
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
