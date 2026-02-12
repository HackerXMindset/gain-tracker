from __future__ import annotations

import asyncio
import html
import logging
from typing import Dict, List, Optional

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from models import MonitoredSourceModel
from db import db

logger = logging.getLogger(__name__)


class InfoHandler:
    """Handler for /info command (database-backed source/user info)."""

    def __init__(self, db_pool=None) -> None:
        self.db = db_pool or db
        self.source_model = MonitoredSourceModel(self.db)
        self._chat_title_cache: Dict[int, str] = {}
        self._member_display_cache: Dict[tuple[int, int], str] = {}
        self._user_display_cache: Dict[int, str] = {}

    async def cmd_info(self, message: types.Message) -> None:
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "ℹ️ <b>Info Command</b>\n\n"
                "Usage:\n"
                "<code>/info &lt;chat_id&gt;</code>\n"
                "<code>/info &lt;chat_id&gt; user:&lt;user_id&gt;</code>\n"
                "<code>/info user:&lt;user_id&gt;</code>\n"
                "<code>/info @username</code>\n\n"
                "Shows database stats + tracking config (not Telegram profile info).",
                parse_mode="HTML",
            )
            return

        raw = parts[1].strip()
        chat_id: Optional[int] = None
        user_id: Optional[int] = None

        if raw.startswith("user:"):
            try:
                user_id = int(raw.split(":", 1)[1])
            except ValueError:
                await message.answer("❌ Invalid user_id. Use: /info user:&lt;user_id&gt;", parse_mode="HTML")
                return
        elif raw.startswith("@"):  # username
            try:
                chat = await message.bot.get_chat(raw)
                chat_id = int(chat.id)
            except Exception as exc:
                await message.answer(f"❌ Unable to resolve username: {html.escape(str(exc))}", parse_mode="HTML")
                return
        else:
            try:
                chat_id = int(raw)
            except ValueError:
                await message.answer("❌ Invalid chat_id. Use: /info &lt;chat_id&gt;", parse_mode="HTML")
                return

        # Allow user filter for a specific chat_id
        if len(parts) > 2:
            for part in parts[2:]:
                if part.startswith("user:"):
                    try:
                        user_id = int(part.split(":", 1)[1])
                    except ValueError:
                        await message.answer("❌ Invalid user_id. Use: /info <chat_id> user:<id>", parse_mode="HTML")
                        return

        if chat_id is None and user_id is None:
            await message.answer("❌ Provide a chat_id or user_id.", parse_mode="HTML")
            return

        if chat_id is not None:
            await self._show_chat_info(message, chat_id, user_id)
        else:
            await self._show_user_info(message, user_id)

    async def _show_chat_info(self, message: types.Message, chat_id: int, user_id: Optional[int]) -> None:
        try:
            records = await self.source_model.get_by_chat(chat_id)
            if not records:
                await message.answer(f"❌ No monitored source found for <code>{chat_id}</code>", parse_mode="HTML")
                return

            # Pick a record for config display
            selected = None
            if user_id is not None:
                selected = next((r for r in records if r.get("user_id") == user_id), None)
            if selected is None:
                selected = next((r for r in records if r.get("chat_type") == "group" and r.get("user_id") is None), None)
            if selected is None:
                selected = records[0]

            chat_type = selected.get("chat_type")
            chat_titles = await self._resolve_chat_titles(message.bot, [chat_id])
            resolved_title = chat_titles.get(chat_id)
            display_name = selected.get("display_name") or resolved_title or str(chat_id)
            track_all = any(r.get("chat_type") == "group" and r.get("user_id") is None for r in records)
            tracked_users = [r.get("user_id") for r in records if r.get("user_id") is not None]

            total_calls = await self.db.fetchval(
                "SELECT COUNT(*) FROM token_group_alerts WHERE chat_id = $1",
                chat_id,
            ) or 0
            unique_tokens = await self.db.fetchval(
                "SELECT COUNT(DISTINCT token_id) FROM token_group_alerts WHERE chat_id = $1",
                chat_id,
            ) or 0
            unique_callers = await self.db.fetchval(
                """
                SELECT COUNT(DISTINCT original_user_id)
                FROM token_group_alerts
                WHERE chat_id = $1 AND original_user_id IS NOT NULL
                """,
                chat_id,
            ) or 0

            exclusions = await self.db.fetchval(
                "SELECT COUNT(*) FROM monitored_source_exclusions WHERE chat_id = $1",
                chat_id,
            ) or 0

            last_token = await self.db.fetchrow(
                """
                SELECT tga.token_id, tga.created_at, tga.original_user_id,
                       tt.address, tt.ticker, tt.first_seen_mc, tt.peak_mc, tt.last_mc
                FROM token_group_alerts tga
                JOIN tokens_tracked tt ON tt.id = tga.token_id
                WHERE tga.chat_id = $1
                  AND ($2::BIGINT IS NULL OR tga.original_user_id = $2)
                ORDER BY tga.created_at DESC NULLS LAST, tga.id DESC
                LIMIT 1
                """,
                chat_id,
                user_id,
            )

            caller_map: Dict[int, str] = {}
            top_callers = await self.db.fetch(
                """
                SELECT original_user_id, COUNT(*) AS token_count
                FROM token_group_alerts
                WHERE chat_id = $1 AND original_user_id IS NOT NULL
                GROUP BY original_user_id
                ORDER BY token_count DESC
                LIMIT 10
                """,
                chat_id,
            )
            if top_callers:
                caller_ids = [int(row["original_user_id"]) for row in top_callers if row.get("original_user_id") is not None]
                caller_map = await self._resolve_user_display_names(message.bot, chat_id, caller_ids)

            top_tokens = await self.db.fetch(
                """
                SELECT
                    tt.address,
                    COALESCE(tt.ticker, tt.address) AS ticker,
                    tt.first_seen_mc,
                    tt.peak_mc,
                    (tt.peak_mc / NULLIF(tt.first_seen_mc, 0)) AS mult
                FROM tokens_tracked tt
                JOIN token_group_alerts tga ON tga.token_id = tt.id
                WHERE tga.chat_id = $1
                ORDER BY mult DESC NULLS LAST
                LIMIT 10
                """,
                chat_id,
            )

            targets = []
            if selected.get("id"):
                targets = await self.source_model.get_targets(int(selected["id"]))

            last_caller_display = None
            if last_token and last_token.get("original_user_id"):
                last_caller_display = await self._resolve_user_display_name(
                    message.bot,
                    chat_id,
                    int(last_token.get("original_user_id")),
                )

            stats_line = (
                f"• Total calls: {total_calls} | Unique tokens: {unique_tokens} | Unique callers: {unique_callers}"
            )

            lines = [
                "ℹ️ <b>DB Info</b>",
                "",
                f"• Chat: {self._format_name_with_id(display_name, chat_id)}",
                f"• Type: {html.escape(str(chat_type))}",
                f"• Track all users: {'Yes' if track_all else 'No'}",
                f"• Tracked users: {len(tracked_users)} | Excluded users: {exclusions}",
                stats_line,
                "",
                "<b>Modes</b>",
                f"• Tracking enabled: {'Yes' if selected.get('tracking_enabled', True) else 'No'}",
                f"• Alerts enabled: {'Yes' if selected.get('is_enabled', True) else 'No'}",
                f"• Sensitivity: {selected.get('sensitivity_pct') if selected.get('sensitivity_pct') is not None else 'Global'}",
                f"• Template: {'Custom' if selected.get('template_text') else 'Global'}",
                f"• Use management bot: {'Yes' if selected.get('use_management_bot') else 'No'}",
                f"• Chart enabled: {'Yes' if selected.get('chart_enabled') else 'No'}",
                f"• Chart bot: {selected.get('chart_bot_id') or 'Global'}",
                f"• Chart threshold: {selected.get('chart_mc_threshold') or 'Global'}",
                f"• Tracker userbot: {selected.get('tracking_userbot_id') or 'Any'}",
                f"• Tracker fallback: {'Yes' if selected.get('tracking_fallback_enabled', True) else 'No'}",
            ]

            if targets:
                lines.append("")
                lines.append("<b>Targets</b>")
                for tgt in targets[:10]:
                    label = tgt.get("target_label") or str(tgt.get("target_chat_id"))
                    lines.append(f"• {html.escape(str(label))} (<code>{tgt.get('target_chat_id')}</code>)")
                if len(targets) > 10:
                    lines.append(f"• ... and {len(targets) - 10} more")

            if last_token:
                lines.append("")
                lines.append("<b>Last tracked token</b>")
                ticker = last_token.get("ticker") or last_token.get("address")
                lines.append(f"• {html.escape(str(ticker))}")
                lines.append(f"• Address: <code>{html.escape(str(last_token.get('address')))}</code>")
                if last_token.get("original_user_id"):
                    caller_id = int(last_token.get("original_user_id"))
                    caller_label = last_caller_display or str(caller_id)
                    lines.append(f"• Caller: {self._format_name_with_id(caller_label, caller_id)}")
                lines.append(f"• Seen at: {html.escape(str(last_token.get('created_at')))}")

            if top_callers:
                lines.append("")
                lines.append("<b>Top callers</b>")
                for row in top_callers:
                    caller_id = int(row["original_user_id"])
                    caller_name = caller_map.get(caller_id, str(caller_id))
                    lines.append(f"• {self._format_name_with_id(caller_name, caller_id)} – {row['token_count']} token(s)")

            if top_tokens:
                lines.append("")
                lines.append("<b>Top tokens (peak multiplier)</b>")
                for row in top_tokens:
                    mult = row.get("mult") or 0
                    lines.append(f"• {html.escape(str(row.get('ticker')))} – {mult:.2f}x")

            await message.answer("\n".join(lines), parse_mode="HTML")
        except Exception as exc:
            logger.error("Error building DB info for chat %s: %s", chat_id, exc, exc_info=True)
            await message.answer("❌ Failed to load DB info", parse_mode="HTML")

    async def _show_user_info(self, message: types.Message, user_id: int) -> None:
        try:
            rows = await self.db.fetch(
                """
                SELECT chat_id,
                       COUNT(*) AS token_count,
                       MAX(created_at) AS last_seen
                FROM token_group_alerts
                WHERE original_user_id = $1
                GROUP BY chat_id
                ORDER BY token_count DESC
                LIMIT 20
                """,
                user_id,
            )

            total_calls = await self.db.fetchval(
                "SELECT COUNT(*) FROM token_group_alerts WHERE original_user_id = $1",
                user_id,
            ) or 0
            unique_chats = await self.db.fetchval(
                "SELECT COUNT(DISTINCT chat_id) FROM token_group_alerts WHERE original_user_id = $1",
                user_id,
            ) or 0
            unique_tokens = await self.db.fetchval(
                "SELECT COUNT(DISTINCT token_id) FROM token_group_alerts WHERE original_user_id = $1",
                user_id,
            ) or 0

            last_token = await self.db.fetchrow(
                """
                SELECT tga.chat_id, tga.created_at, tt.address, tt.ticker
                FROM token_group_alerts tga
                JOIN tokens_tracked tt ON tt.id = tga.token_id
                WHERE tga.original_user_id = $1
                ORDER BY tga.created_at DESC NULLS LAST, tga.id DESC
                LIMIT 1
                """,
                user_id,
            )

            best_token = await self.db.fetchrow(
                """
                SELECT tt.address, tt.ticker, tt.first_seen_mc, tt.peak_mc
                FROM tokens_tracked tt
                JOIN (
                    SELECT DISTINCT token_id
                    FROM token_group_alerts
                    WHERE original_user_id = $1
                ) tga ON tga.token_id = tt.id
                WHERE tt.first_seen_mc > 0 AND tt.peak_mc > 0
                ORDER BY (tt.peak_mc / NULLIF(tt.first_seen_mc, 0)) DESC NULLS LAST
                LIMIT 1
                """,
                user_id,
            )

            avg_multiplier = await self.db.fetchval(
                """
                SELECT AVG(tt.peak_mc / NULLIF(tt.first_seen_mc, 0))
                FROM tokens_tracked tt
                JOIN (
                    SELECT DISTINCT token_id
                    FROM token_group_alerts
                    WHERE original_user_id = $1
                ) tga ON tga.token_id = tt.id
                WHERE tt.first_seen_mc > 0 AND tt.peak_mc > 0
                """,
                user_id,
            )

            recent_limit = 5
            recent_tokens = await self.db.fetch(
                """
                SELECT tga.chat_id, tga.created_at, tt.address, tt.ticker
                FROM token_group_alerts tga
                JOIN tokens_tracked tt ON tt.id = tga.token_id
                WHERE tga.original_user_id = $1
                ORDER BY tga.created_at DESC NULLS LAST, tga.id DESC
                LIMIT $2
                """,
                user_id,
                recent_limit,
            )

            chat_ids = [int(row["chat_id"]) for row in rows if row.get("chat_id") is not None]
            if last_token and last_token.get("chat_id"):
                chat_ids.append(int(last_token.get("chat_id")))
            chat_ids.extend([int(row["chat_id"]) for row in recent_tokens if row.get("chat_id") is not None])
            unique_chat_ids = list(dict.fromkeys(chat_ids))
            db_chat_names = await self._resolve_db_chat_names(unique_chat_ids)
            chat_titles = await self._resolve_chat_titles(message.bot, unique_chat_ids)

            user_display = await self._resolve_user_display_name(message.bot, None, user_id)

            lines = [
                "ℹ️ <b>DB Info</b>",
                "",
                f"• User: {self._format_name_with_id(user_display, user_id)}",
                f"• Total calls: {total_calls}",
                f"• Unique chats: {unique_chats}",
                f"• Unique tokens: {unique_tokens}",
            ]

            if last_token:
                ticker = last_token.get("ticker") or last_token.get("address")
                chat_id_val = int(last_token.get("chat_id"))
                chat_name = db_chat_names.get(chat_id_val) or chat_titles.get(chat_id_val) or str(chat_id_val)
                lines.append(f"• Last token: {html.escape(str(ticker))}")
                lines.append(f"• Last chat: {self._format_name_with_id(chat_name, chat_id_val)}")
                lines.append(f"• Last time: {html.escape(str(last_token.get('created_at')))}")

            if best_token:
                mult = 0.0
                first_seen = best_token.get("first_seen_mc") or 0
                peak = best_token.get("peak_mc") or 0
                if first_seen:
                    try:
                        mult = float(peak) / float(first_seen)
                    except (TypeError, ValueError, ZeroDivisionError):
                        mult = 0.0
                ticker = best_token.get("ticker") or best_token.get("address")
                lines.append(f"• Best multiplier: {mult:.2f}x ({html.escape(str(ticker))})")

            if avg_multiplier is not None:
                try:
                    avg_val = float(avg_multiplier)
                except (TypeError, ValueError):
                    avg_val = 0.0
                lines.append(f"• Avg peak multiplier: {avg_val:.2f}x")

            if rows:
                lines.append("")
                lines.append("<b>Top chats</b>")
                for row in rows:
                    chat_id_val = int(row["chat_id"])
                    chat_name = db_chat_names.get(chat_id_val) or chat_titles.get(chat_id_val) or str(chat_id_val)
                    lines.append(
                        f"• {self._format_name_with_id(chat_name, chat_id_val)} – {row['token_count']} token(s)"
                    )
            else:
                lines.append("")
                lines.append("No tracked calls yet.")

            if recent_tokens:
                lines.append("")
                lines.append(f"<b>Recent tokens (last {recent_limit})</b>")
                for row in recent_tokens:
                    ticker = row.get("ticker") or row.get("address")
                    chat_id_val = int(row["chat_id"])
                    chat_name = db_chat_names.get(chat_id_val) or chat_titles.get(chat_id_val) or str(chat_id_val)
                    lines.append(
                        f"• {html.escape(str(ticker))} – {self._format_name_with_id(chat_name, chat_id_val)}"
                    )

            await message.answer("\n".join(lines), parse_mode="HTML")
        except Exception as exc:
            logger.error("Error building DB info for user %s: %s", user_id, exc, exc_info=True)
            await message.answer("❌ Failed to load DB info", parse_mode="HTML")

    async def _resolve_chat_titles(self, bot: Bot, chat_ids: List[int]) -> Dict[int, str]:
        results: Dict[int, str] = {}
        to_fetch: List[int] = []

        for chat_id in chat_ids:
            cached = self._chat_title_cache.get(chat_id)
            if cached is not None:
                results[chat_id] = cached
            else:
                to_fetch.append(chat_id)

        if to_fetch:
            tasks = [self._fetch_chat_title(bot, chat_id) for chat_id in to_fetch]
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for chat_id, value in zip(to_fetch, fetched):
                if isinstance(value, Exception):
                    title = str(chat_id)
                else:
                    title = value
                results[chat_id] = title
                self._chat_title_cache[chat_id] = title

        return results

    async def _resolve_db_chat_names(self, chat_ids: List[int]) -> Dict[int, str]:
        if not chat_ids:
            return {}

        rows = await self.db.fetch(
            """
            SELECT chat_id, display_name
            FROM monitored_sources
            WHERE chat_id = ANY($1::BIGINT[])
              AND display_name IS NOT NULL
            """,
            chat_ids,
        )

        results: Dict[int, str] = {}
        for row in rows:
            chat_id = int(row.get("chat_id") or 0)
            display_name = row.get("display_name")
            if display_name:
                results[chat_id] = display_name
        return results

    def _format_name_with_id(self, name: Optional[str], entity_id: int) -> str:
        if not name or str(name) == str(entity_id):
            return f"<code>{entity_id}</code>"
        return f"{html.escape(str(name))} (<code>{entity_id}</code>)"

    async def _fetch_chat_title(self, bot: Bot, chat_id: int) -> str:
        try:
            chat = await bot.get_chat(chat_id)
        except TelegramBadRequest:
            return str(chat_id)

        title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
        if title:
            return title
        username = getattr(chat, "username", None)
        if username:
            return f"@{username}"
        return str(chat_id)

    async def _resolve_user_display_names(self, bot: Bot, chat_id: int, user_ids: List[int]) -> Dict[int, str]:
        if not user_ids:
            return {}

        unique_ids = list(dict.fromkeys(user_ids))
        results: Dict[int, str] = {}
        to_fetch: List[int] = []

        for user_id in unique_ids:
            cache_key = (chat_id, user_id)
            cached = self._member_display_cache.get(cache_key)
            if cached is not None:
                results[user_id] = cached
            else:
                to_fetch.append(user_id)

        if to_fetch:
            tasks = [self._fetch_user_display(bot, chat_id, user_id) for user_id in to_fetch]
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for user_id, value in zip(to_fetch, fetched):
                if isinstance(value, Exception):
                    display = str(user_id)
                else:
                    display = value
                results[user_id] = display
                self._member_display_cache[(chat_id, user_id)] = display

        return results

    async def _resolve_user_display_name(self, bot: Bot, chat_id: Optional[int], user_id: int) -> str:
        if chat_id is not None:
            cached = self._member_display_cache.get((chat_id, user_id))
            if cached is not None:
                return cached

        cached_user = self._user_display_cache.get(user_id)
        if cached_user is not None:
            return cached_user

        display = await self._fetch_user_display(bot, chat_id, user_id)
        if chat_id is not None:
            self._member_display_cache[(chat_id, user_id)] = display
        self._user_display_cache[user_id] = display
        return display

    async def _fetch_user_display(self, bot: Bot, chat_id: Optional[int], user_id: int) -> str:
        if chat_id is not None:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                tg_user = member.user
                display_name = tg_user.full_name or tg_user.username or str(user_id)
                if tg_user.username:
                    display_name = f"{tg_user.full_name or tg_user.username} (@{tg_user.username})"
                return display_name
            except TelegramBadRequest:
                pass

        try:
            chat = await bot.get_chat(user_id)
        except TelegramBadRequest:
            return str(user_id)

        display_name = getattr(chat, "full_name", None) or getattr(chat, "title", None)
        username = getattr(chat, "username", None)
        if username:
            return f"{display_name or username} (@{username})"
        return display_name or str(user_id)
