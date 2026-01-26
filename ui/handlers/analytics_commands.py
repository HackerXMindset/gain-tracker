"""
Analytics Commands Handler - /stats and /top commands.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from models import AnalyticsModel, MonitoredSourceModel
from utils import format_duration

logger = logging.getLogger(__name__)


class AnalyticsCommandsHandler:
    """Handler for analytics slash commands."""

    def __init__(self, db_pool):
        self.db = db_pool
        self.analytics_model = AnalyticsModel(db_pool)
        self.source_model = MonitoredSourceModel(db_pool)

    async def cmd_stats(self, message: types.Message) -> None:
        """
        Show stats for a monitored source.

        Usage:
            /stats {chat_id} {timeframe}
            /stats {chat_id} {timeframe} user:{user_id}
            /stats {chat_id}:{user_id} {timeframe}

        Examples:
            /stats -1001234567890 24h
            /stats -1009876543210 7d user:123456789
            /stats -1009876543210:123456789 7d
        """
        parts = message.text.split()

        if len(parts) < 2:
            await message.answer(
                "📊 <b>Stats Command</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/stats {chat_id} {timeframe}</code>\n"
                "<code>/stats {chat_id} {timeframe} user:{user_id}</code>\n"
                "<code>/stats {chat_id}:{user_id} {timeframe}</code>\n\n"
                "<b>Timeframes:</b> 1h, 6h, 24h, 2d, 7d, 14d, 30d\n\n"
                "<b>Examples:</b>\n"
                "• <code>/stats -1001234567890 24h</code>\n"
                "• <code>/stats -1009876543210 7d user:123456789</code>\n"
                "• <code>/stats -1009876543210:123456789 7d</code>",
                parse_mode="HTML"
            )
            return

        try:
            # Parse chat_id and optional user_id
            chat_id, user_id = self._parse_chat_user_id(parts[1])
            timeframe = "24h"

            # Parse remaining arguments
            for part in parts[2:]:
                if part.startswith("user:"):
                    user_id = int(part.split(":", 1)[1])
                elif part in ["1h", "6h", "24h", "2d", "7d", "14d", "30d"]:
                    timeframe = part

            # Get source info
            sources = await self.source_model.get_by_chat(chat_id)
            source = sources[0] if sources else None
            if not source:
                await message.answer(
                    f"❌ Source not found for chat_id {chat_id}" +
                    (f" and user_id {user_id}" if user_id else ""),
                    parse_mode="HTML"
                )
                return

            display_name = source.get("display_name", f"Chat {chat_id}")
            if user_id:
                display_name = f"{display_name} (User {user_id})"

            # Parse timeframe
            start_time, end_time = self._parse_timeframe(timeframe)

            # Calculate stats
            stats = await self.analytics_model.calculate_source_stats(
                chat_id, user_id, start_time, end_time
            )

            # Format response
            text = self._format_stats(display_name, stats, timeframe)
            await message.answer(text, parse_mode="HTML")

        except ValueError as exc:
            await message.answer(f"❌ Invalid input: {exc}", parse_mode="HTML")
        except Exception as exc:
            logger.error("Error in /stats command: %s", exc, exc_info=True)
            await message.answer("❌ Failed to load stats", parse_mode="HTML")

    async def cmd_top(self, message: types.Message) -> None:
        """
        Show leaderboard of top performing sources.

        Usage:
            /top {timeframe}

        Examples:
            /top
            /top 7d
            /top 30d
        """
        parts = message.text.split()
        timeframe = parts[1] if len(parts) > 1 else "7d"

        if timeframe not in ["1h", "6h", "24h", "2d", "7d", "14d", "30d"]:
            await message.answer(
                "❌ Invalid timeframe. Use: 1h, 6h, 24h, 2d, 7d, 14d, or 30d",
                parse_mode="HTML"
            )
            return

        try:
            # Get top sources from cached stats
            # Note: This requires stats cache to be populated first
            leaderboard = await self.analytics_model.get_top_sources(timeframe, limit=10)

            if not leaderboard:
                await message.answer(
                    f"📊 No stats available for {timeframe} period.\n\n"
                    "Stats are calculated hourly. Please check back later.",
                    parse_mode="HTML"
                )
                return

            # Format leaderboard
            text = self._format_leaderboard(leaderboard, timeframe)
            await message.answer(text, parse_mode="HTML")

        except Exception as exc:
            logger.error("Error in /top command: %s", exc, exc_info=True)
            await message.answer("❌ Failed to load leaderboard", parse_mode="HTML")

    async def cmd_patterns(self, message: types.Message) -> None:
        """
        Show time-based performance patterns (hourly and daily) across ALL sources.

        Usage:
            /patterns
            /patterns {chat_id}
            /patterns {timeframe}
            /patterns {chat_id} {timeframe}

        Examples:
            /patterns
            /patterns -1001234567890
            /patterns 30d
            /patterns -1001234567890 30d
        """
        parts = message.text.split()
        timeframe = "7d"
        chat_id = None

        if len(parts) > 1:
            if parts[1] in ["7d", "14d", "30d"]:
                timeframe = parts[1]
            else:
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await message.answer(
                        "❌ Invalid chat_id. Use: /patterns {chat_id} {timeframe}",
                        parse_mode="HTML",
                    )
                    return
                if len(parts) > 2:
                    timeframe = parts[2]

        if timeframe not in ["7d", "14d", "30d"]:
            await message.answer(
                "❌ Invalid timeframe. Use: 7d, 14d, or 30d",
                parse_mode="HTML",
            )
            return

        display_name = "All Sources"
        if chat_id is not None:
            sources = await self.source_model.get_by_chat(chat_id)
            if sources:
                display_name = sources[0].get("display_name", f"Chat {chat_id}")
            else:
                display_name = f"Chat {chat_id}"

        # Show timezone selection
        await message.answer(
            "📊 <b>Time Pattern Analysis</b>\n\n"
            f"Analyzing patterns for <b>{html.escape(display_name)}</b>.\n"
            f"Period: <b>{timeframe}</b>\n\n"
            "Select your timezone:",
            reply_markup=self._build_timezone_keyboard(timeframe, chat_id),
            parse_mode="HTML",
        )

    async def cmd_besthold(self, message: types.Message) -> None:
        """
        Show best hold duration based on 2x/5x milestone win rates.

        Usage:
            /besthold
            /besthold {timeframe}
            /besthold {chat_id}
            /besthold {chat_id} {timeframe}
            /besthold {chat_id} user:{user_id} {timeframe}
        """
        parts = message.text.split()
        timeframe = "7d"
        chat_id = None
        user_id = None
        valid_timeframes = ["1d", "7d", "10d", "14d", "21d", "30d"]

        if len(parts) > 1:
            if parts[1] in valid_timeframes:
                timeframe = parts[1]
            else:
                try:
                    chat_id, user_id = self._parse_chat_user_id(parts[1])
                except ValueError:
                    await message.answer(
                        "❌ Invalid chat_id. Use: /besthold {chat_id} {timeframe}",
                        parse_mode="HTML",
                    )
                    return
                for part in parts[2:]:
                    if part in valid_timeframes:
                        timeframe = part
                    elif part.startswith("user:"):
                        try:
                            user_id = int(part.split(":", 1)[1])
                        except ValueError:
                            await message.answer(
                                "❌ Invalid user_id. Use: /besthold {chat_id} user:{user_id} {timeframe}",
                                parse_mode="HTML",
                            )
                            return

        if timeframe not in valid_timeframes:
            await message.answer(
                "❌ Invalid timeframe. Use: 1d, 7d, 10d, 14d, 21d, or 30d",
                parse_mode="HTML",
            )
            return

        try:
            start_time, end_time = self._parse_besthold_timeframe(timeframe)
            result = await self.analytics_model.analyze_best_hold(chat_id, user_id, start_time, end_time)

            if result["total_tokens"] == 0:
                scope_label = "All Sources" if chat_id is None else f"Chat {chat_id}"
                await message.answer(
                    f"📊 <b>Best Hold ({html.escape(scope_label)})</b>\n"
                    f"Period: {timeframe}\n\n"
                    "No calls recorded in this period.",
                    parse_mode="HTML",
                )
                return

            display_name = "All Sources"
            if chat_id is not None:
                sources = await self.source_model.get_by_chat(chat_id)
                if sources:
                    display_name = sources[0].get("display_name", f"Chat {chat_id}")
                else:
                    display_name = f"Chat {chat_id}"
            if user_id is not None:
                display_name = f"{display_name} (User {user_id})"

            text = self._format_besthold(display_name, timeframe, result)
            await message.answer(text, parse_mode="HTML")

        except Exception as exc:
            logger.error("Error in /besthold command: %s", exc, exc_info=True)
            await message.answer("❌ Failed to load best hold analysis", parse_mode="HTML")

    def _build_timezone_keyboard(
        self,
        timeframe: str,
        chat_id: Optional[int] = None,
    ) -> types.InlineKeyboardMarkup:
        """Build keyboard with timezone options."""
        builder = InlineKeyboardBuilder()

        # Timezone options with country names
        timezones = [
            ("UTC", "UTC (Coordinated Universal Time)"),
            ("America/New_York", "EST/EDT (USA - New York)"),
            ("America/Los_Angeles", "PST/PDT (USA - Los Angeles)"),
            ("America/Chicago", "CST/CDT (USA - Chicago)"),
            ("Europe/London", "GMT/BST (United Kingdom)"),
            ("Europe/Paris", "CET/CEST (France/Germany)"),
            ("Asia/Dubai", "GST (UAE)"),
            ("Asia/Kolkata", "IST (India)"),
            ("Asia/Jakarta", "WIB (Indonesia - Jakarta)"),
            ("Asia/Singapore", "SGT (Singapore)"),
            ("Asia/Tokyo", "JST (Japan)"),
            ("Asia/Hong_Kong", "HKT (Hong Kong)"),
            ("Australia/Sydney", "AEDT/AEST (Australia)"),
            ("Pacific/Auckland", "NZDT/NZST (New Zealand)"),
        ]

        for tz_name, display_text in timezones:
            if chat_id is None:
                callback_data = f"patterns:tz:{tz_name}:{timeframe}"
            else:
                callback_data = f"patterns:tz:{tz_name}:{timeframe}:{chat_id}"
            builder.button(
                text=display_text,
                callback_data=callback_data,
            )

        builder.adjust(2)  # Two timezones per row
        return builder.as_markup()

    async def handle_timezone_selection(self, query: types.CallbackQuery) -> None:
        """Handle timezone selection and display patterns."""
        parts = query.data.split(":")
        tz_name = parts[2]
        timeframe = parts[3]
        chat_id = None
        if len(parts) > 4:
            try:
                chat_id = int(parts[4])
            except ValueError:
                chat_id = None

        try:
            # Parse timeframe
            start_time, end_time = self._parse_timeframe(timeframe)

            # Analyze patterns across all sources or a single chat
            patterns = await self.analytics_model.analyze_time_patterns(
                chat_id, start_time, end_time
            )
            best_hold = await self.analytics_model.analyze_best_hold(
                chat_id, None, start_time, end_time
            )
            best_hold_summary = self._extract_best_hold(best_hold)

            if patterns["hourly_total_calls"] == 0:
                scope_label = "All Sources" if chat_id is None else f"Chat {chat_id}"
                await query.message.edit_text(
                    f"📊 <b>Time Patterns ({html.escape(scope_label)})</b>\n"
                    f"Period: {timeframe}\n\n"
                    "No calls recorded in this period.",
                    parse_mode="HTML"
                )
                await query.answer()
                return

            display_name = "All Sources"
            if chat_id is not None:
                sources = await self.source_model.get_by_chat(chat_id)
                if sources:
                    display_name = sources[0].get("display_name", f"Chat {chat_id}")
                else:
                    display_name = f"Chat {chat_id}"

            # Format patterns with timezone conversion
            text = self._format_patterns_with_tz(
                display_name,
                patterns,
                timeframe,
                tz_name,
                best_hold_summary,
            )
            await query.message.edit_text(text, parse_mode="HTML")
            await query.answer()

        except Exception as exc:
            logger.error("Error in timezone selection: %s", exc, exc_info=True)
            await query.message.edit_text("❌ Failed to load patterns")
            await query.answer()

    def _parse_chat_user_id(self, raw: str) -> Tuple[int, Optional[int]]:
        """Parse 'chat_id' or 'chat_id:user_id' format."""
        if ":" in raw:
            parts = raw.split(":", 1)
            return int(parts[0]), int(parts[1])
        return int(raw), None

    def _parse_timeframe(self, timeframe: str) -> Tuple[datetime, datetime]:
        """Convert timeframe string to start/end datetime."""
        timeframe_map = {
            "1h": timedelta(hours=1),
            "6h": timedelta(hours=6),
            "24h": timedelta(hours=24),
            "2d": timedelta(days=2),
            "7d": timedelta(days=7),
            "14d": timedelta(days=14),
            "30d": timedelta(days=30),
        }

        duration = timeframe_map.get(timeframe)
        if not duration:
            raise ValueError(f"Invalid timeframe: {timeframe}")

        end_time = datetime.now(timezone.utc)
        start_time = end_time - duration
        return start_time, end_time

    def _parse_besthold_timeframe(self, timeframe: str) -> Tuple[datetime, datetime]:
        """Convert best-hold timeframe string to start/end datetime."""
        timeframe_map = {
            "1d": timedelta(days=1),
            "7d": timedelta(days=7),
            "10d": timedelta(days=10),
            "14d": timedelta(days=14),
            "21d": timedelta(days=21),
            "30d": timedelta(days=30),
        }
        duration = timeframe_map.get(timeframe)
        if not duration:
            raise ValueError(f"Invalid timeframe: {timeframe}")
        end_time = datetime.now(timezone.utc)
        start_time = end_time - duration
        return start_time, end_time

    def _format_stats(self, display_name: str, stats: dict, timeframe: str) -> str:
        """Format stats as HTML text."""
        total_calls = stats["total_calls"]

        if total_calls == 0:
            return (
                f"📊 <b>Stats for {html.escape(display_name)}</b>\n"
                f"Period: {timeframe}\n\n"
                f"No calls recorded in this period."
            )

        # Format win rates
        win_rate_2x = stats["win_rate_2x"]
        win_rate_5x = stats["win_rate_5x"]
        win_rate_10x = stats["win_rate_10x"]
        win_rate_100x = stats["win_rate_100x"]

        # Format time to peak
        avg_time_to_peak = stats["avg_time_to_peak_seconds"]
        if avg_time_to_peak > 0:
            hours = int(avg_time_to_peak // 3600)
            minutes = int((avg_time_to_peak % 3600) // 60)
            if hours > 0:
                time_to_peak_str = f"{hours}h {minutes}m"
            else:
                time_to_peak_str = f"{minutes}m"
        else:
            time_to_peak_str = "N/A"

        # Format multipliers
        avg_peak_mult = stats["avg_peak_multiplier"]
        best_mult = stats["best_multiplier"]
        worst_mult = stats["worst_multiplier"]

        text = (
            f"📊 <b>Stats for {html.escape(display_name)}</b>\n"
            f"Period: {timeframe}\n\n"
            f"📞 <b>Total Calls:</b> {total_calls}\n\n"
            f"🎯 <b>Win Rates:</b>\n"
            f"  • 2x: {win_rate_2x:.1f}% ({stats['hits_2x']}/{total_calls})\n"
            f"  • 5x: {win_rate_5x:.1f}% ({stats['hits_5x']}/{total_calls})\n"
            f"  • 10x: {win_rate_10x:.1f}% ({stats['hits_10x']}/{total_calls})\n"
            f"  • 100x: {win_rate_100x:.1f}% ({stats['hits_100x']}/{total_calls})\n\n"
            f"📊 <b>Performance:</b>\n"
            f"  • Avg Peak: {avg_peak_mult:.2f}x\n"
            f"  • Avg Time to Peak: {time_to_peak_str}\n"
            f"  • Best Call: {best_mult:.2f}x\n"
            f"  • Worst Call: {worst_mult:.2f}x\n"
        )

        return text

    def _format_leaderboard(self, leaderboard: list, timeframe: str) -> str:
        """Format leaderboard as HTML text."""
        text = f"🏆 <b>Top Callers ({timeframe})</b>\n\n"

        for idx, source in enumerate(leaderboard, 1):
            display_name = source.get("display_name", f"Chat {source['chat_id']}")
            total_calls = source["total_calls"]
            win_rate_2x = source["win_rate_2x"]

            text += f"{idx}. {html.escape(display_name)} - {win_rate_2x:.1f}% hit 2x ({total_calls} calls)\n"

        return text

    def _format_patterns(
        self,
        display_name: str,
        patterns: dict,
        timeframe: str,
        best_hold_summary: Optional[dict] = None,
    ) -> str:
        """Format time patterns as HTML text."""
        text = f"📊 <b>Patterns for {html.escape(display_name)}</b>\n"
        text += f"Period: {timeframe}\n\n"

        # Hourly breakdown
        text += "⏰ <b>Hourly Performance (UTC):</b>\n"
        hourly = patterns["hourly"]
        for hour_data in hourly:
            hour = hour_data["hour_utc"]
            calls = hour_data["calls"]
            win_rate = hour_data["win_rate_2x"]
            bar = self._make_bar(win_rate, max_length=10)
            text += f"{hour:02d}:00 {bar} {win_rate:.1f}% ({calls} calls)\n"

        # Best hour
        text += f"\n🏆 Best hour: {patterns['best_hour_utc']:02d}:00 UTC ({patterns['best_hour_win_rate']:.1f}%)\n\n"

        best_session = patterns.get("best_session")
        if best_session:
            start_hour = best_session["start_hour_utc"]
            end_hour = (start_hour + best_session["window_hours"]) % 24
            text += (
                f"🔥 Best session: {best_session['window_hours']}h window "
                f"{start_hour:02d}:00–{end_hour:02d}:00 UTC "
                f"({best_session['win_rate_2x']:.1f}%, {best_session['calls']} calls)\n\n"
            )

        # Daily breakdown (ISODOW: 1=Mon, 7=Sun)
        text += "📅 <b>Daily Performance (UTC):</b>\n"
        day_names = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        daily = patterns["daily"]
        for day_data in daily:
            day = day_data["day"]  # 1-7
            calls = day_data["calls"]
            win_rate = day_data["win_rate_2x"]
            bar = self._make_bar(win_rate, max_length=10)
            day_name = day_names[day] if 1 <= day <= 7 else f"Day{day}"
            text += f"{day_name} {bar} {win_rate:.1f}% ({calls} calls)\n"
            best_hour = day_data.get("best_hour")
            if best_hour:
                text += f"      Best Hour: {best_hour['hour_utc']:02d}:00 ({best_hour['win_rate_2x']:.1f}%)\n"

        # Best day
        best_day = patterns["best_day"]
        best_day_name = day_names[best_day] if 1 <= best_day <= 7 else f"Day{best_day}"
        text += f"\n🏆 Best day (UTC): {best_day_name} ({patterns['best_day_win_rate']:.1f}%)\n"
        if best_hold_summary:
            text += (
                f"⏱ Best timeframe: {best_hold_summary['label']} "
                f"({best_hold_summary['win_rate_2x']:.1f}% 2x, "
                f"{best_hold_summary['win_rate_5x']:.1f}% 5x)\n"
            )

        return text

    def _format_besthold(self, display_name: str, timeframe: str, result: dict) -> str:
        total_tokens = result["total_tokens"]
        rows = result["rows"]

        formatted = []
        best_2x = None
        best_5x = None

        for row in rows:
            label = row["label"]
            hits_2x = row["hits_2x"] or 0
            hits_5x = row["hits_5x"] or 0
            win_rate_2x = (hits_2x / total_tokens * 100) if total_tokens > 0 else 0.0
            win_rate_5x = (hits_5x / total_tokens * 100) if total_tokens > 0 else 0.0

            formatted.append({
                "label": label,
                "seconds": row["seconds"],
                "hits_2x": hits_2x,
                "hits_5x": hits_5x,
                "win_rate_2x": win_rate_2x,
                "win_rate_5x": win_rate_5x,
            })

            candidate_2x = (win_rate_2x, -row["seconds"])
            if best_2x is None or candidate_2x > (best_2x["win_rate_2x"], -best_2x["seconds"]):
                best_2x = formatted[-1]

            candidate_5x = (win_rate_5x, -row["seconds"])
            if best_5x is None or candidate_5x > (best_5x["win_rate_5x"], -best_5x["seconds"]):
                best_5x = formatted[-1]

        top_3_2x = sorted(
            formatted,
            key=lambda row: (row["win_rate_2x"], -row["seconds"]),
            reverse=True,
        )[:3]
        top_3_5x = sorted(
            formatted,
            key=lambda row: (row["win_rate_5x"], -row["seconds"]),
            reverse=True,
        )[:3]

        median_time_to_2x = result.get("median_time_to_2x_seconds")

        text = (
            f"📊 <b>Best Hold ({html.escape(display_name)})</b>\n"
            f"Period: {timeframe} • Tokens: {total_tokens}\n\n"
        )

        if best_2x:
            text += (
                f"🏆 <b>Best 2x:</b> {best_2x['label']} • "
                f"{best_2x['win_rate_2x']:.1f}% "
                f"({best_2x['hits_2x']}/{total_tokens})\n"
            )
        if best_5x:
            text += (
                f"🏆 <b>Best 5x:</b> {best_5x['label']} • "
                f"{best_5x['win_rate_5x']:.1f}% "
                f"({best_5x['hits_5x']}/{total_tokens})\n"
            )
        if median_time_to_2x:
            text += (
                f"⏱ <b>Median time to 2x:</b> {format_duration(int(median_time_to_2x))}\n"
            )

        if top_3_2x:
            text += "\n🥇 <b>Top 3 Holds (2x):</b>\n"
            for idx, row in enumerate(top_3_2x, 1):
                text += f"{idx}. {row['label']} • {row['win_rate_2x']:.1f}%\n"

        if top_3_5x:
            text += "\n🥇 <b>Top 3 Holds (5x):</b>\n"
            for idx, row in enumerate(top_3_5x, 1):
                text += f"{idx}. {row['label']} • {row['win_rate_5x']:.1f}%\n"

        text += "\n⏱ <b>Hold Durations</b> (tap to expand)\n"
        text += "<blockquote expandable>\n"
        max_label = max((len(row["label"]) for row in formatted), default=4)
        max_label = min(max_label, 8)
        text += f"<code>{'Hold':<{max_label}}   {'2x%':>6}   {'5x%':>6}</code>\n"
        for row in formatted:
            label = row["label"][:max_label]
            win_2x = f"{row['win_rate_2x']:.1f}%"
            win_5x = f"{row['win_rate_5x']:.1f}%"
            text += f"<code>{label:<{max_label}}   {win_2x:>6}   {win_5x:>6}</code>\n"
        text += "</blockquote>\n"

        return text

    def _format_patterns_with_tz(
        self,
        display_name: str,
        patterns: dict,
        timeframe: str,
        tz_name: str,
        best_hold_summary: Optional[dict] = None,
    ) -> str:
        """Format time patterns with timezone-adjusted hourly display."""
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = timezone.utc
            tz_name = "UTC"

        now_utc = datetime.now(timezone.utc)
        tz_abbrev = now_utc.astimezone(tz).tzname() or tz_name

        text_lines = [
            f"📊 <b>Patterns for {html.escape(display_name)}</b>",
            f"Period: {timeframe}",
            f"Timezone: {html.escape(tz_name)} ({html.escape(tz_abbrev)})",
            "",
        ]

        # Hourly breakdown (timezone-adjusted from UTC buckets)
        text_lines.append(f"⏰ <b>Hourly Performance ({html.escape(tz_abbrev)}):</b>")
        hourly_local = []
        for hour_data in patterns["hourly"]:
            hour_utc = hour_data["hour_utc"]
            base = now_utc.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
            local_dt = base.astimezone(tz)
            hourly_local.append({
                **hour_data,
                "local_hour": local_dt.hour,
                "local_minute": local_dt.minute,
            })

        hourly_local.sort(key=lambda item: (item["local_hour"], item["local_minute"]))

        for hour_data in hourly_local:
            calls = hour_data["calls"]
            win2 = hour_data["win_rate_2x"]
            bar = self._make_bar(win2, max_length=10)
            time_label = f"{hour_data['local_hour']:02d}:{hour_data['local_minute']:02d}"
            text_lines.append(f"{time_label} {bar} {win2:.1f}% ({calls} calls)")
        text_lines.append("")

        # Best hour (show both local and UTC)
        best_hour_utc = patterns["best_hour_utc"]
        best_base = now_utc.replace(hour=best_hour_utc, minute=0, second=0, microsecond=0)
        best_local = best_base.astimezone(tz)
        best_local_label = f"{best_local.hour:02d}:{best_local.minute:02d}"
        text_lines.extend([
            f"🏆 Best hour: {best_local_label} {html.escape(tz_abbrev)} "
            f"({patterns['best_hour_win_rate']:.1f}%)",
            f"   ({best_hour_utc:02d}:00 UTC)",
            "",
        ])

        best_session = patterns.get("best_session")
        if best_session:
            start_hour = best_session["start_hour_utc"]
            end_hour = (start_hour + best_session["window_hours"]) % 24
            start_utc = now_utc.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            end_utc = start_utc + timedelta(hours=best_session["window_hours"])
            start_local = start_utc.astimezone(tz)
            end_local = end_utc.astimezone(tz)
            start_label = f"{start_local.hour:02d}:{start_local.minute:02d}"
            end_label = f"{end_local.hour:02d}:{end_local.minute:02d}"
            text_lines.extend([
                f"🔥 Best session: {best_session['window_hours']}h window "
                f"{start_label}–{end_label} {html.escape(tz_abbrev)} "
                f"({best_session['win_rate_2x']:.1f}%, {best_session['calls']} calls)",
                f"   ({start_hour:02d}:00–{end_hour:02d}:00 UTC)",
                "",
            ])

        # Daily breakdown remains UTC-based (source data is aggregated by UTC day)
        text_lines.append("📅 <b>Daily Performance (UTC):</b>")
        day_names = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        daily = patterns["daily"]
        for day_data in daily:
            day = day_data["day"]  # 1-7
            calls = day_data["calls"]
            win2 = day_data["win_rate_2x"]
            bar = self._make_bar(win2, max_length=10)
            day_name = day_names[day] if 1 <= day <= 7 else f"Day{day}"
            text_lines.append(f"{day_name} {bar} {win2:.1f}% ({calls} calls)")
            best_hour = day_data.get("best_hour")
            if best_hour:
                text_lines.append(
                    f"      Best Hour: {best_hour['hour_utc']:02d}:00 ({best_hour['win_rate_2x']:.1f}%)"
                )
        text_lines.append("")

        best_day = patterns["best_day"]
        best_day_name = day_names[best_day] if 1 <= best_day <= 7 else f"Day{best_day}"
        text_lines.append(f"🏆 Best day (UTC): {best_day_name} ({patterns['best_day_win_rate']:.1f}%)")
        if best_hold_summary:
            text_lines.append(
                f"⏱ Best timeframe: {best_hold_summary['label']} "
                f"({best_hold_summary['win_rate_2x']:.1f}% 2x, "
                f"{best_hold_summary['win_rate_5x']:.1f}% 5x)"
            )

        return self._sanitize_html("\n".join(text_lines))

    @staticmethod
    def _extract_best_hold(best_hold: dict) -> Optional[dict]:
        total_tokens = best_hold.get("total_tokens") or 0
        rows = best_hold.get("rows") or []
        if total_tokens <= 0 or not rows:
            return None
        best = None
        for row in rows:
            hits_2x = row["hits_2x"] or 0
            hits_5x = row["hits_5x"] or 0
            win_rate_2x = (hits_2x / total_tokens * 100) if total_tokens else 0.0
            win_rate_5x = (hits_5x / total_tokens * 100) if total_tokens else 0.0
            candidate = (win_rate_2x, -row["seconds"])
            if best is None or candidate > (best["win_rate_2x"], -best["seconds"]):
                best = {
                    "label": row["label"],
                    "seconds": row["seconds"],
                    "win_rate_2x": win_rate_2x,
                    "win_rate_5x": win_rate_5x,
                }
        return best

    def _make_bar(self, percentage: float, max_length: int = 10) -> str:
        """Create a visual bar for percentage display."""
        filled = int((percentage / 100) * max_length)
        empty = max_length - filled
        return "█" * filled + "░" * empty

    @staticmethod
    def _sanitize_html(text: str) -> str:
        allowed = (
            "<b>",
            "</b>",
            "<code>",
            "</code>",
            "<blockquote>",
            "</blockquote>",
            "<blockquote expandable>",
        )
        i = 0
        out: list[str] = []
        while i < len(text):
            if text[i] == "<":
                matched = False
                for tag in allowed:
                    if text.startswith(tag, i):
                        out.append(tag)
                        i += len(tag)
                        matched = True
                        break
                if not matched:
                    out.append("&lt;")
                    i += 1
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    def _format_mc_short(self, value: float) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric >= 1_000_000_000:
            return f"${numeric / 1_000_000_000:.2f}B"
        if numeric >= 1_000_000:
            return f"${numeric / 1_000_000:.2f}M"
        if numeric >= 1_000:
            return f"${numeric / 1_000:.2f}K"
        return f"${numeric:.2f}"


    async def cmd_invest(self, message: types.Message) -> None:
        """
        Simulate investment P&L across token calls.

        Usage:
            /invest {amount}
            /invest {amount} {chat_id}
            /invest {amount} {chat_id} {hold_strategy}
            /invest {amount} {chat_id} {hold_strategy} {timeframe}

        Examples:
            /invest 100                    # $100 across all sources, last 24h, hold to peak
            /invest 100 -1001234567890     # $100 on specific source
            /invest 100 all 1h             # Hold for 1h instead of peak
            /invest 100 all peak 7d        # Last 7 days
            /invest 100 all current        # Still holding (current price)
        """
        parts = message.text.split()

        if len(parts) < 2:
            await message.answer(
                "💰 <b>Investment Simulator</b>\n\n"
                "<b>Usage:</b>\n"
                "<code>/invest {amount_per_token}</code>\n"
                "<code>/invest {amount_per_token} {chat_id}</code>\n"
                "<code>/invest {amount_per_token} {chat_id} {hold} {period}</code>\n\n"
                "Amount is <b>per token</b> (not total).\n"
                "Total = amount × number of tokens\n\n"
                "<b>Hold Strategies:</b>\n"
                "• <code>peak</code> - Sell at peak MC (default)\n"
                "• <code>current</code> - Still holding at current MC\n"
                "• <code>1h</code>, <code>6h</code>, <code>24h</code> - Hold for duration\n\n"
                "<b>Periods:</b> 24h (default), 7d, 30d\n\n"
                "<b>Examples:</b>\n"
                "• <code>/invest 100</code> - $100 per token\n"
                "• <code>/invest 100 -1001234567890</code>\n"
                "• <code>/invest 100 all 1h</code>\n"
                "• <code>/invest 100 all peak 7d</code>",
                parse_mode="HTML"
            )
            return

        try:
            # Parse amount
            amount_str = parts[1].replace("$", "").replace(",", "")
            amount = float(amount_str)

            if amount <= 0:
                await message.answer("❌ Amount must be positive", parse_mode="HTML")
                return

            # Parse chat_id (optional)
            chat_id = None
            if len(parts) > 2 and parts[2].lower() not in ["all", "peak", "current", "1h", "6h", "24h"]:
                try:
                    chat_id = int(parts[2])
                except ValueError:
                    pass

            # Parse hold strategy (optional)
            hold_strategy = "peak"
            if len(parts) > 3:
                if parts[3].lower() in ["peak", "current", "1h", "6h", "24h"]:
                    hold_strategy = parts[3].lower()
            elif len(parts) > 2 and chat_id is None:
                if parts[2].lower() in ["peak", "current", "1h", "6h", "24h"]:
                    hold_strategy = parts[2].lower()

            # Parse timeframe (optional)
            timeframe_hours = 24
            if len(parts) > 4:
                timeframe_str = parts[4].lower()
                if timeframe_str == "7d":
                    timeframe_hours = 168
                elif timeframe_str == "30d":
                    timeframe_hours = 720
            elif len(parts) > 3 and chat_id is None:
                timeframe_str = parts[3].lower()
                if timeframe_str == "7d":
                    timeframe_hours = 168
                elif timeframe_str == "30d":
                    timeframe_hours = 720

            # Run simulation
            sim = await self.analytics_model.simulate_investment(
                amount=amount,
                chat_id=chat_id,
                timeframe_hours=timeframe_hours,
                hold_strategy=hold_strategy,
            )

            if "error" in sim:
                await message.answer(f"❌ {sim['error']}", parse_mode="HTML")
                return

            # Format results
            text = self._format_investment_results(sim)
            await message.answer(text, parse_mode="HTML")

        except ValueError as exc:
            await message.answer(f"❌ Invalid input: {exc}", parse_mode="HTML")
        except Exception as exc:
            logger.error("Error in /invest command: %s", exc, exc_info=True)
            await message.answer("❌ Failed to simulate investment", parse_mode="HTML")

    def _format_investment_results(self, sim: dict) -> str:
        """Format investment simulation results as HTML."""
        settings = sim["settings"]
        amount = settings["amount"]
        chat_id = settings.get("chat_id")
        hold = settings["hold_strategy"]
        timeframe_h = settings.get("timeframe_hours", 24)

        timeframe_label = f"{timeframe_h}h"

        source_label = f"Chat {chat_id}" if chat_id else "All"
        if chat_id and settings.get("user_id") is not None:
            source_label = f"{source_label} (User {settings['user_id']})"

        slippage_model = settings.get("slippage_model")
        liquidity_pct = settings.get("liquidity_pct_of_mc")
        trojan_fee_pct = settings.get("trojan_fee_pct")
        if slippage_model == "liquidity_ratio" and liquidity_pct is None:
            liquidity_pct = 10.0
        if trojan_fee_pct is None:
            trojan_fee_pct = 0.0

        if hold in ("peak", "current"):
            hold_label = hold.title()
        else:
            hold_label = hold
        header = f"💰 <b>Investment Simulation — {timeframe_label} | Hold {hold_label}</b>"
        text_lines = [header, ""]

        # Summary
        total_final = sim["total_final_value"]
        total_pnl = sim["total_pnl"]
        total_pnl_pct = sim["total_pnl_pct"]
        winners = sim["winners_count"]
        losers = sim["losers_count"]
        win_threshold_pct = settings.get("win_threshold_pct", 0.0)
        avg_pnl_pct = sim.get("avg_pnl_pct", 0.0)
        top3_profit_share_pct = sim.get("top3_profit_share_pct", 0.0)
        total_fees_usd = sim.get("total_fees_usd", 0.0)
        total_gas_usd = sim.get("total_gas_usd", 0.0)
        total_trojan_fees_usd = sim.get("total_trojan_fees_usd", 0.0)
        win_rate_pct = (winners / sim["total_tokens"] * 100) if sim["total_tokens"] else 0.0
        fallback_count = sim.get("fallback_count", 0)
        fallback_hold_avg_seconds = sim.get("fallback_hold_avg_seconds")
        fallback_hold_min_seconds = sim.get("fallback_hold_min_seconds")
        fallback_hold_max_seconds = sim.get("fallback_hold_max_seconds")
        excluded_due_to_age = sim.get("excluded_due_to_age", 0)

        pnl_sign = "+" if total_pnl >= 0 else ""
        pnl_emoji = "🟩" if total_pnl >= 0 else "🟥"
        text_lines.extend([
            "<b>📊 SUMMARY</b>",
            f"Final Value:        ${total_final:,.2f}",
            f"Total P&L:          {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pnl_pct:.0f}%) {pnl_emoji}",
            f"Total Invested:     ${sim['total_invested']:,.2f}",
            f"Fees Paid:          ${total_fees_usd:,.2f}",
            f"Win Rate:           {winners} / {sim['total_tokens']} ({win_rate_pct:.0f}%)",
            f"Average Gain:       {avg_pnl_pct:+.1f}%",
            f"Top 3 Impact:       {top3_profit_share_pct:.0f}% of total profit",
            "",
            "<b>⚙️ SETTINGS</b>",
            f"Per Token:          ${amount:,.2f}",
            f"Period:             Last {timeframe_label} ({sim['total_tokens']} tokens)",
            f"Hold Time:          {hold_label}",
            f"Sources:            {source_label}",
            f"Slippage:           Liquidity-based ({liquidity_pct:.0f}%)",
            f"Gas Cost:           ${total_gas_usd / sim['total_tokens'] if sim['total_tokens'] else 0:.2f} per token",
            f"Trojan Fee:         {trojan_fee_pct:.2f}% per trade",
            "",
        ])
        if fallback_count:
            if fallback_hold_avg_seconds is not None:
                avg_hold = format_duration(int(fallback_hold_avg_seconds))
                min_hold = format_duration(int(fallback_hold_min_seconds)) if fallback_hold_min_seconds is not None else "N/A"
                max_hold = format_duration(int(fallback_hold_max_seconds)) if fallback_hold_max_seconds is not None else "N/A"
                text_lines.append(
                    f"ℹ️ {fallback_count} token(s) missing {hold_label} data; "
                    f"used last available hold avg {avg_hold} (min {min_hold}, max {max_hold})."
                )
            else:
                text_lines.append(
                    f"ℹ️ {fallback_count} token(s) missing {hold_label} data; "
                    f"used last available hold."
                )
            text_lines.append("")
        if excluded_due_to_age:
            text_lines.append(
                f"ℹ️ {excluded_due_to_age} token(s) excluded (age < {hold_label})."
            )
            text_lines.append("")

        # Top performers
        results = sim["results"]
        if results:
            lines = []
            for idx, r in enumerate(results[:15], 1):
                ticker = html.escape(r.get("ticker") or "")
                final_value = f"{r['final_value']:,.2f}"
                pnl_pct = r["pnl_pct"]
                pnl_sign = "+" if pnl_pct >= 0 else ""
                emoji = "🟩" if pnl_pct >= 0 else "🟥"
                lines.append(
                    f"{idx}. {ticker}   {pnl_sign}{pnl_pct:.0f}%   ${final_value} {emoji}"
                )
            text_lines.append("<b>🚀 TOP PERFORMERS</b>")
            text_lines.append("<blockquote>" + "\n".join(lines) + "</blockquote>")
            text_lines.append("")

            mc_lines = []
            for r in results[:15]:
                ticker = html.escape(r.get("ticker") or "")
                entry_mc = self._format_mc_short(r.get("entry_mc"))
                exit_mc = self._format_mc_short(r.get("exit_mc"))
                mc_lines.append(f"{ticker}:   {entry_mc} → {exit_mc}")
            text_lines.append("<b>📉 MC MOVE (TOP 15)</b>")
            text_lines.append("<blockquote expandable>" + "\n".join(mc_lines) + "</blockquote>")
            text_lines.append("")

        # Worst performers (negative P&L only)
        worst_results = sim.get("worst_results", [])
        if worst_results:
            lines = []
            for idx, r in enumerate(worst_results, 1):
                ticker = html.escape(r.get("ticker") or "")
                final_value = f"{r['final_value']:,.2f}"
                pnl_pct = r["pnl_pct"]
                pnl_sign = "+" if pnl_pct >= 0 else ""
                lines.append(f"{idx}. {ticker}   {pnl_sign}{pnl_pct:.0f}%   ${final_value} 🟥")
            text_lines.append("<b>🔻 WORST PERFORMERS</b>")
            text_lines.append("<blockquote>" + "\n".join(lines) + "</blockquote>")

        return "\n".join(text_lines)
