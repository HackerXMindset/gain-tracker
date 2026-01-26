from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

import asyncpg

from models.base import BaseModel

logger = logging.getLogger(__name__)


class AnalyticsModel(BaseModel):
    def __init__(self, db_pool=None) -> None:
        super().__init__(db_pool)

    # Token Milestones
    async def record_milestone(
        self,
        token_id: int,
        milestone_type: str,
        achieved_at: datetime,
        market_cap_at_milestone: Decimal,
        first_seen_mc: Decimal,
        multiplier: Decimal,
        time_to_milestone_seconds: int,
    ) -> None:
        """Record a milestone achievement (idempotent via ON CONFLICT DO NOTHING)."""
        await self.db.execute(
            """
            INSERT INTO token_milestones
            (token_id, milestone_type, achieved_at, market_cap_at_milestone,
             first_seen_mc, multiplier, time_to_milestone_seconds)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (token_id, milestone_type) DO NOTHING
            """,
            token_id,
            milestone_type,
            achieved_at,
            market_cap_at_milestone,
            first_seen_mc,
            multiplier,
            time_to_milestone_seconds,
        )

    async def get_token_milestones(self, token_id: int) -> List[asyncpg.Record]:
        """Get all milestones for a specific token."""
        return await self.db.fetch(
            """
            SELECT * FROM token_milestones
            WHERE token_id = $1
            ORDER BY achieved_at ASC
            """,
            token_id,
        )

    async def get_recent_milestones(
        self,
        limit: int = 100,
        milestone_type: Optional[str] = None,
    ) -> List[asyncpg.Record]:
        """Get recent milestone achievements across all tokens."""
        if milestone_type:
            return await self.db.fetch(
                """
                SELECT tm.*, tt.address, tt.ticker
                FROM token_milestones tm
                JOIN tokens_tracked tt ON tm.token_id = tt.id
                WHERE tm.milestone_type = $1
                ORDER BY tm.achieved_at DESC
                LIMIT $2
                """,
                milestone_type,
                limit,
            )
        else:
            return await self.db.fetch(
                """
                SELECT tm.*, tt.address, tt.ticker
                FROM token_milestones tm
                JOIN tokens_tracked tt ON tm.token_id = tt.id
                ORDER BY tm.achieved_at DESC
                LIMIT $1
                """,
                limit,
            )

    async def get_milestone_stats(self) -> Optional[asyncpg.Record]:
        """Get aggregate statistics on milestone achievements."""
        return await self.db.fetchrow(
            """
            SELECT
                COUNT(DISTINCT token_id) as tokens_with_milestones,
                COUNT(*) FILTER (WHERE milestone_type = '2x') as total_2x,
                COUNT(*) FILTER (WHERE milestone_type = '5x') as total_5x,
                COUNT(*) FILTER (WHERE milestone_type = '10x') as total_10x,
                COUNT(*) FILTER (WHERE milestone_type = '100x') as total_100x,
                AVG(time_to_milestone_seconds) FILTER (WHERE milestone_type = '2x') as avg_time_to_2x,
                AVG(time_to_milestone_seconds) FILTER (WHERE milestone_type = '5x') as avg_time_to_5x,
                AVG(time_to_milestone_seconds) FILTER (WHERE milestone_type = '10x') as avg_time_to_10x
            FROM token_milestones
            """
        )

    # Source Stats (Phase 2)
    async def calculate_source_stats(
        self,
        source_chat_id: int,
        user_id: Optional[int],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Calculate performance stats for a source over a time period."""
        # Get all tokens from this source in the time period
        # Note: We're using token_group_alerts to track which tokens came from which source
        query = """
            WITH source_tokens AS (
                SELECT DISTINCT tt.id, tt.address, tt.first_seen_mc, tt.peak_mc,
                       tt.last_mc, tt.first_seen_at, tt.peak_reached_at
                FROM tokens_tracked tt
                JOIN token_group_alerts tga ON tt.id = tga.token_id
                WHERE tga.chat_id = $1
                  AND tga.created_at BETWEEN $2 AND $3
                  AND ($4::BIGINT IS NULL OR tga.original_user_id = $4)
            )
            SELECT
                COUNT(*) as total_calls,
                COUNT(DISTINCT tm_2x.token_id) as hits_2x,
                COUNT(DISTINCT tm_5x.token_id) as hits_5x,
                COUNT(DISTINCT tm_10x.token_id) as hits_10x,
                COUNT(DISTINCT tm_100x.token_id) as hits_100x,
                AVG(st.peak_mc / NULLIF(st.first_seen_mc, 0)) as avg_peak_multiplier,
                AVG(EXTRACT(EPOCH FROM (st.peak_reached_at - st.first_seen_at))) as avg_time_to_peak_seconds,
                MAX(st.peak_mc / NULLIF(st.first_seen_mc, 0)) as best_multiplier,
                MIN(CASE WHEN st.last_mc > 0 THEN st.last_mc / NULLIF(st.first_seen_mc, 0) END) as worst_multiplier
            FROM source_tokens st
            LEFT JOIN token_milestones tm_2x ON st.id = tm_2x.token_id AND tm_2x.milestone_type = '2x'
            LEFT JOIN token_milestones tm_5x ON st.id = tm_5x.token_id AND tm_5x.milestone_type = '5x'
            LEFT JOIN token_milestones tm_10x ON st.id = tm_10x.token_id AND tm_10x.milestone_type = '10x'
            LEFT JOIN token_milestones tm_100x ON st.id = tm_100x.token_id AND tm_100x.milestone_type = '100x'
            WHERE st.first_seen_mc > 0
        """

        result = await self.db.fetchrow(query, source_chat_id, start_time, end_time, user_id)

        if not result or result["total_calls"] == 0:
            return {
                "total_calls": 0,
                "hits_2x": 0,
                "hits_5x": 0,
                "hits_10x": 0,
                "hits_100x": 0,
                "win_rate_2x": 0.0,
                "win_rate_5x": 0.0,
                "win_rate_10x": 0.0,
                "win_rate_100x": 0.0,
                "avg_peak_multiplier": 0.0,
                "avg_time_to_peak_seconds": 0,
                "best_multiplier": 0.0,
                "worst_multiplier": 0.0,
            }

        total_calls = result["total_calls"] or 0

        return {
            "total_calls": total_calls,
            "hits_2x": result["hits_2x"] or 0,
            "hits_5x": result["hits_5x"] or 0,
            "hits_10x": result["hits_10x"] or 0,
            "hits_100x": result["hits_100x"] or 0,
            "win_rate_2x": (result["hits_2x"] or 0) / total_calls * 100 if total_calls > 0 else 0.0,
            "win_rate_5x": (result["hits_5x"] or 0) / total_calls * 100 if total_calls > 0 else 0.0,
            "win_rate_10x": (result["hits_10x"] or 0) / total_calls * 100 if total_calls > 0 else 0.0,
            "win_rate_100x": (result["hits_100x"] or 0) / total_calls * 100 if total_calls > 0 else 0.0,
            "avg_peak_multiplier": float(result["avg_peak_multiplier"] or 0),
            "avg_time_to_peak_seconds": int(result["avg_time_to_peak_seconds"] or 0),
            "best_multiplier": float(result["best_multiplier"] or 0),
            "worst_multiplier": float(result["worst_multiplier"] or 0),
        }

    async def get_cached_stats(
        self,
        source_id: int,
        period: str = "24h",
    ) -> Optional[asyncpg.Record]:
        """Get cached stats for a monitored source."""
        return await self.db.fetchrow(
            """
            SELECT * FROM source_stats
            WHERE source_id = $1 AND stat_period = $2
            """,
            source_id,
            period,
        )

    async def refresh_stats_cache(
        self,
        source_id: int,
        source_chat_id: int,
        period: str = "24h",
    ) -> None:
        """Calculate and cache stats for a source."""
        from datetime import timedelta

        # Parse period to timedelta
        period_map = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
            "all_time": timedelta(days=365 * 10),  # 10 years
        }

        duration = period_map.get(period, timedelta(hours=24))
        end_time = datetime.now(timezone.utc)
        start_time = end_time - duration

        # Calculate stats
        stats = await self.calculate_source_stats(source_chat_id, None, start_time, end_time)

        # Upsert into cache
        await self.db.execute(
            """
            INSERT INTO source_stats
            (source_id, stat_period, period_start, period_end, total_calls,
             tokens_hit_2x, tokens_hit_5x, tokens_hit_10x, tokens_hit_100x,
             avg_peak_multiplier, avg_time_to_peak_seconds, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
            ON CONFLICT (source_id, stat_period)
            DO UPDATE SET
                period_start = $3,
                period_end = $4,
                total_calls = $5,
                tokens_hit_2x = $6,
                tokens_hit_5x = $7,
                tokens_hit_10x = $8,
                tokens_hit_100x = $9,
                avg_peak_multiplier = $10,
                avg_time_to_peak_seconds = $11,
                updated_at = NOW()
            """,
            source_id,
            period,
            start_time,
            end_time,
            stats["total_calls"],
            stats["hits_2x"],
            stats["hits_5x"],
            stats["hits_10x"],
            stats["hits_100x"],
            stats["avg_peak_multiplier"],
            stats["avg_time_to_peak_seconds"],
        )

        logger.info(
            "[STATS] Refreshed %s stats for source %s: %d calls, %.1f%% hit 2x",
            period,
            source_id,
            stats["total_calls"],
            stats["win_rate_2x"],
        )

    async def get_top_sources(
        self,
        period: str = "7d",
        limit: int = 10,
    ) -> List[asyncpg.Record]:
        """Get leaderboard of top performing sources."""
        return await self.db.fetch(
            """
            SELECT
                ss.*,
                ms.display_name,
                ms.chat_id,
                CASE
                    WHEN ss.total_calls > 0
                    THEN CAST(ss.tokens_hit_2x AS FLOAT) / ss.total_calls * 100
                    ELSE 0
                END as win_rate_2x
            FROM source_stats ss
            JOIN monitored_sources ms ON ss.source_id = ms.id
            WHERE ss.stat_period = $1
              AND ss.total_calls > 0
            ORDER BY win_rate_2x DESC, ss.total_calls DESC
            LIMIT $2
            """,
            period,
            limit,
        )

    # Hourly Patterns (Phase 5)
    async def analyze_time_patterns(
        self,
        chat_id: Optional[int],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """
        Analyze hourly and daily performance patterns.
        If chat_id is None, analyzes global patterns across all sources.
        """
        # Query for hourly patterns
        hourly_query = """
            SELECT
                EXTRACT(HOUR FROM tga.created_at AT TIME ZONE 'UTC') as hour_utc,
                COUNT(*) as total_calls,
                COUNT(DISTINCT tm_2x.token_id) as hits_2x,
                COUNT(DISTINCT tm_5x.token_id) as hits_5x,
                AVG(tt.peak_mc / NULLIF(tt.first_seen_mc, 0)) as avg_multiplier
            FROM token_group_alerts tga
            JOIN tokens_tracked tt ON tga.token_id = tt.id
            LEFT JOIN token_milestones tm_2x ON tt.id = tm_2x.token_id AND tm_2x.milestone_type = '2x'
            LEFT JOIN token_milestones tm_5x ON tt.id = tm_5x.token_id AND tm_5x.milestone_type = '5x'
            WHERE tt.first_seen_mc > 0
              AND tga.created_at BETWEEN $2 AND $3
              AND ($1::BIGINT IS NULL OR tga.chat_id = $1)
            GROUP BY hour_utc
            ORDER BY hour_utc
        """

        hourly_results = await self.db.fetch(hourly_query, chat_id, start_time, end_time)

        # Query for daily patterns (ISODOW: 1=Monday, 7=Sunday)
        daily_query = """
            SELECT
                EXTRACT(ISODOW FROM tga.created_at AT TIME ZONE 'UTC') as day_of_week,
                COUNT(*) as total_calls,
                COUNT(DISTINCT tm_2x.token_id) as hits_2x,
                COUNT(DISTINCT tm_5x.token_id) as hits_5x,
                AVG(tt.peak_mc / NULLIF(tt.first_seen_mc, 0)) as avg_multiplier
            FROM token_group_alerts tga
            JOIN tokens_tracked tt ON tga.token_id = tt.id
            LEFT JOIN token_milestones tm_2x ON tt.id = tm_2x.token_id AND tm_2x.milestone_type = '2x'
            LEFT JOIN token_milestones tm_5x ON tt.id = tm_5x.token_id AND tm_5x.milestone_type = '5x'
            WHERE tt.first_seen_mc > 0
              AND tga.created_at BETWEEN $2 AND $3
              AND ($1::BIGINT IS NULL OR tga.chat_id = $1)
            GROUP BY day_of_week
            ORDER BY day_of_week
        """

        daily_results = await self.db.fetch(daily_query, chat_id, start_time, end_time)

        daily_hourly_query = """
            SELECT
                EXTRACT(ISODOW FROM tga.created_at AT TIME ZONE 'UTC') as day_of_week,
                EXTRACT(HOUR FROM tga.created_at AT TIME ZONE 'UTC') as hour_utc,
                COUNT(*) as total_calls,
                COUNT(DISTINCT tm_2x.token_id) as hits_2x,
                COUNT(DISTINCT tm_5x.token_id) as hits_5x
            FROM token_group_alerts tga
            JOIN tokens_tracked tt ON tga.token_id = tt.id
            LEFT JOIN token_milestones tm_2x ON tt.id = tm_2x.token_id AND tm_2x.milestone_type = '2x'
            LEFT JOIN token_milestones tm_5x ON tt.id = tm_5x.token_id AND tm_5x.milestone_type = '5x'
            WHERE tt.first_seen_mc > 0
              AND tga.created_at BETWEEN $2 AND $3
              AND ($1::BIGINT IS NULL OR tga.chat_id = $1)
            GROUP BY day_of_week, hour_utc
            ORDER BY day_of_week, hour_utc
        """
        daily_hourly_results = await self.db.fetch(daily_hourly_query, chat_id, start_time, end_time)

        # Process hourly patterns
        hourly = []
        best_hour_utc = 0
        best_hour_win_rate = 0.0
        best_hour_win_rate_5x = 0.0

        for row in hourly_results:
            hour_utc = int(row["hour_utc"])
            total_calls = row["total_calls"] or 0
            hits_2x = row["hits_2x"] or 0
            hits_5x = row["hits_5x"] or 0
            win_rate_2x = (hits_2x / total_calls * 100) if total_calls > 0 else 0.0
            win_rate_5x = (hits_5x / total_calls * 100) if total_calls > 0 else 0.0

            # IST is UTC+5:30
            hour_ist = (hour_utc + 5.5) % 24

            hourly.append({
                "hour_utc": hour_utc,
                "hour_ist": hour_ist,
                "calls": total_calls,
                "win_rate_2x": win_rate_2x,
                "win_rate_5x": win_rate_5x,
                "hits_2x": hits_2x,
                "hits_5x": hits_5x,
                "avg_multiplier": float(row["avg_multiplier"] or 0),
            })

            if win_rate_2x > best_hour_win_rate:
                best_hour_win_rate = win_rate_2x
                best_hour_win_rate_5x = win_rate_5x
                best_hour_utc = hour_utc

        # Process daily patterns (ISODOW: 1=Monday, 7=Sunday)
        daily = []
        day_names = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        best_day = 1
        best_day_win_rate = 0.0
        best_day_win_rate_5x = 0.0

        best_hour_by_day: Dict[int, Dict[str, Any]] = {}
        for row in daily_hourly_results:
            day_of_week = int(row["day_of_week"])
            hour_utc = int(row["hour_utc"])
            total_calls = row["total_calls"] or 0
            hits_2x = row["hits_2x"] or 0
            hits_5x = row["hits_5x"] or 0
            win_rate_2x = (hits_2x / total_calls * 100) if total_calls > 0 else 0.0
            win_rate_5x = (hits_5x / total_calls * 100) if total_calls > 0 else 0.0

            current = best_hour_by_day.get(day_of_week)
            candidate = (win_rate_2x, total_calls)
            if current is None or candidate > (current["win_rate_2x"], current["calls"]):
                best_hour_by_day[day_of_week] = {
                    "hour_utc": hour_utc,
                    "win_rate_2x": win_rate_2x,
                    "win_rate_5x": win_rate_5x,
                    "calls": total_calls,
                }

        for row in daily_results:
            day_of_week = int(row["day_of_week"])  # 1-7
            total_calls = row["total_calls"] or 0
            hits_2x = row["hits_2x"] or 0
            hits_5x = row["hits_5x"] or 0
            win_rate_2x = (hits_2x / total_calls * 100) if total_calls > 0 else 0.0
            win_rate_5x = (hits_5x / total_calls * 100) if total_calls > 0 else 0.0

            daily.append({
                "day": day_of_week,  # 1=Mon, 7=Sun
                "day_name": day_names[day_of_week],
                "day_of_week": day_of_week,
                "calls": total_calls,
                "win_rate_2x": win_rate_2x,
                "win_rate_5x": win_rate_5x,
                "hits_2x": hits_2x,
                "avg_multiplier": float(row["avg_multiplier"] or 0),
                "best_hour": best_hour_by_day.get(day_of_week),
            })

            if win_rate_2x > best_day_win_rate:
                best_day_win_rate = win_rate_2x
                best_day_win_rate_5x = win_rate_5x
                best_day = day_of_week

        # Calculate total calls for the period
        hourly_total_calls = sum(h["calls"] for h in hourly)
        hourly_by_hour = {h["hour_utc"]: h for h in hourly}

        best_session = None
        session_windows = [2, 3, 4, 6]
        for window_hours in session_windows:
            for start_hour in range(24):
                total_calls = 0
                hits_2x = 0
                hits_5x = 0
                for offset in range(window_hours):
                    hour = (start_hour + offset) % 24
                    data = hourly_by_hour.get(hour)
                    if not data:
                        continue
                    total_calls += data.get("calls", 0)
                    hits_2x += data.get("hits_2x", 0)
                    hits_5x += data.get("hits_5x", 0)
                win_rate_2x = (hits_2x / total_calls * 100) if total_calls > 0 else 0.0
                win_rate_5x = (hits_5x / total_calls * 100) if total_calls > 0 else 0.0
                candidate = (win_rate_2x, total_calls, -window_hours)
                if best_session is None or candidate > (
                    best_session["win_rate_2x"],
                    best_session["calls"],
                    -best_session["window_hours"],
                ):
                    best_session = {
                        "start_hour_utc": start_hour,
                        "window_hours": window_hours,
                        "calls": total_calls,
                        "win_rate_2x": win_rate_2x,
                        "win_rate_5x": win_rate_5x,
                    }

        return {
            "hourly": hourly,
            "daily": daily,
            "hourly_total_calls": hourly_total_calls,
            "best_hour_utc": best_hour_utc,
            "best_hour_ist": (best_hour_utc + 5.5) % 24,
            "best_hour_win_rate": best_hour_win_rate,
            "best_hour_win_rate_5x": best_hour_win_rate_5x,
            "best_day": best_day,  # 1-7 (ISODOW)
            "best_day_win_rate": best_day_win_rate,
            "best_day_win_rate_5x": best_day_win_rate_5x,
            "best_session": best_session,
        }

    async def get_hourly_pattern(
        self,
        hour: int,
        day_of_week: int,
    ) -> Optional[asyncpg.Record]:
        """Get performance stats for specific hour/day combination."""
        return await self.db.fetchrow(
            """
            SELECT * FROM hourly_patterns
            WHERE hour_of_day = $1 AND day_of_week = $2
            """,
            hour,
            day_of_week,
        )

    # MC History (Phase 1.5)
    async def record_mc_history(self, token_id: int, market_cap: Decimal) -> None:
        """Record a market cap snapshot for historical analysis."""
        await self.db.execute(
            """
            INSERT INTO token_mc_history (token_id, market_cap)
            VALUES ($1, $2)
            """,
            token_id,
            market_cap,
        )

    async def get_mc_at_time(
        self,
        token_id: int,
        target_time: datetime,
        tolerance_minutes: int = 5,
    ) -> Optional[Decimal]:
        """Get MC closest to target time (within tolerance)."""
        if not isinstance(target_time, datetime):
            logger.error("Invalid target_time for MC lookup: %r", target_time)
            return None
        record = await self.db.fetchrow(
            """
            SELECT market_cap
            FROM token_mc_history
            WHERE token_id = $1
              AND recorded_at BETWEEN $2::timestamptz - ($3::int * INTERVAL '1 minute')
                                  AND $2::timestamptz + ($3::int * INTERVAL '1 minute')
            ORDER BY ABS(EXTRACT(EPOCH FROM (recorded_at - $2))) ASC
            LIMIT 1
            """,
            token_id,
            target_time,
            tolerance_minutes,
        )
        return Decimal(str(record["market_cap"])) if record else None

    async def get_mc_after_duration(
        self,
        token_id: int,
        first_seen_at: datetime,
        duration_seconds: int,
    ) -> Optional[Decimal]:
        """Get MC at specific duration after first_seen."""
        from datetime import timedelta

        target_time = first_seen_at + timedelta(seconds=duration_seconds)
        return await self.get_mc_at_time(token_id, target_time)

    async def get_hold_timeframes(
        self,
        defaults_only: bool = False,
    ) -> List[asyncpg.Record]:
        """Get all configured hold timeframes."""
        if defaults_only:
            return await self.db.fetch(
                """
                SELECT * FROM hold_timeframes
                WHERE is_default = true
                ORDER BY display_order
                """
            )
        return await self.db.fetch(
            "SELECT * FROM hold_timeframes ORDER BY display_order"
        )

    async def analyze_best_hold(
        self,
        chat_id: Optional[int],
        user_id: Optional[int],
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Analyze win rates for 2x/5x milestones across hold durations."""
        total_tokens = await self.db.fetchval(
            """
            SELECT COUNT(DISTINCT tga.token_id)
            FROM token_group_alerts tga
            WHERE tga.created_at BETWEEN $1 AND $2
              AND ($3::BIGINT IS NULL OR tga.chat_id = $3)
              AND ($4::BIGINT IS NULL OR tga.original_user_id = $4)
            """,
            start_time,
            end_time,
            chat_id,
            user_id,
        )

        if not total_tokens:
            return {
                "total_tokens": 0,
                "rows": [],
            }

        rows = await self.db.fetch(
            """
            WITH source_tokens AS (
                SELECT DISTINCT tga.token_id
                FROM token_group_alerts tga
                WHERE tga.created_at BETWEEN $1 AND $2
                  AND ($3::BIGINT IS NULL OR tga.chat_id = $3)
                  AND ($4::BIGINT IS NULL OR tga.original_user_id = $4)
            ),
            milestones AS (
                SELECT tm.token_id, tm.milestone_type, tm.time_to_milestone_seconds
                FROM token_milestones tm
                JOIN source_tokens st ON st.token_id = tm.token_id
                WHERE tm.milestone_type IN ('2x', '5x')
            )
            SELECT
                ht.label,
                ht.seconds,
                COUNT(DISTINCT CASE
                    WHEN m.milestone_type = '2x'
                     AND m.time_to_milestone_seconds <= ht.seconds
                    THEN m.token_id
                END) AS hits_2x,
                COUNT(DISTINCT CASE
                    WHEN m.milestone_type = '5x'
                     AND m.time_to_milestone_seconds <= ht.seconds
                    THEN m.token_id
                END) AS hits_5x
            FROM hold_timeframes ht
            LEFT JOIN milestones m
                ON m.time_to_milestone_seconds <= ht.seconds
            GROUP BY ht.label, ht.seconds
            ORDER BY ht.seconds
            """,
            start_time,
            end_time,
            chat_id,
            user_id,
        )

        median_time_to_2x_seconds = await self.db.fetchval(
            """
            WITH source_tokens AS (
                SELECT DISTINCT tga.token_id
                FROM token_group_alerts tga
                WHERE tga.created_at BETWEEN $1 AND $2
                  AND ($3::BIGINT IS NULL OR tga.chat_id = $3)
                  AND ($4::BIGINT IS NULL OR tga.original_user_id = $4)
            )
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY tm.time_to_milestone_seconds)
            FROM token_milestones tm
            JOIN source_tokens st ON st.token_id = tm.token_id
            WHERE tm.milestone_type = '2x'
            """,
            start_time,
            end_time,
            chat_id,
            user_id,
        )

        return {
            "total_tokens": int(total_tokens),
            "rows": rows,
            "median_time_to_2x_seconds": int(median_time_to_2x_seconds)
            if median_time_to_2x_seconds is not None
            else None,
        }

    async def add_hold_timeframe(
        self,
        label: str,
        seconds: int,
        is_default: bool = False,
    ) -> Optional[asyncpg.Record]:
        """Add a new hold timeframe."""
        # Calculate display_order based on seconds
        display_order = seconds // 60  # Simple ordering by duration
        try:
            return await self.db.fetchrow(
                """
                INSERT INTO hold_timeframes (label, seconds, display_order, is_default)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                label,
                seconds,
                display_order,
                is_default,
            )
        except Exception as exc:
            logger.error("Error adding hold timeframe %s: %s", label, exc)
            return None

    async def delete_hold_timeframe(self, label: str) -> bool:
        """Delete a hold timeframe by label."""
        result = await self.db.execute(
            "DELETE FROM hold_timeframes WHERE label = $1",
            label,
        )
        return result != "DELETE 0"

    async def cleanup_old_mc_history(self, days_to_keep: int = 30) -> int:
        """Delete MC history older than specified days. Returns count deleted."""
        result = await self.db.execute(
            """
            DELETE FROM token_mc_history
            WHERE recorded_at < NOW() - ($1 || ' days')::INTERVAL
            """,
            days_to_keep,
        )
        # Parse "DELETE N" to get count
        count = int(result.split()[-1]) if result.startswith("DELETE") else 0
        return count

    # Investment Simulator (Phase 6)
    async def simulate_investment(
        self,
        amount: float,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        user_ids: Optional[List[int]] = None,
        token_count: Optional[int] = None,
        timeframe_hours: Optional[int] = 24,
        hold_strategy: str = "peak",
        allocation: str = "equal",
    ) -> dict:
        """
        Simulate investment P&L across tokens.

        Args:
            amount: Investment amount in USD
            chat_id: Source chat (None = all sources)
            token_count: Number of recent tokens (None = use timeframe)
            timeframe_hours: Timeframe in hours (used if token_count is None)
            hold_strategy: "peak", "current", or duration like "1h", "6h", "24h"
            allocation: "equal" or "weighted"

        Returns:
            Dict with simulation results including top performers and summary
        """
        from datetime import timedelta

        # Get tokens for simulation
        if user_ids is not None and len(user_ids) == 0:
            user_ids = None
        if user_ids is None and user_id is not None:
            user_ids = [user_id]

        tokens = await self._get_tokens_for_simulation(
            chat_id, user_ids, token_count, timeframe_hours
        )

        token_ids = [token["id"] for token in tokens] if tokens else []
        latest_mc_history = {}
        if token_ids:
            rows = await self.db.fetch(
                """
                SELECT DISTINCT ON (token_id)
                       token_id,
                       recorded_at,
                       market_cap
                FROM token_mc_history
                WHERE token_id = ANY($1)
                ORDER BY token_id, recorded_at DESC
                """,
                token_ids,
            )
            latest_mc_history = {
                row["token_id"]: {
                    "recorded_at": row["recorded_at"],
                    "market_cap": row["market_cap"],
                }
                for row in rows
            }

        if not tokens:
            return {
                "error": "No tokens found for simulation",
                "total_tokens": 0,
            }

        liquidity_pct_assumption = 0.10  # Liquidity assumed as 10% of exit MC
        sol_price_usd = 200.0
        base_gas_sol = 0.002
        gas_tip_sol = 0.0015
        trojan_fee_pct = 0.01
        gas_per_tx_usd = (base_gas_sol + gas_tip_sol) * sol_price_usd
        gas_per_token_usd = gas_per_tx_usd * 2

        # Calculate allocation per token
        results = []
        fallback_seconds = []
        total_trojan_buy = 0.0
        total_trojan_sell = 0.0
        excluded_due_to_age = 0
        for token in tokens:
            per_token_amount = amount  # Amount per token

            if hold_strategy not in ("peak", "current"):
                duration_seconds = self._parse_duration(hold_strategy)
                first_seen_at = token.get("first_seen_at")
                if duration_seconds and first_seen_at:
                    age_seconds = int((datetime.now(timezone.utc) - first_seen_at).total_seconds())
                    if age_seconds < duration_seconds:
                        excluded_due_to_age += 1
                        continue

            entry_mc = Decimal(str(token["first_seen_mc"] or 0))
            if entry_mc <= 0:
                continue

            # Determine exit MC based on hold strategy
            exit_mc, fallback_reason = await self._get_exit_mc(token, hold_strategy)
            if exit_mc is None or exit_mc <= 0:
                exit_mc = Decimal(str(token["last_mc"] or 0))
                fallback_reason = "missing_hold_data"

            if fallback_reason == "missing_hold_data":
                history = latest_mc_history.get(token["id"])
                if history and history.get("market_cap"):
                    exit_mc = Decimal(str(history["market_cap"]))
                    recorded_at = history.get("recorded_at")
                    first_seen_at = token.get("first_seen_at")
                    if recorded_at and first_seen_at:
                        try:
                            fallback_seconds.append(
                                int((recorded_at - first_seen_at).total_seconds())
                            )
                        except Exception:
                            pass

            if exit_mc <= 0:
                continue

            multiplier = float(exit_mc / entry_mc)
            gross_final_value = per_token_amount * multiplier

            liquidity_usd = float(exit_mc) * liquidity_pct_assumption
            if liquidity_usd > 0:
                slippage_pct = min(gross_final_value / liquidity_usd, 1.0)
            else:
                slippage_pct = 0.0

            exit_value = gross_final_value * (1 - slippage_pct)

            trojan_fee_buy = per_token_amount * trojan_fee_pct
            trojan_fee_sell = exit_value * trojan_fee_pct
            total_trojan_buy += trojan_fee_buy
            total_trojan_sell += trojan_fee_sell

            final_value = exit_value - trojan_fee_sell - gas_per_token_usd
            pnl = final_value - per_token_amount - trojan_fee_buy
            pnl_pct = (pnl / per_token_amount * 100) if per_token_amount > 0 else -100

            results.append({
                "token_id": token["id"],
                "address": token["address"],
                "ticker": token.get("ticker") or token["address"][:8],
                "entry_mc": float(entry_mc),
                "exit_mc": float(exit_mc),
                "multiplier": multiplier,
                "invested": per_token_amount,
                "final_value": final_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "liquidity_usd": liquidity_usd,
                "slippage_pct": slippage_pct * 100,
                "gas_cost_usd": gas_per_token_usd,
                "trojan_fee_buy_usd": trojan_fee_buy,
                "trojan_fee_sell_usd": trojan_fee_sell,
                "fallback_reason": fallback_reason,
            })

        # Sort by P&L
        results.sort(key=lambda x: x["pnl"], reverse=True)

        # Calculate summary stats
        win_threshold_pct = 70.0
        total_invested = amount * len(results)
        total_final_value = sum(r["final_value"] for r in results)
        total_gas_usd = gas_per_token_usd * len(results)
        total_fees_usd = total_gas_usd + total_trojan_buy + total_trojan_sell
        total_pnl = total_final_value - total_invested - total_trojan_buy
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        winners = [r for r in results if r["pnl_pct"] >= win_threshold_pct]
        losers = [r for r in results if r["pnl_pct"] < win_threshold_pct]

        negative_results = [r for r in results if r["pnl"] < 0]
        worst_results = sorted(negative_results, key=lambda x: x["pnl"])[:3]

        fallback_count = sum(1 for r in results if r.get("fallback_reason"))
        fallback_hold_avg_seconds = (
            int(sum(fallback_seconds) / len(fallback_seconds)) if fallback_seconds else None
        )
        fallback_hold_min_seconds = min(fallback_seconds) if fallback_seconds else None
        fallback_hold_max_seconds = max(fallback_seconds) if fallback_seconds else None

        avg_pnl_pct = (
            sum(r["pnl_pct"] for r in results) / len(results)
            if results
            else 0.0
        )

        positive_results = [r for r in results if r["pnl"] > 0]
        total_positive_profit = sum(r["pnl"] for r in positive_results)
        top_positive = sorted(positive_results, key=lambda x: x["pnl"], reverse=True)[:3]
        top3_positive_profit = sum(r["pnl"] for r in top_positive)
        top3_profit_share_pct = (
            (top3_positive_profit / total_positive_profit) * 100
            if total_positive_profit > 0
            else 0.0
        )

        return {
            "settings": {
                "amount": amount,
                "chat_id": chat_id,
                "user_id": user_id,
                "user_ids": user_ids,
                "token_count": token_count,
                "timeframe_hours": timeframe_hours,
                "hold_strategy": hold_strategy,
                "allocation": allocation,
                "win_threshold_pct": win_threshold_pct,
                "slippage_model": "liquidity_ratio",
                "liquidity_pct_of_mc": liquidity_pct_assumption * 100,
                "base_gas_sol": base_gas_sol,
                "gas_tip_sol": gas_tip_sol,
                "sol_price_usd": sol_price_usd,
                "trojan_fee_pct": trojan_fee_pct * 100,
            },
            "results": results[:15],  # Top 15
            "worst_results": worst_results,
            "total_tokens": len(results),
            "total_invested": total_invested,
            "total_final_value": total_final_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "total_gas_usd": total_gas_usd,
            "total_trojan_fees_usd": total_trojan_buy + total_trojan_sell,
            "total_fees_usd": total_fees_usd,
            "winners_count": len(winners),
            "losers_count": len(losers),
            "top_performer": results[0] if results else None,
            "worst_performer": results[-1] if results else None,
            "avg_pnl_pct": avg_pnl_pct,
            "total_positive_profit": total_positive_profit,
            "top3_positive_profit": top3_positive_profit,
            "top3_profit_share_pct": top3_profit_share_pct,
            "fallback_count": fallback_count,
            "fallback_hold_avg_seconds": fallback_hold_avg_seconds,
            "fallback_hold_min_seconds": fallback_hold_min_seconds,
            "fallback_hold_max_seconds": fallback_hold_max_seconds,
            "excluded_due_to_age": excluded_due_to_age,
        }

    async def _get_tokens_for_simulation(
        self,
        chat_id: Optional[int],
        user_ids: Optional[List[int]],
        token_count: Optional[int],
        timeframe_hours: Optional[int],
    ) -> List[asyncpg.Record]:
        """Get tokens for investment simulation based on filters."""
        from datetime import timedelta

        if token_count:
            # Get N most recent tokens
            if chat_id:
                return await self.db.fetch(
                    """
                    SELECT DISTINCT ON (tt.id) tt.*
                    FROM tokens_tracked tt
                    JOIN token_group_alerts tga ON tga.token_id = tt.id
                    WHERE tga.chat_id = $1
                      AND ($2::BIGINT[] IS NULL OR tga.original_user_id = ANY($2))
                      AND tt.first_seen_mc > 0
                      AND tt.peak_mc > 0
                    ORDER BY tt.id DESC, tt.first_seen_at DESC
                    LIMIT $3
                    """,
                    chat_id,
                    user_ids,
                    token_count,
                )
            else:
                return await self.db.fetch(
                    """
                    SELECT * FROM tokens_tracked
                    WHERE first_seen_mc > 0
                      AND peak_mc > 0
                    ORDER BY first_seen_at DESC
                    LIMIT $1
                    """,
                    token_count,
                )
        else:
            # Get tokens from timeframe
            start_time = datetime.now(timezone.utc) - timedelta(hours=timeframe_hours or 24)
            if chat_id:
                return await self.db.fetch(
                    """
                    SELECT DISTINCT ON (tt.id) tt.*
                    FROM tokens_tracked tt
                    JOIN token_group_alerts tga ON tga.token_id = tt.id
                    WHERE tga.chat_id = $1
                      AND tt.first_seen_at >= $2
                      AND ($3::BIGINT[] IS NULL OR tga.original_user_id = ANY($3))
                      AND tt.first_seen_mc > 0
                      AND tt.peak_mc > 0
                    ORDER BY tt.id DESC, tt.first_seen_at DESC
                    """,
                    chat_id,
                    start_time,
                    user_ids,
                )
            else:
                return await self.db.fetch(
                    """
                    SELECT * FROM tokens_tracked
                    WHERE first_seen_at >= $1
                      AND first_seen_mc > 0
                      AND peak_mc > 0
                    ORDER BY first_seen_at DESC
                    """,
                    start_time,
                )

    async def _get_exit_mc(
        self,
        token: asyncpg.Record,
        hold_strategy: str,
    ) -> Tuple[Optional[Decimal], Optional[str]]:
        """Determine exit MC based on hold strategy."""
        if hold_strategy == "peak":
            return (Decimal(str(token["peak_mc"])), None)
        elif hold_strategy == "current":
            return (Decimal(str(token["last_mc"])), None)
        else:
            # Parse duration like "1h", "6h", "24h"
            try:
                duration_seconds = self._parse_duration(hold_strategy)
                if duration_seconds:
                    exit_mc = await self.get_mc_after_duration(
                        token["id"],
                        token["first_seen_at"],
                        duration_seconds,
                    )
                    if exit_mc:
                        return (exit_mc, None)
            except Exception as exc:
                logger.error("Error parsing hold strategy %s: %s", hold_strategy, exc)

            # Fallback to last known MC when hold data is missing
            return (Decimal(str(token["last_mc"])), "missing_hold_data")

    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """Parse duration string like '1h', '6h', '24h' to seconds."""
        import re

        match = re.match(r"^(\d+)([smhdw])$", duration_str.lower())
        if not match:
            return None

        value, unit = match.groups()
        value = int(value)

        multipliers = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }

        return value * multipliers.get(unit, 0)
