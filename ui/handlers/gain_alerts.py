"""
Gain Alerts Handler - Admin UI for gain alert monitored sources.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from models import (
    AnalyticsModel,
    MonitoredSourceModel,
    SettingsModel,
    ChartRequestGroupModel,
)
from config import DEFAULT_GLOBAL_CHART_THRESHOLD
from ui.states import AdminStates
from ui.keyboards import Keyboards
from alerts.templates import DEFAULT_GAIN_ALERT_TEMPLATE, missing_required_placeholders, normalise_template
from ui.handlers.gain_alerts_chart import ChartAndSettingsMixin

logger = logging.getLogger(__name__)


class GainAlertsHandler(ChartAndSettingsMixin):
    """Handler for managing monitored sources used by the gain alert system."""

    def __init__(self, db_pool):
        self.db = db_pool
        self.model = MonitoredSourceModel(db_pool)
        self.analytics_model = AnalyticsModel(db_pool)
        self.settings_model = SettingsModel(db_pool)
        self.chart_groups = ChartRequestGroupModel(db_pool)
        self.keyboards = Keyboards()
        self._member_display_cache: Dict[tuple[int, int], str] = {}
        self._chart_bot_cache: Dict[int, Optional[str]] = {}

    async def show_main_menu(self, query: types.CallbackQuery, state: Optional[FSMContext] = None, page: int = 1) -> None:
        try:
            if state:
                await state.clear()

            sources = await self.model.get_all_with_stats()
            userbots = await self.model.list_available_userbots()
            userbot_lookup = {record["id"]: record["label"] for record in userbots}
            known_targets = await self.model.list_known_target_chats()
            target_lookup = {record["chat_id"]: record["label"] for record in known_targets}

            grouped = self._group_sources(sources)
            menu_entries = self._summaries_for_menu(grouped, userbot_lookup)
            page_size = 9
            total_pages = max(1, (len(menu_entries) + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            start = (page - 1) * page_size
            end = start + page_size
            paginated_entries = menu_entries[start:end]
            page_chat_ids = [entry["chat_id"] for entry in paginated_entries]
            text = self._format_sources_overview(
                grouped,
                userbot_lookup,
                target_lookup,
                page_chat_ids=page_chat_ids,
                page=page,
                total_pages=total_pages,
            )

            await query.message.edit_text(
                text,
                reply_markup=self.keyboards.gain_alerts_main_menu(
                    paginated_entries,
                    page=page,
                    total_pages=total_pages,
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Error showing gain alerts menu: %s", exc, exc_info=True)
            await query.answer("❌ Failed to load gain alerts", show_alert=True)

    async def show_chart_groups_menu(self, query: types.CallbackQuery, page: int = 1) -> None:
        try:
            groups = await self.chart_groups.list_all()
            page_size = 9
            total_pages = max(1, (len(groups) + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            start = (page - 1) * page_size
            end = start + page_size
            paginated_groups = groups[start:end]

            lines = [
                "<b>📊 Chart Request Groups</b>",
                "",
                "Groups where bot can post CA to fetch charts:",
                "",
            ]
            if total_pages > 1:
                lines.append(f"Page {page}/{total_pages}")
                lines.append("")

            if groups:
                for group in paginated_groups:
                    chat_id = group["chat_id"]
                    label = group.get("label")
                    if label:
                        lines.append(f"• Group <code>{chat_id}</code> ({label})")
                    else:
                        lines.append(f"• Group <code>{chat_id}</code>")
            else:
                lines.append("No chart request groups configured yet.")

            text = "\n".join(lines)
            keyboard = self.keyboards.chart_groups_menu(
                paginated_groups,
                page=page,
                total_pages=total_pages,
            )

            await query.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing chart groups menu: %s", exc, exc_info=True)
            await query.answer("❌ Failed to load chart groups menu", show_alert=True)

    async def start_add_chart_group_menu(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            await state.clear()
            await state.set_state(AdminStates.chart_groups_add_chat_id)

            prompt = (
                "<b>➕ Add Chart Request Group</b>\n\n"
                "Enter the Telegram group chat ID where the bot can post contract addresses "
                "to request charts.\n\n"
                "Chat ID must be a negative integer (e.g., <code>-1001234567890</code>).\n\n"
                "Use the cancel button to abort."
            )

            await query.message.edit_text(
                prompt,
                reply_markup=self.keyboards.cancel_button("gain_alerts:chart_groups:cancel"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting add chart group flow: %s", exc, exc_info=True)
            await query.answer("❌ Failed to start add chart group flow", show_alert=True)

    async def handle_chart_group_input(self, message: types.Message, state: FSMContext) -> None:
        try:
            raw_input = (message.text or "").strip()
            if not raw_input:
                await message.answer("❌ Please enter a valid chat ID.")
                return

            try:
                chat_id = int(raw_input)
            except ValueError:
                await message.answer("❌ Invalid chat ID. Please enter a numeric value.")
                return

            if chat_id >= 0:
                await message.answer("❌ Chat ID must be negative (e.g., -1001234567890).")
                return

            existing = await self.chart_groups.get_by_chat_id(chat_id)
            if existing:
                await message.answer("⚠️ This chat is already configured as a chart request group.")
                await state.clear()
                return

            added = await self.chart_groups.add_group(chat_id, label=None)
            if added:
                await message.answer(
                    f"✅ Chart request group added: <code>{chat_id}</code>",
                    parse_mode="HTML",
                )
            else:
                await message.answer("⚠️ This chat is already configured as a chart request group.")

            await state.clear()
        except Exception as exc:
            logger.error("Error handling chart group input: %s", exc, exc_info=True)
            await message.answer("❌ Failed to add chart request group. Please try again.")
            await state.clear()

    async def remove_chart_group(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            removed = await self.chart_groups.remove_by_chat(chat_id)

            if removed:
                await query.answer("✅ Chart request group removed.", show_alert=False)
            else:
                await query.answer("⚠️ Chart request group not found.", show_alert=True)

            await self.show_chart_groups_menu(query)
        except Exception as exc:
            logger.error("Error removing chart group %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to remove chart request group", show_alert=True)

    async def cancel_chart_groups(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await self.show_chart_groups_menu(query)

    async def start_add_flow(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await state.set_state(AdminStates.gain_alerts_add_type)
        text = (
            "<b>➕ Add Monitored Source</b>\n\n"
            "Choose the type of Telegram entity you want to monitor:\n\n"
            "📢 <b>Channel</b> – Track every post in a channel\n"
            "👥 <b>Group</b> – Track contract addresses from specific posters\n"
            "💬 <b>DM</b> – Track direct messages from a single account\n\n"
            "Select an option to continue."
        )
        await query.message.edit_text(
            text,
            reply_markup=self.keyboards.gain_alerts_type_selector(),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_type_selected(self, query: types.CallbackQuery, state: FSMContext, chat_type: str) -> None:
        await state.update_data(chat_type=chat_type, return_to_chat_id=None)
        await state.set_state(AdminStates.gain_alerts_add_chat_id)
        guidance = "Enter the Telegram chat ID (negative integer)." if chat_type in {"group", "channel"} else "Enter the DM user ID to monitor (positive integer)."
        prompt = (
            f"<b>➕ Add {self._chat_type_label(chat_type)}</b>\n\n"
            f"{guidance}\n\n"
            "Example: <code>-1001234567890</code>\n"
            "Use the cancel button to abort."
        )
        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_chat_id_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_type = data.get("chat_type")

        if not chat_type:
            await message.answer("❌ Type selection expired. Please start again.")
            await state.clear()
            return

        chat_id = self._parse_int(message.text)
        if chat_id is None:
            await message.answer("❌ Invalid chat ID. Please enter a numeric value.")
            return

        if chat_type in {"group", "channel"} and chat_id >= 0:
            await message.answer("❌ Chat IDs for groups/channels must be negative (e.g., -1001234567890).")
            return

        if chat_type == "dm" and chat_id <= 0:
            await message.answer("❌ DM user IDs must be positive integers.")
            return

        existing = await self.model.is_monitored(chat_id, None)
        if chat_type in {"channel", "dm"} and existing:
            await message.answer("⚠️ This chat is already monitored. Remove it first if you need to reconfigure.")
            await state.clear()
            return

        await state.update_data(chat_id=chat_id, return_to_chat_id=None, skipped_user_ids=[])

        if chat_type == "group":
            await state.set_state(AdminStates.gain_alerts_add_user_id)
            await message.answer(
                "<b>👥 Monitor Group Members</b>\n\n"
                "Enter one or more Telegram user IDs to monitor in this group.\n"
                "User IDs must be positive integers. Separate multiple IDs with commas or spaces.\n\n"
                "To monitor the entire group, reply with <code>all</code>.",
                reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            )
            await state.update_data(user_ids=[])
            return

        await state.update_data(user_id=None)
        await state.set_state(AdminStates.gain_alerts_confirm_add)
        await self._show_add_confirmation(message, state)

    async def handle_user_id_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        chat_type = data.get("chat_type")

        if not chat_id or chat_type != "group":
            await message.answer("❌ Session expired. Please restart the add flow.")
            await state.clear()
            return

        raw_input = (message.text or "").strip().lower()
        if raw_input in {"all", "*", "everyone", "any"}:
            existing_all = await self.model.is_monitored(chat_id, None)
            if existing_all and existing_all.get("chat_type") == "group":
                await message.answer("⚠️ This group is already tracking all users.")
                return
            await state.update_data(user_ids=[], skipped_user_ids=[], track_all_users=True)
            await state.set_state(AdminStates.gain_alerts_confirm_add)
            await self._show_add_confirmation(message, state)
            return

        parsed_ids = self._parse_int_list(message.text)
        if not parsed_ids:
            await message.answer("❌ Invalid user ID. Please enter positive integers separated by commas or spaces.")
            return

        invalid_ids = [uid for uid in parsed_ids if uid <= 0]
        if invalid_ids:
            formatted = ", ".join(str(uid) for uid in invalid_ids)
            await message.answer(f"❌ Invalid user ID(s): {formatted}. Please provide positive integers.")
            return

        unique_ids: List[int] = []
        seen_ids = set()
        for uid in parsed_ids:
            if uid not in seen_ids:
                unique_ids.append(uid)
                seen_ids.add(uid)

        existing_ids: List[int] = []
        new_ids: List[int] = []
        for uid in unique_ids:
            if await self.model.is_monitored(chat_id, uid):
                existing_ids.append(uid)
            else:
                new_ids.append(uid)

        if not new_ids:
            duplicates = ", ".join(str(uid) for uid in existing_ids)
            await message.answer(
                f"⚠️ All provided user IDs are already monitored: {duplicates}.\n"
                "Submit different user IDs or cancel the flow."
            )
            return

        await state.update_data(user_ids=new_ids, skipped_user_ids=existing_ids, track_all_users=False)
        await state.set_state(AdminStates.gain_alerts_confirm_add)
        await self._show_add_confirmation(message, state)

    async def confirm_add(self, query: types.CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        chat_type = data.get("chat_type")
        chat_id = data.get("chat_id")
        user_id = data.get("user_id")
        track_all_users = bool(data.get("track_all_users"))

        user_ids: List[Optional[int]] = []
        if chat_type == "group":
            stored_ids = data.get("user_ids")
            if track_all_users:
                user_ids = [None]
            elif stored_ids:
                user_ids = [int(uid) for uid in stored_ids]
            elif user_id is not None:
                user_ids = [int(user_id)]
            else:
                user_ids = []
        else:
            user_ids = [None]

        if chat_type is None or chat_id is None or (chat_type == "group" and not user_ids and not track_all_users):
            await query.answer("❌ Missing data. Please start again.", show_alert=True)
            await state.clear()
            return

        try:
            added_ids: List[Optional[int]] = []
            skipped_ids: List[Optional[int]] = []

            for uid in user_ids:
                try:
                    await self.model.add_source(
                        chat_id=chat_id,
                        chat_type=chat_type,
                        user_id=uid,
                        admin_id=query.from_user.id,
                    )
                    added_ids.append(uid)
                except Exception as exc:
                    # Unique violations or duplicates land here; treat as skipped.
                    logger.debug("Skipped monitored source for chat %s user %s: %s", chat_id, uid, exc)
                    skipped_ids.append(uid)

            if not added_ids:
                await query.answer("⚠️ This source is already monitored.", show_alert=True)
                await state.clear()
                return

            skip_note = ""
            if skipped_ids:
                formatted = ", ".join(str(uid) for uid in skipped_ids if uid is not None)
                if formatted:
                    skip_note = f" (skipped existing IDs: {formatted})"

            await query.answer(f"✅ Monitored source added{skip_note}", show_alert=bool(skip_note))
        except Exception as exc:
            logger.error("Failed to add monitored source: %s", exc, exc_info=True)
            await query.answer("❌ Failed to add monitored source", show_alert=True)
            await state.clear()
            return

        await state.clear()
        await self.show_main_menu(query, state=None)

    # ----------------- detail & overrides -----------------

    async def show_source_detail(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            context = await self._build_detail_context(chat_id, query.bot)
            if context is None:
                await self.show_main_menu(query, state=None)
                await query.answer("Monitored source not found.", show_alert=True)
                return

            await query.message.edit_text(
                context["text"],
                reply_markup=context["keyboard"],
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing gain alert source detail for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load source detail", show_alert=True)

    async def show_source_stats(self, query: types.CallbackQuery, chat_id: int, timeframe: str = "24h") -> None:
        """Show performance statistics for a monitored source."""
        try:
            from datetime import datetime, timedelta, timezone

            # Get source info
            sources = await self.model.get_by_chat(chat_id)
            source = sources[0] if sources else None
            if not source:
                await query.answer("Source not found.", show_alert=True)
                return

            source_id = source["id"]
            display_name = source.get("display_name", f"Chat {chat_id}")

            # Parse timeframe to timedelta
            timeframe_map = {
                "1h": timedelta(hours=1),
                "24h": timedelta(hours=24),
                "7d": timedelta(days=7),
                "30d": timedelta(days=30),
            }

            duration = timeframe_map.get(timeframe, timedelta(hours=24))
            end_time = datetime.now(timezone.utc)
            start_time = end_time - duration

            # Calculate stats
            stats = await self.analytics_model.calculate_source_stats(
                chat_id, None, start_time, end_time
            )

            # Format display
            text = self._format_source_stats(display_name, stats, timeframe)
            keyboard = self._build_stats_keyboard(chat_id, timeframe)

            await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await query.answer()

        except Exception as exc:
            logger.error("Error showing stats for source %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load stats", show_alert=True)

    async def cancel(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            data = await state.get_data()
            await state.clear()

            return_chat_id = data.get("return_to_chat_id")
            detail_chat_id = data.get("detail_chat_id")
            detail_message_id = data.get("detail_message_id")
            return_view = data.get("return_view")

            if return_chat_id:
                if return_view == "chart_settings":
                    await self.show_chart_settings(query, int(return_chat_id))
                    return
                if return_view == "tracked":
                    view = await self._build_tracked_users_view(query.bot, int(return_chat_id))
                    if view is not None and detail_chat_id is not None and detail_message_id is not None:
                        text, keyboard = view
                        try:
                            await query.bot.edit_message_text(
                                text=text,
                                chat_id=detail_chat_id,
                                message_id=detail_message_id,
                                reply_markup=keyboard,
                                parse_mode="HTML",
                            )
                            await query.answer()
                            return
                        except TelegramBadRequest:
                            pass
                await self.show_source_detail(query, int(return_chat_id))
                return

            await self.show_main_menu(query, state=None)
        except Exception as exc:
            logger.error("Error handling cancel: %s", exc, exc_info=True)
            await query.answer("❌ Failed to cancel", show_alert=True)
    async def toggle_source_enabled(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            new_status = not (records[0].get("is_enabled", True))
            for record in records:
                if record.get("id"):
                    await self.model.set_enabled(int(record["id"]), new_status)

            await self.show_source_detail(query, chat_id)
            await query.answer("Alerts enabled." if new_status else "Alerts disabled.")
        except Exception as exc:
            logger.error("Error toggling gain alert source %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to toggle alerts", show_alert=True)

    async def start_sensitivity_menu(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            entry = self._summarise_records(records)
            current_value = entry.get("sensitivity_pct")
            if current_value is not None:
                try:
                    percent_text = f"+{float(current_value) * 100:.0f}%"
                except (TypeError, ValueError):
                    percent_text = "<i>invalid</i>"
            else:
                percent_text = "Using global default"

            text = (
                "<b>🎯 Gain Sensitivity</b>\n\n"
                f"Current setting: {percent_text}\n\n"
                "Choose a preset below, set a custom percentage, or revert to the global default."
            )

            keyboard = self._build_sensitivity_menu_keyboard(chat_id)
            await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await query.answer()
        except Exception as exc:
            logger.error("Error showing sensitivity menu for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load sensitivity menu", show_alert=True)

    async def set_sensitivity_value(self, query: types.CallbackQuery, chat_id: int, raw_value: Optional[str]) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            record_ids = sorted({int(record["id"]) for record in records if record.get("id") is not None})
            if not record_ids:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            new_value: Optional[float]
            if raw_value in {None, "default", "clear"}:
                new_value = None
            else:
                try:
                    decimal_value = Decimal(raw_value)
                except (InvalidOperation, TypeError):
                    await query.answer("❌ Invalid sensitivity value", show_alert=True)
                    return

                if decimal_value <= 0:
                    await query.answer("❌ Sensitivity must be greater than 0", show_alert=True)
                    return

                if decimal_value > Decimal("5"):
                    await query.answer("❌ Sensitivity too high", show_alert=True)
                    return

                decimal_value = decimal_value.quantize(Decimal("0.00001"))
                new_value = float(decimal_value)

            for source_id in record_ids:
                await self.model.set_sensitivity(source_id, new_value)

            await self.show_source_detail(query, chat_id)

            if new_value is None:
                await query.answer("Sensitivity reset to default.")
            else:
                await query.answer(f"Sensitivity set to +{new_value * 100:.0f}%.")
        except Exception as exc:
            logger.error("Error setting sensitivity for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to update sensitivity", show_alert=True)

    async def toggle_sender(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            current = bool(records[0].get("use_management_bot"))
            new_value = not current
            await self.model.set_management_bot_for_chat(chat_id, new_value)
            await self.show_source_detail(query, chat_id)
            await query.answer("Sender switched to management bot." if new_value else "Sender switched to userbot pool.")
        except Exception as exc:
            logger.error("Error toggling sender for chat %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to toggle sender", show_alert=True)

    async def start_userbot_menu(self, query: types.CallbackQuery, chat_id: int, page: int = 1) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            entry = records[0]
            current_bot_id = entry.get("assigned_userbot_id")
            userbot_records_raw = await self.model.list_available_userbots()
            userbot_records = [dict(record) for record in userbot_records_raw]

            if entry.get("use_management_bot"):
                current_display = "Management bot"
            elif current_bot_id:
                current_label = next(
                    (record["label"] for record in userbot_records if record["id"] == current_bot_id),
                    None,
                )
                current_display = current_label or f"Userbot {current_bot_id}"
            else:
                current_display = "Not assigned"

            lines = [
                "<b>🤖 Choose Alert Sender</b>",
                "",
                f"Current sender: {current_display}",
                "",
            ]

            if userbot_records:
                lines.append(
                    "Select a sender below. Management bot posts via the admin bot; userbots post via Telethon workers."
                )
            else:
                lines.append(
                    "No userbots available. Add a userbot first from the main menu or use the management bot option above."
                )

            text = "\n".join(lines)
            keyboard = self._build_userbot_menu_keyboard(
                chat_id,
                userbot_records,
                current_bot_id,
                bool(entry.get("use_management_bot")),
                page,
            )

            await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await query.answer()
        except Exception as exc:
            logger.error("Error showing userbot menu for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load userbot menu", show_alert=True)

    async def set_userbot_assignment(self, query: types.CallbackQuery, chat_id: int, raw_userbot_id: Optional[str]) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            record_ids = [int(r["id"]) for r in records if r.get("id")]
            if not record_ids:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            if raw_userbot_id == "management":
                await self.model.set_management_bot_for_chat(chat_id, True)
                for source_id in record_ids:
                    await self.model.assign_userbot(source_id, None)
                await self.show_source_detail(query, chat_id)
                await query.answer("Using management bot for alerts.")
                return

            if raw_userbot_id in {None, "clear"}:
                target_userbot_id: Optional[int] = None
            else:
                try:
                    target_userbot_id = int(raw_userbot_id)
                except (TypeError, ValueError):
                    await query.answer("❌ Invalid userbot selection", show_alert=True)
                    return

            await self.model.set_management_bot_for_chat(chat_id, False)

            for source_id in record_ids:
                await self.model.assign_userbot(source_id, target_userbot_id)

            await self.show_source_detail(query, chat_id)

            if target_userbot_id is None:
                await query.answer("Sender cleared (pooled userbot).")
            else:
                await query.answer("Userbot assigned.")
        except Exception as exc:
            logger.error("Error assigning userbot for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to assign userbot", show_alert=True)

    async def start_tracking_userbot_menu(self, query: types.CallbackQuery, chat_id: int, page: int = 1) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            entry = records[0]
            current_tracking_id = entry.get("tracking_userbot_id")
            fallback_enabled = entry.get("tracking_fallback_enabled", True)
            userbot_records_raw = await self.model.list_available_userbots()
            userbot_records = [dict(record) for record in userbot_records_raw]

            if current_tracking_id:
                current_label = next(
                    (record["label"] for record in userbot_records if record["id"] == current_tracking_id),
                    None,
                )
                current_display = current_label or f"Userbot {current_tracking_id}"
            else:
                current_display = "Any available (pooled)"

            fallback_status = "enabled" if fallback_enabled else "disabled"

            lines = [
                "<b>📡 Choose Tracking Userbot</b>",
                "",
                f"Current tracker: {current_display}",
                f"Fallback: {fallback_status}",
                "",
                "Select which userbot monitors this channel for contract addresses.",
            ]

            text = "\n".join(lines)
            keyboard = self._build_tracking_userbot_keyboard(
                chat_id,
                userbot_records,
                current_tracking_id,
                fallback_enabled,
                page,
            )

            await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await query.answer()
        except Exception as exc:
            logger.error("Error showing tracking userbot menu for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load tracking menu", show_alert=True)

    async def set_tracking_userbot_assignment(self, query: types.CallbackQuery, chat_id: int, raw_userbot_id: Optional[str]) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            record_ids = [int(r["id"]) for r in records if r.get("id")]
            if not record_ids:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            if raw_userbot_id in {None, "clear", "any"}:
                target_userbot_id: Optional[int] = None
            else:
                try:
                    target_userbot_id = int(raw_userbot_id)
                except (TypeError, ValueError):
                    await query.answer("❌ Invalid userbot selection", show_alert=True)
                    return

            for source_id in record_ids:
                await self.model.assign_tracking_userbot(source_id, target_userbot_id)

            await self.show_source_detail(query, chat_id)

            if target_userbot_id is None:
                await query.answer("Tracking set to any available userbot.")
            else:
                await query.answer("Tracking userbot assigned.")
        except Exception as exc:
            logger.error("Error assigning tracking userbot for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to assign tracking userbot", show_alert=True)

    async def toggle_tracking_fallback(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            current = records[0].get("tracking_fallback_enabled", True)
            new_value = not current

            for record in records:
                if record.get("id"):
                    await self.model.set_tracking_fallback(int(record["id"]), new_value)

            await self.start_tracking_userbot_menu(query, chat_id)
            await query.answer("Fallback enabled." if new_value else "Fallback disabled.")
        except Exception as exc:
            logger.error("Error toggling tracking fallback for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to toggle fallback", show_alert=True)

    async def start_edit_name(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            record_ids = [int(r["id"]) for r in records if r.get("id")]
            current_name = records[0].get("display_name") or "—"

            await state.clear()
            await state.set_state(AdminStates.gain_alerts_edit_name)
            await state.update_data(
                chat_id=chat_id,
                record_ids=record_ids,
                detail_chat_id=query.message.chat.id,
                detail_message_id=query.message.message_id,
                return_to_chat_id=chat_id,
                return_view="detail",
            )

            prompt = (
                "<b>✏️ Set Display Name</b>\n\n"
                f"Current: <code>{current_name}</code>\n\n"
                "Send a new display name (2–64 chars) or <code>clear</code> to remove."
            )

            await query.message.edit_text(
                prompt,
                reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting gain alert name edit for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to start name editor", show_alert=True)

    async def handle_edit_name_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        record_ids: List[int] = data.get("record_ids") or []
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if not chat_id or not record_ids or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please restart the edit flow.")
            await state.clear()
            return

        raw_input = (message.text or "").strip()
        if not raw_input:
            await message.answer("❌ Display name cannot be empty. Send text or 'clear' to reset.")
            return

        clear_command = raw_input.lower() in {"clear", "none", "reset", "remove"}
        if clear_command:
            new_name: Optional[str] = None
        else:
            if len(raw_input) < 2 or len(raw_input) > 64 or "\n" in raw_input:
                await message.answer("❌ Display name must be 2–64 chars on one line.")
                return
            new_name = raw_input

        for source_id in record_ids:
            await self.model.set_display_name(source_id, new_name)

        await state.clear()
        confirmation = "✅ Display name cleared." if new_name is None else f"✅ Display name set to <b>{new_name}</b>."
        await message.answer(confirmation, parse_mode="HTML")
        await self._refresh_detail_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    async def start_sensitivity_custom(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            current_value = records[0].get("sensitivity_pct")
            if current_value is not None:
                try:
                    current_display = f"Current: +{float(current_value) * 100:.0f}%"
                except (TypeError, ValueError):
                    current_display = "Current: <i>invalid</i>"
            else:
                current_display = "Currently using global default"

            record_ids = [int(r["id"]) for r in records if r.get("id")]

            await state.clear()
            await state.set_state(AdminStates.gain_alerts_edit_sensitivity)
            await state.update_data(
                chat_id=chat_id,
                record_ids=record_ids,
                detail_chat_id=query.message.chat.id,
                detail_message_id=query.message.message_id,
                return_to_chat_id=chat_id,
                return_view="detail",
            )

            prompt = (
                "<b>🎯 Custom Sensitivity</b>\n\n"
                f"{current_display}\n\n"
                "Send a new gain increase percentage (e.g., <code>35</code> for +35%).\n"
                "Values must be between 1 and 500. Type <code>default</code> to reset."
            )

            await query.message.edit_text(
                prompt,
                reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting custom sensitivity editor for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to start sensitivity editor", show_alert=True)

    async def handle_edit_sensitivity_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        record_ids: List[int] = data.get("record_ids") or []
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if not chat_id or not record_ids or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please restart the sensitivity editor.")
            await state.clear()
            return

        raw_input = (message.text or "").strip().lower()
        if not raw_input:
            await message.answer("❌ Please provide a number or 'default'.")
            return

        if raw_input in {"default", "clear", "reset"}:
            new_value: Optional[float] = None
            percent_display = "default"
        else:
            normalized = raw_input.replace("%", "").replace("+", "")
            try:
                decimal_value = Decimal(normalized)
            except Exception:
                await message.answer("❌ Couldn't parse that number. Try again (e.g., 35 or 0.35).")
                return

            if decimal_value <= 0:
                await message.answer("❌ Sensitivity must be greater than 0.")
                return

            if decimal_value >= 1:
                if decimal_value > Decimal("500"):
                    await message.answer("❌ Sensitivity too high (max 500%).")
                    return
                decimal_value = (decimal_value / 100).quantize(Decimal("0.00001"))
            else:
                if decimal_value > Decimal("5"):
                    await message.answer("❌ Sensitivity too high (max 500%).")
                    return
                decimal_value = decimal_value.quantize(Decimal("0.00001"))

            new_value = float(decimal_value)
            percent_display = f"+{new_value * 100:.0f}%"

        for source_id in record_ids:
            await self.model.set_sensitivity(source_id, new_value)

        await state.clear()
        if new_value is None:
            await message.answer("✅ Sensitivity reset to global default.")
        else:
            await message.answer(f"✅ Sensitivity set to {percent_display}.")

        await self._refresh_detail_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    async def start_edit_template(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            record_ids = [int(r["id"]) for r in records if r.get("id")]
            current_override = records[0].get("template_text")
            global_template = await self.settings_model.get_gain_alert_template_text()

            await state.clear()
            await state.set_state(AdminStates.gain_alerts_edit_template)
            await state.update_data(
                chat_id=chat_id,
                record_ids=record_ids,
                detail_chat_id=query.message.chat.id,
                detail_message_id=query.message.message_id,
                return_to_chat_id=chat_id,
                return_view="detail",
            )

            placeholder_list = [
                "{gain_emoji}",
                "{token_symbol}",
                "{multiplier}",
                "{first_market_cap}",
                "{current_market_cap}",
                "{elapsed_time}",
                "{address}",
            ]
            placeholders_text = ", ".join(placeholder_list)

            template_preview = current_override or global_template or DEFAULT_GAIN_ALERT_TEMPLATE

            prompt_lines = [
                "<b>📝 Edit Gain Alert Template</b>",
                "",
                "Available placeholders:",
                f"<code>{placeholders_text}</code>",
                "",
                "Send the new template text exactly as you want it to appear.",
                "Type <code>reset</code> to remove the custom override and use the global template.",
                "",
                "<b>Current template:</b>",
                f"<code>{template_preview}</code>",
            ]

            await query.message.edit_text(
                "\n".join(prompt_lines),
                reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting template edit for chat %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to open template editor", show_alert=True)

    async def handle_edit_template_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if chat_id is None or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Template editor expired. Please open the source detail again.")
            await state.clear()
            return

        raw_input = message.text or ""
        command = raw_input.strip().lower()

        if not raw_input.strip():
            await message.answer("❌ Template cannot be empty. Include placeholders or type 'reset'.")
            return

        if command == "reset":
            try:
                await self.model.set_template_for_chat(int(chat_id), None)
            except Exception as exc:
                logger.error("Failed to reset template for chat %s: %s", chat_id, exc, exc_info=True)
                await message.answer("❌ Failed to reset template. Please try again.")
                return

            await message.answer("✅ Template reset to global default.")
        else:
            cleaned = normalise_template(raw_input)
            missing = missing_required_placeholders(cleaned)
            if missing:
                await message.answer(f"⚠️ Missing placeholders: {', '.join(sorted(missing))}")
                return
            try:
                await self.model.set_template_for_chat(int(chat_id), cleaned)
            except Exception as exc:
                logger.error("Failed to set template for chat %s: %s", chat_id, exc, exc_info=True)
                await message.answer("❌ Failed to save template. Please try again.")
                return

            await message.answer("✅ Template updated.")

        await state.clear()
        await self._refresh_detail_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    async def show_tracked_users(self, query: types.CallbackQuery, chat_id: int, page: int = 1) -> None:
        try:
            view = await self._build_tracked_users_view(query.bot, chat_id, page=page)
            if view is None:
                await query.answer("No tracked users.", show_alert=True)
                return
            text, keyboard = view
            await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            await query.answer()
        except Exception as exc:
            logger.error("Error showing tracked users for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load tracked users", show_alert=True)

    async def remove_user(self, query: types.CallbackQuery, source_id: int) -> None:
        try:
            record = await self.model.get_by_id(source_id)
            if not record:
                await query.answer("Monitored user not found.", show_alert=True)
                return

            chat_id = record["chat_id"]
            deleted = await self.model.remove_source(source_id)
            if not deleted:
                await query.answer("Monitored user already removed.", show_alert=True)
                return

            await query.answer("✅ Monitored user removed.", show_alert=False)
            await self.show_source_detail(query, chat_id)
        except Exception as exc:
            logger.error("Error removing monitored user %s: %s", source_id, exc, exc_info=True)
            await query.answer("❌ Failed to remove monitored user", show_alert=True)

    async def toggle_track_all_users(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            entry = self._summarise_records(records)
            if entry.get("chat_type") != "group":
                await query.answer("Track-all is only available for groups.", show_alert=True)
                return

            existing_all = next(
                (record for record in records if record.get("chat_type") == "group" and record.get("user_id") is None),
                None,
            )

            if existing_all:
                removed = await self.model.delete_source_row(existing_all["id"])
                if removed:
                    await query.answer("✅ Track-all disabled for this group.", show_alert=False)
                else:
                    await query.answer("⚠️ Track-all already disabled.", show_alert=True)
            else:
                new_record = await self.model.add_source(
                    chat_id=chat_id,
                    chat_type="group",
                    user_id=None,
                    admin_id=query.from_user.id,
                )
                if new_record and records:
                    base = records[0]
                    await self.model.update_source_fields(
                        new_record["id"],
                        display_name=base.get("display_name"),
                        is_enabled=base.get("is_enabled"),
                        sensitivity_pct=base.get("sensitivity_pct"),
                        assigned_userbot_id=base.get("assigned_userbot_id"),
                        template_text=base.get("template_text"),
                        use_management_bot=base.get("use_management_bot"),
                        chart_enabled=base.get("chart_enabled"),
                        chart_bot_id=base.get("chart_bot_id"),
                        chart_mc_threshold=base.get("chart_mc_threshold"),
                        chart_min_age_minutes=base.get("chart_min_age_minutes"),
                        chart_min_liquidity_usd=base.get("chart_min_liquidity_usd"),
                        chart_min_volume_usd=base.get("chart_min_volume_usd"),
                        chart_min_multiplier=base.get("chart_min_multiplier"),
                        chart_max_price_change_pct=base.get("chart_max_price_change_pct"),
                        chart_checks_required=base.get("chart_checks_required"),
                        tracking_userbot_id=base.get("tracking_userbot_id"),
                        tracking_fallback_enabled=base.get("tracking_fallback_enabled"),
                    )
                await query.answer("✅ Track-all enabled for this group.", show_alert=False)

            await self.show_source_detail(query, chat_id)
        except Exception as exc:
            logger.error("Error toggling track-all for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to toggle track-all", show_alert=True)

    async def toggle_user_exclusion(self, query: types.CallbackQuery, chat_id: int, user_id: int, page: int = 1) -> None:
        try:
            excluded = await self.model.is_user_excluded(chat_id, user_id)
            if excluded:
                await self.model.remove_exclusion(chat_id, user_id)
                await query.answer("✅ User re-included.", show_alert=False)
            else:
                await self.model.add_exclusion(chat_id, user_id)
                await query.answer("🚫 User excluded.", show_alert=False)
            await self.show_tracked_users(query, chat_id, page=page)
        except Exception as exc:
            logger.error("Error toggling exclusion for %s/%s: %s", chat_id, user_id, exc, exc_info=True)
            await query.answer("❌ Failed to update exclusion", show_alert=True)

    async def start_remove_chat(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            entry = self._summarise_records(records)
            lines = [
                "<b>⚠️ Delete Monitored Source</b>",
                f"Chat: <code>{chat_id}</code>",
                f"Type: {entry['chat_type']}",
                f"Tracked baselines: {entry['token_sum']}",
                "",
                "This removes every monitored entry for this chat and clears all gain alert history.",
                "<b>This action cannot be undone.</b>",
            ]

            await query.message.edit_text(
                "\n".join(lines),
                reply_markup=self.keyboards.confirm_delete(chat_id),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error preparing delete prompt for chat %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to open delete prompt", show_alert=True)

    async def confirm_remove_chat(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await self.show_main_menu(query, state=None)
                await query.answer("Monitored source already removed.", show_alert=True)
                return

            removed = 0
            for record in records:
                source_id = record.get("id")
                if source_id is None:
                    continue
                try:
                    deleted = await self.model.remove_source(int(source_id))
                except Exception as exc:
                    logger.error("Failed to remove monitored source %s for chat %s: %s", source_id, chat_id, exc, exc_info=True)
                    continue
                if deleted:
                    removed += 1

            await self.show_main_menu(query, state=None)
            if removed:
                await query.answer("✅ Monitored source removed.", show_alert=False)
            else:
                await query.answer("Monitored source already removed.", show_alert=True)
        except Exception as exc:
            logger.error("Error removing monitored chat %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to remove monitored source", show_alert=True)

    # ----------------- helper methods -----------------
    async def _show_add_confirmation(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_type = data.get("chat_type")
        chat_id = data.get("chat_id")
        user_ids = data.get("user_ids") or []
        skipped = data.get("skipped_user_ids") or []

        if chat_type == "group":
            if data.get("track_all_users"):
                user_block = "Scope: all group members"
            else:
                user_lines = []
                if user_ids:
                    user_lines.append("Users to add: " + ", ".join(str(uid) for uid in user_ids))
                if skipped:
                    user_lines.append("Skipped existing: " + ", ".join(str(uid) for uid in skipped))
                user_block = "\n".join(user_lines) if user_lines else "No users provided yet."
        else:
            user_block = "Scope: whole chat"

        text = (
            "<b>✅ Confirm Add</b>\n\n"
            f"Type: {self._chat_type_label(chat_type)}\n"
            f"Chat ID: <code>{chat_id}</code>\n"
            f"{user_block}"
        )

        await message.answer(
            text,
            reply_markup=self.keyboards.gain_alerts_add_confirm(),
            parse_mode="HTML",
        )

    def _chat_type_label(self, chat_type: str) -> str:
        return {"group": "Group", "channel": "Channel", "dm": "DM"}.get(chat_type, chat_type)

    def _chat_label(self, src: Dict[str, Any]) -> str:
        name = src.get("display_name")
        if name:
            return name
        chat_id = src.get("chat_id")
        ctype = src.get("chat_type") or "chat"
        return f"{ctype} {chat_id}"

    def _summarise_records(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        track_all_record = next(
            (r for r in records if r.get("chat_type") == "group" and r.get("user_id") is None),
            None,
        )
        token_sum = track_all_record.get("token_count") if track_all_record else records[0].get("token_count")
        entry = {
            "chat_id": records[0].get("chat_id"),
            "chat_type": records[0].get("chat_type"),
            "display_name": records[0].get("display_name"),
            "is_enabled": records[0].get("is_enabled", True),
            "sensitivity_pct": records[0].get("sensitivity_pct"),
            "has_sensitivity": records[0].get("sensitivity_pct") is not None,
            "template_text": records[0].get("template_text"),
            "has_template": bool(records[0].get("template_text")),
            "use_management_bot": records[0].get("use_management_bot") or False,
            "assigned_userbot_id": records[0].get("assigned_userbot_id"),
            "tracked_user_count": sum(1 for r in records if r.get("user_id") is not None),
            "token_sum": token_sum or 0,
            "chart_enabled": bool(records[0].get("chart_enabled")),
            "chart_mc_threshold": records[0].get("chart_mc_threshold"),
            "chart_bot_id": records[0].get("chart_bot_id"),
            "last_guardrail_result": records[0].get("last_guardrail_result"),
            "has_chart": True,
            "tracking_userbot_id": records[0].get("tracking_userbot_id"),
            "tracking_fallback_enabled": records[0].get("tracking_fallback_enabled", True),
        }
        entry["track_all_users"] = any(
            r.get("chat_type") == "group" and r.get("user_id") is None for r in records
        )
        entry["sensitivity_text"] = (
            f"+{float(entry['sensitivity_pct']) * 100:.0f}%" if entry["sensitivity_pct"] is not None else "Global"
        )
        entry["sender_label"] = "Management bot" if entry["use_management_bot"] else "Userbot (pooled)"
        return entry

    def _build_sensitivity_menu_keyboard(self, chat_id: int) -> InlineKeyboardMarkup:
        presets = [Decimal("0.20"), Decimal("0.40"), Decimal("0.60")]
        rows: List[List[InlineKeyboardButton]] = []

        for preset in presets:
            percent = int(preset * 100)
            value_str = format(preset.normalize(), "f")
            rows.append([
                InlineKeyboardButton(
                    text=f"+{percent}%",
                    callback_data=f"gain_alerts:view:sensitivity:set:{chat_id}:{value_str}",
                )
            ])

        rows.append([
            InlineKeyboardButton(
                text="♻️ Use Global Default",
                callback_data=f"gain_alerts:view:sensitivity:set:{chat_id}:default",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="✏️ Custom Percentage",
                callback_data=f"gain_alerts:view:sensitivity:custom:{chat_id}",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="🔙 Back to Detail",
                callback_data=f"gain_alerts:view:{chat_id}",
            )
        ])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _group_sources(self, sources: List[Dict[str, Any]]) -> OrderedDict[int, Dict[str, Any]]:
        grouped: OrderedDict[int, Dict[str, Any]] = OrderedDict()

        for row in sources or []:
            chat_id = int(row["chat_id"])
            entry = grouped.setdefault(chat_id, {
                "chat_id": chat_id,
                "chat_type": row["chat_type"],
                "records": [],
                "token_sum": 0,
                "track_all_users": False,
                "track_all_token_count": None,
                "target_count": 0,
                "target_chat_ids": [],
                "display_name": row.get("display_name"),
                "is_enabled": row.get("is_enabled", True),
                "sensitivity_pct": row.get("sensitivity_pct"),
                "assigned_userbot_id": row.get("assigned_userbot_id"),
                "tracking_userbot_id": row.get("tracking_userbot_id"),
                "tracking_fallback_enabled": row.get("tracking_fallback_enabled", True),
                "created_at": row.get("created_at"),
                "template_text": row.get("template_text"),
                "use_management_bot": bool(row.get("use_management_bot")) if row.get("use_management_bot") is not None else False,
                "chart_enabled": bool(row.get("chart_enabled")) if row.get("chart_enabled") is not None else False,
                "chart_bot_id": row.get("chart_bot_id"),
                "chart_mc_threshold": row.get("chart_mc_threshold"),
                "chart_min_age_minutes": row.get("chart_min_age_minutes"),
                "chart_min_liquidity_usd": row.get("chart_min_liquidity_usd"),
                "chart_min_volume_usd": row.get("chart_min_volume_usd"),
                "chart_min_multiplier": row.get("chart_min_multiplier"),
                "chart_max_price_change_pct": row.get("chart_max_price_change_pct"),
                "chart_checks_required": row.get("chart_checks_required"),
            })
            entry["records"].append(row)
            token_count = int(row.get("token_count") or 0)
            entry["token_sum"] += token_count
            if row.get("chat_type") == "group" and row.get("user_id") is None:
                entry["track_all_users"] = True
                entry["track_all_token_count"] = token_count

            if entry["display_name"] is None and row.get("display_name"):
                entry["display_name"] = row.get("display_name")
            if row.get("is_enabled") is not None:
                entry["is_enabled"] = bool(row.get("is_enabled"))
            if row.get("sensitivity_pct") is not None:
                entry["sensitivity_pct"] = row.get("sensitivity_pct")
            if row.get("assigned_userbot_id") is not None:
                entry["assigned_userbot_id"] = row.get("assigned_userbot_id")
            if row.get("tracking_userbot_id") is not None:
                entry["tracking_userbot_id"] = row.get("tracking_userbot_id")
            if row.get("tracking_fallback_enabled") is not None:
                entry["tracking_fallback_enabled"] = bool(row.get("tracking_fallback_enabled"))
            if row.get("created_at"):
                entry["created_at"] = row.get("created_at")
            if row.get("template_text"):
                entry["template_text"] = row.get("template_text")
            if row.get("use_management_bot") is not None:
                entry["use_management_bot"] = bool(row.get("use_management_bot"))
            if row.get("chart_enabled") is not None:
                entry["chart_enabled"] = bool(row.get("chart_enabled"))
            if "chart_bot_id" in row:
                entry["chart_bot_id"] = row.get("chart_bot_id")
            if "chart_mc_threshold" in row:
                entry["chart_mc_threshold"] = row.get("chart_mc_threshold")
            if row.get("chart_min_age_minutes") is not None:
                entry["chart_min_age_minutes"] = row.get("chart_min_age_minutes")
            if row.get("chart_min_liquidity_usd") is not None:
                entry["chart_min_liquidity_usd"] = row.get("chart_min_liquidity_usd")
            if row.get("chart_min_volume_usd") is not None:
                entry["chart_min_volume_usd"] = row.get("chart_min_volume_usd")
            if row.get("chart_min_multiplier") is not None:
                entry["chart_min_multiplier"] = row.get("chart_min_multiplier")
            if row.get("chart_max_price_change_pct") is not None:
                entry["chart_max_price_change_pct"] = row.get("chart_max_price_change_pct")
            if row.get("chart_checks_required") is not None:
                entry["chart_checks_required"] = row.get("chart_checks_required")

            if row.get("target_count") is not None:
                entry["target_count"] = int(row.get("target_count") or 0)

            targets = row.get("target_chat_ids") or []
            if targets:
                existing = set(entry["target_chat_ids"] or [])
                entry["target_chat_ids"] = sorted(existing.union(set(targets)))
                entry["target_count"] = len(entry["target_chat_ids"])

        for entry in grouped.values():
            if entry.get("track_all_users") and entry.get("track_all_token_count") is not None:
                entry["token_sum"] = entry["track_all_token_count"]

        return grouped

    def _summaries_for_menu(self, grouped: OrderedDict[int, Dict[str, Any]], userbot_lookup: Dict[int, str]) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for entry in grouped.values():
            user_count = sum(1 for record in entry["records"] if record.get("user_id") is not None)
            token_sum = entry.get("token_sum", 0)
            userbot_id = entry.get("assigned_userbot_id")
            userbot_label = userbot_lookup.get(userbot_id) if userbot_id else None
            sensitivity_pct = entry.get("sensitivity_pct")
            is_enabled = entry.get("is_enabled", True)
            use_management_bot = entry.get("use_management_bot", False)
            track_all_users = entry.get("track_all_users", False)

            status_icon = "🟢" if is_enabled else "⛔️"
            name = entry.get("display_name") or f"{entry['chat_type'].upper()} {entry['chat_id']}"

            meta_parts: List[str] = []
            if token_sum:
                meta_parts.append(f"{token_sum} tok")
            if entry["chat_type"] == "group":
                if track_all_users:
                    meta_parts.append("all users")
                else:
                    meta_parts.append(f"{user_count} user" + ("s" if user_count != 1 else ""))
            if use_management_bot:
                meta_parts.append("🛰 mgmt")
            elif userbot_label:
                meta_parts.append(f"🤖 {userbot_label}")
            if sensitivity_pct is not None:
                try:
                    pct_value = float(sensitivity_pct) * 100
                    meta_parts.append(f"+{pct_value:.0f}%")
                except (TypeError, ValueError):
                    pass

            button_text = f"{status_icon} {name}"
            if meta_parts:
                button_text = f"{button_text} | {' | '.join(meta_parts)}"

            entries.append({
                "chat_id": entry["chat_id"],
                "chat_type": entry["chat_type"],
                "token_sum": token_sum,
                "user_count": user_count,
                "userbot_label": userbot_label,
                "sensitivity_pct": sensitivity_pct,
                "is_enabled": is_enabled,
                "use_management_bot": use_management_bot,
                "track_all_users": track_all_users,
                "button_text": button_text[:64] if len(button_text) > 64 else button_text,
            })
        return entries

    def _format_sources_overview(
        self,
        grouped: OrderedDict[int, Dict[str, Any]],
        userbot_lookup: Dict[int, str],
        target_lookup: Dict[int, str],
        page_chat_ids: Optional[List[int]] = None,
        page: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> str:
        if not grouped:
            return (
                "<b>📈 Gain Alerts – Monitored Sources</b>\n\n"
                "No chats or users are being monitored yet.\n\n"
                "Add a monitored source to start triggering gain alerts when "
                "contract addresses appear in tracked conversations."
            )

        total_sources = sum(len(entry["records"]) for entry in grouped.values())
        total_tokens = sum(entry["token_sum"] for entry in grouped.values())
        disabled_count = sum(1 for entry in grouped.values() if not entry.get("is_enabled", True))

        lines = [
            "<b>📈 Gain Alerts – Monitored Sources</b>",
            "",
            f"Tracking {total_sources} source(s) across {total_tokens} token baseline(s):",
            "",
        ]
        if page is not None and total_pages is not None and total_pages > 1:
            lines.append(f"Page {page}/{total_pages}")
            lines.append("")
        if disabled_count:
            lines.append(f"⚠️ {disabled_count} source(s) currently disabled.")
            lines.append("")

        type_icons = {
            "group": "👥",
            "channel": "📢",
            "dm": "💬",
        }

        entries_to_show = []
        if page_chat_ids:
            for chat_id in page_chat_ids:
                if chat_id in grouped:
                    entries_to_show.append(grouped[chat_id])
        else:
            entries_to_show = list(grouped.values())

        for info in entries_to_show:
            chat_id = info["chat_id"]
            chat_type = info["chat_type"]
            is_enabled = info.get("is_enabled", True)
            icon = type_icons.get(chat_type, "❔")
            chat_label = self._chat_label({"chat_id": chat_id, "chat_type": chat_type})
            status = "✅ Enabled" if is_enabled else "⛔️ Disabled"
            name = info.get("display_name")
            if name:
                lines.append(f"{icon} {chat_label} — <b>{name}</b>")
            else:
                lines.append(f"{icon} {chat_label}")
            lines.append(f"  • {status}")

            sensitivity_pct = info.get("sensitivity_pct")
            if sensitivity_pct is not None:
                try:
                    pct_value = float(sensitivity_pct) * 100
                    lines.append(f"  • Gain sensitivity: +{pct_value:.0f}%")
                except (TypeError, ValueError):
                    pass

            userbot_id = info.get("assigned_userbot_id")
            if userbot_id:
                userbot_label = userbot_lookup.get(userbot_id, f"Userbot {userbot_id}")
                lines.append(f"  • Userbot: {userbot_label}")

            target_ids = info.get("target_chat_ids") or []
            if target_ids:
                target_display_parts = []
                for tid in target_ids[:5]:
                    label = target_lookup.get(tid, str(tid))
                    target_display_parts.append(label)
                target_display = ", ".join(target_display_parts)
                if len(target_ids) > 5:
                    target_display += f", +{len(target_ids) - 5} more"
                lines.append(f"  • Targets: {target_display}")

            for record in info["records"]:
                if chat_type == "group":
                    if record.get("user_id") is None:
                        lines.append(
                            f"  • All members – {record.get('token_count', 0)} token(s)"
                        )
                    else:
                        lines.append(
                            f"  • User {record['user_id']} – {record.get('token_count', 0)} token(s)"
                        )
                else:
                    lines.append(
                        f"  • All messages – {record.get('token_count', 0)} token(s)"
                    )
            lines.append("")

        lines.append("Use the buttons below to add or manage monitored sources.")
        return "\n".join(lines)

    async def _build_detail_context(self, source_chat_id: int, bot: Optional[Bot]) -> Optional[Dict[str, Any]]:
        records = await self.model.get_by_chat(source_chat_id)
        if not records:
            return None

        userbots = await self.model.list_available_userbots()
        userbot_lookup = {record["id"]: record["label"] for record in userbots}

        known_targets = await self.model.list_known_target_chats()
        target_lookup = {record["chat_id"]: record["label"] for record in known_targets}

        grouped = self._group_sources(records)
        entry = grouped.get(source_chat_id)
        if entry is None and grouped:
            entry = next(iter(grouped.values()))

        if entry is None:
            return None

        user_display_map: Dict[int, str] = {}
        if bot and entry.get("chat_type") == "group":
            user_ids = [int(record["user_id"]) for record in entry.get("records", []) if record.get("user_id") is not None]
            user_display_map = await self._resolve_user_display_names(bot, source_chat_id, user_ids)

        chart_bot_display = None
        chart_bot_id = entry.get("chart_bot_id")
        if bot and chart_bot_id:
            chart_bot_display = await self._resolve_chart_bot_display(bot, int(chart_bot_id))

        text = self._format_source_detail(
            entry,
            userbot_lookup,
            target_lookup,
            user_display_map,
            chart_bot_display,
        )
        keyboard = self._build_source_detail_keyboard(entry, userbot_lookup)

        return {
            "entry": entry,
            "text": text,
            "keyboard": keyboard,
            "userbot_lookup": userbot_lookup,
            "target_lookup": target_lookup,
            "user_display_map": user_display_map,
            "chart_bot_display": chart_bot_display,
        }

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
            fetch_tasks = [self._fetch_user_display(bot, chat_id, user_id) for user_id in to_fetch]
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for user_id, fetch_result in zip(to_fetch, fetch_results):
                if isinstance(fetch_result, Exception):
                    display = str(user_id)
                else:
                    display = fetch_result
                results[user_id] = display
                self._member_display_cache[(chat_id, user_id)] = display

        return results

    async def _fetch_user_display(self, bot: Bot, chat_id: int, user_id: int) -> str:
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
            display_name = chat.full_name or getattr(chat, "username", None) or str(user_id)
            username = getattr(chat, "username", None)
            if username:
                display_name = f"{chat.full_name or username} (@{username})"
            return display_name
        except TelegramBadRequest:
            return str(user_id)

    async def _resolve_chart_bot_display(self, bot: Bot, user_id: int) -> Optional[str]:
        cached = self._chart_bot_cache.get(user_id)
        if cached is not None:
            return cached

        try:
            chat = await bot.get_chat(user_id)
        except TelegramBadRequest as exc:
            logger.debug("Unable to resolve chart bot %s: %s", user_id, exc)
            self._chart_bot_cache[user_id] = None
            return None

        username = getattr(chat, "username", None)
        full_name = getattr(chat, "full_name", None)
        if username:
            display = f"@{username}"
        elif full_name:
            display = full_name
        else:
            display = str(user_id)

        self._chart_bot_cache[user_id] = display
        return display

    async def _build_tracked_users_view(
        self,
        bot: Optional[Bot],
        chat_id: int,
        page: int = 1,
    ) -> Optional[tuple[str, InlineKeyboardMarkup]]:
        if bot is None:
            return None

        context = await self._build_detail_context(chat_id, bot)
        if context is None:
            return None

        entry = context["entry"]
        if entry.get("chat_type") != "group":
            return None

        user_map = context.get("user_display_map") or {}
        records_raw = entry.get("records", [])
        records = [dict(record) for record in records_raw]

        lines = [
            "<b>👥 Tracked Users</b>",
            "",
        ]

        if entry.get("track_all_users"):
            lines.append("Tracking all members in this group.")
            page_size = 9
            page = max(1, page)
            total_users = await self.db.fetchval(
                """
                SELECT COUNT(DISTINCT original_user_id)
                FROM token_group_alerts
                WHERE chat_id = $1 AND original_user_id IS NOT NULL
                """,
                chat_id,
            ) or 0
            total_pages = max(1, (total_users + page_size - 1) // page_size)
            if page > total_pages:
                page = total_pages
            offset = (page - 1) * page_size

            rows = await self.db.fetch(
                """
                SELECT
                    tga.original_user_id AS user_id,
                    COUNT(*) AS token_count,
                    (mse.user_id IS NOT NULL) AS is_excluded
                FROM token_group_alerts tga
                LEFT JOIN monitored_source_exclusions mse
                    ON mse.chat_id = tga.chat_id
                   AND mse.user_id = tga.original_user_id
                WHERE tga.chat_id = $1 AND tga.original_user_id IS NOT NULL
                GROUP BY tga.original_user_id, mse.user_id
                ORDER BY token_count DESC
                LIMIT $2 OFFSET $3
                """,
                chat_id,
                page_size,
                offset,
            )

            excluded_count = await self.db.fetchval(
                """
                SELECT COUNT(*)
                FROM monitored_source_exclusions
                WHERE chat_id = $1
                """,
                chat_id,
            ) or 0

            lines.append(f"Excluded users: {excluded_count}")
            if total_users:
                start_idx = offset + 1
                end_idx = min(offset + page_size, total_users)
                lines.append(f"Showing {start_idx}-{end_idx} of {total_users}")

            if rows:
                lines.append("")
                lines.append("Top callers:")
                page_user_ids = [int(row.get("user_id") or 0) for row in rows]
                if page_user_ids:
                    user_map = await self._resolve_user_display_names(bot, chat_id, page_user_ids)
                for row in rows:
                    user_id = int(row.get("user_id") or 0)
                    token_count = int(row.get("token_count") or 0)
                    display = user_map.get(user_id, str(user_id))
                    display_safe = html.escape(display)
                    status_icon = "🚫" if row.get("is_excluded") else "✅"
                    lines.append(f"• {status_icon} {display_safe} <code>{user_id}</code> – {token_count} token(s)")
            else:
                lines.append("No calls recorded yet.")
        elif records:
            lines.append("Gain alerts will fire when these members post contract addresses:")
            for record in records:
                user_id = int(record.get("user_id") or 0)
                token_count = int(record.get("token_count") or 0)
                display = user_map.get(user_id, str(user_id))
                display_safe = html.escape(display)
                lines.append(f"• {display_safe} <code>{user_id}</code> – {token_count} token(s)")
        else:
            lines.append("No specific members are being tracked yet.")

        text = "\n".join(lines)
        if entry.get("track_all_users"):
            buttons: List[List[InlineKeyboardButton]] = []
            row_buffer: List[InlineKeyboardButton] = []
            for row in rows:
                user_id = int(row.get("user_id") or 0)
                display = user_map.get(user_id, str(user_id))
                label = display if len(display) <= 18 else display[:15] + "..."
                is_excluded = bool(row.get("is_excluded"))
                btn_text = f"{'✅ Include' if is_excluded else '🚫 Exclude'} {label}"
                row_buffer.append(
                    InlineKeyboardButton(
                        text=btn_text,
                        callback_data=f"gain_alerts:view:exclude_user:{chat_id}:{user_id}:page:{page}",
                    )
                )
                if len(row_buffer) == 2:
                    buttons.append(row_buffer)
                    row_buffer = []

            if row_buffer:
                buttons.append(row_buffer)

            if total_pages > 1:
                nav_row: List[InlineKeyboardButton] = []
                if page > 1:
                    nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"gain_alerts:view:users:{chat_id}:page:{page-1}"))
                nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
                if page < total_pages:
                    nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"gain_alerts:view:users:{chat_id}:page:{page+1}"))
                buttons.append(nav_row)

            buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"gain_alerts:view:{chat_id}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        else:
            keyboard = self.keyboards.tracked_users(records, chat_id)
        return text, keyboard

    def _format_source_detail(
        self,
        entry: Dict[str, Any],
        userbot_lookup: Dict[int, str],
        target_lookup: Dict[int, str],
        user_display_map: Optional[Dict[int, str]] = None,
        chart_bot_display: Optional[str] = None,
    ) -> str:
        _ = target_lookup
        chat_type = entry["chat_type"]
        chat_label = self._chat_label(entry)
        token_sum = entry.get("token_sum", 0)
        is_enabled = entry.get("is_enabled", True)
        display_name = entry.get("display_name")
        sensitivity_pct = entry.get("sensitivity_pct")
        userbot_id = entry.get("assigned_userbot_id")

        type_icons = {
            "group": "👥",
            "channel": "📢",
            "dm": "💬",
        }
        icon = type_icons.get(chat_type, "❔")

        lines: List[str] = [
            "<b>🌙 Gain Alerts – Source Detail</b>",
            "",
            f"{icon} {chat_label}",
        ]
        if display_name:
            lines.append(f"Alias: <b>{display_name}</b>")
        lines.append("")

        lines.append("<b>Status</b>")
        lines.append(f"• {'✅ Enabled' if is_enabled else '⛔️ Disabled'}")
        lines.append(f"• Tracked tokens: {token_sum}")
        lines.append("")

        lines.append("<b>Gain Settings</b>")
        if sensitivity_pct is not None:
            try:
                pct_value = float(sensitivity_pct) * 100
                lines.append(f"• Custom sensitivity: +{pct_value:.0f}%")
            except (TypeError, ValueError):
                lines.append("• Custom sensitivity: <i>invalid value</i>")
        else:
            lines.append("• Using global gain sensitivity")
        lines.append("")

        lines.append("<b>Sender</b>")
        if entry.get("use_management_bot"):
            lines.append("• Management bot")
        elif userbot_id:
            userbot_label = userbot_lookup.get(userbot_id, f"Userbot {userbot_id}")
            lines.append(f"• Userbot: {userbot_label}")
        else:
            lines.append("• Pooled userbot (first available)")
        lines.append("")

        chart_enabled = bool(entry.get("chart_enabled"))
        chart_bot_id = entry.get("chart_bot_id")
        chart_threshold = entry.get("chart_mc_threshold")

        lines.append("<b>Chart Alerts</b>")
        lines.append(f"• Status: {'✅ Enabled' if chart_enabled else '⛔️ Disabled'}")
        if chart_threshold is None:
            lines.append(f"• MC Threshold: {self._format_chart_threshold(DEFAULT_GLOBAL_CHART_THRESHOLD)} (default)")
        else:
            lines.append(f"• MC Threshold: {self._format_chart_threshold(chart_threshold)}")

        if chart_bot_id:
            bot_id_int = int(chart_bot_id)
            if chart_bot_display:
                lines.append(f"• Chart Bot: {chart_bot_display} (ID: {bot_id_int})")
            else:
                lines.append(f"• Chart Bot ID: {bot_id_int}")
        else:
            lines.append("• Chart Bot: Not configured")

        last_guardrail_result = entry.get("last_guardrail_result")
        if isinstance(last_guardrail_result, str):
            try:
                last_guardrail_result = json.loads(last_guardrail_result)
            except Exception:
                last_guardrail_result = None
        if last_guardrail_result:
            passed = last_guardrail_result.get("passed", False)
            checks_passed = last_guardrail_result.get("checks_passed", 0)
            total_checks = last_guardrail_result.get("total_checks", 0)
            lines.append(
                f"• Last Guardrail Eval: {'✅ PASS' if passed else '❌ FAIL'} ({checks_passed}/{total_checks} checks passed)"
            )
        else:
            lines.append("• Last Guardrail Eval: N/A (no evaluations yet)")
        lines.append("")

        template_text = entry.get("template_text")
        preview = html.escape(template_text) if template_text else None
        lines.append("<b>Alert Template</b>")
        if template_text:
            lines.append("• Custom override in use")
            lines.append("")
            lines.append("<b>Preview</b>")
            lines.append(f"<code>{preview}</code>")
        else:
            lines.append("• Using global template")
        lines.append("")

        if chat_type == "group":
            lines.append("<b>Monitored Users</b>")
            records = entry.get("records", [])
            if entry.get("track_all_users"):
                lines.append("• All members (tracking any CA in this group)")
                lines.append(
                    f"• Use <code>/stats {entry['chat_id']} user:&lt;id&gt;</code> for individual stats"
                )
            elif records:
                for record in records[:10]:
                    user_id = record.get("user_id")
                    if user_id is None:
                        continue
                    token_count = int(record.get("token_count") or 0)
                    display = user_display_map.get(user_id) if user_display_map else None
                    if not display:
                        display = str(user_id)
                    lines.append(f"• {display} <code>{user_id}</code> – {token_count} token(s)")
                filtered_count = sum(1 for record in records if record.get("user_id") is not None)
                if filtered_count > 10:
                    lines.append(f"• …and {filtered_count - 10} more")
            else:
                lines.append("• None configured yet")
            lines.append("")

        return "\n".join(lines)

    def _build_source_detail_keyboard(self, entry: Dict[str, Any], userbot_lookup: Dict[int, str]) -> InlineKeyboardMarkup:
        rows: List[List[InlineKeyboardButton]] = []
        chat_id = entry["chat_id"]
        chat_type = entry["chat_type"]
        is_enabled = entry.get("is_enabled", True)
        userbot_id = entry.get("assigned_userbot_id")
        userbot_label = userbot_lookup.get(userbot_id) if userbot_id else None
        use_management_bot = entry.get("use_management_bot", False)

        rows.append([
            InlineKeyboardButton(
                text="✏️ Edit Name",
                callback_data=f"gain_alerts:view:edit_name:{chat_id}",
            ),
            InlineKeyboardButton(
                text="⏸ Disable Alerts" if is_enabled else "▶️ Enable Alerts",
                callback_data=f"gain_alerts:view:toggle:{chat_id}",
            ),
        ])

        rows.append([
            InlineKeyboardButton(
                text="🎯 Edit Sensitivity",
                callback_data=f"gain_alerts:view:sensitivity:{chat_id}",
            )
        ])

        rows.append([
            InlineKeyboardButton(
                text="📝 Edit Template",
                callback_data=f"gain_alerts:view:template:{chat_id}",
            )
        ])

        rows.append([
            InlineKeyboardButton(
                text="📊 Chart Settings",
                callback_data=f"gain_alerts:view:chart:{chat_id}",
            )
        ])

        rows.append([
            InlineKeyboardButton(
                text="📈 Stats",
                callback_data=f"gain_alerts:view:stats:{chat_id}",
            )
        ])

        if use_management_bot:
            sender_label = "🛰 Sender: Management Bot"
        elif userbot_label:
            sender_label = f"🤖 Sender: {userbot_label}"
        else:
            sender_label = "🤖 Assign Sender"

        rows.append([
            InlineKeyboardButton(
                text=sender_label,
                callback_data=f"gain_alerts:view:userbot:{chat_id}",
            )
        ])

        tracking_userbot_id = entry.get("tracking_userbot_id")
        tracking_label = userbot_lookup.get(tracking_userbot_id) if tracking_userbot_id else None
        if tracking_label:
            tracker_text = f"📡 Tracker: {tracking_label}"
        else:
            tracker_text = "📡 Tracker: Any (pooled)"

        rows.append([
            InlineKeyboardButton(
                text=tracker_text,
                callback_data=f"gain_alerts:view:tracking:{chat_id}",
            )
        ])

        if chat_type == "group":
            track_all_users = entry.get("track_all_users", False)
            toggle_text = "👥 Track All Users: ON" if track_all_users else "👥 Track All Users: OFF"
            rows.append([
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"gain_alerts:view:track_all:{chat_id}",
                )
            ])

        if chat_type == "group":
            rows.append([
                InlineKeyboardButton(
                    text="👥 View Tracked Users",
                    callback_data=f"gain_alerts:view:users:{chat_id}",
                )
            ])

        rows.append([
            InlineKeyboardButton(
                text="🗑️ Delete Source",
                callback_data=f"gain_alerts:view:remove_chat:{chat_id}",
            )
        ])

        rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="gain_alerts:menu")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _format_source_stats(self, display_name: str, stats: Dict[str, Any], timeframe: str) -> str:
        """Format source statistics as HTML text."""
        total_calls = stats["total_calls"]

        if total_calls == 0:
            return (
                f"📈 <b>Stats for {html.escape(display_name)}</b>\n"
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
            f"📈 <b>Stats for {html.escape(display_name)}</b>\n"
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

    def _build_stats_keyboard(self, chat_id: int, current_timeframe: str) -> InlineKeyboardMarkup:
        """Build keyboard for stats view with timeframe selection."""
        rows: List[List[InlineKeyboardButton]] = []

        # Timeframe buttons
        timeframes = [
            ("1h", "1h"),
            ("24h", "24h"),
            ("7d", "7d"),
            ("30d", "30d"),
        ]

        timeframe_row = []
        for label, tf in timeframes:
            prefix = "✅ " if tf == current_timeframe else ""
            timeframe_row.append(
                InlineKeyboardButton(
                    text=f"{prefix}{label}",
                    callback_data=f"gain_alerts:view:stats:{chat_id}:{tf}",
                )
            )

        rows.append(timeframe_row[:2])  # First 2 buttons
        rows.append(timeframe_row[2:])  # Last 2 buttons

        # Back button
        rows.append([
            InlineKeyboardButton(
                text="🔙 Back to Source",
                callback_data=f"gain_alerts:view:detail:{chat_id}",
            )
        ])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _build_userbot_menu_keyboard(
        self,
        chat_id: int,
        userbots: List[Dict[str, Any]],
        current_bot_id: Optional[int],
        use_management_bot: bool,
        page: int,
    ) -> InlineKeyboardMarkup:
        rows: List[List[InlineKeyboardButton]] = []

        total_userbots = len(userbots)
        page_size = 9
        total_pages = max(1, (total_userbots + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        mgmt_prefix = "✅" if use_management_bot else "🛰"
        rows.append([
            InlineKeyboardButton(
                text=f"{mgmt_prefix} Management Bot",
                callback_data=f"gain_alerts:view:userbot:set:{chat_id}:management",
            )
        ])

        status_icons = {
            "active": "🟢",
            "running": "🟢",
            "idle": "🟡",
            "error": "🔴",
        }

        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        row_buffer: List[InlineKeyboardButton] = []
        for record in userbots[start_index:end_index]:
            bot_id = int(record.get("id"))
            label = record.get("label") or f"Userbot {bot_id}"
            status = (record.get("status") or "").lower()
            icon = status_icons.get(status, "⚪️")
            button_text = f"{icon} {label}"
            if not use_management_bot and current_bot_id == bot_id:
                button_text = f"✅ {label}"

            row_buffer.append(
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"gain_alerts:view:userbot:set:{chat_id}:{bot_id}",
                )
            )
            if len(row_buffer) == 2:
                rows.append(row_buffer)
                row_buffer = []

        if row_buffer:
            rows.append(row_buffer)

        if use_management_bot or current_bot_id:
            rows.append([
                InlineKeyboardButton(
                    text="♻️ Use pooled userbot",
                    callback_data=f"gain_alerts:view:userbot:set:{chat_id}:clear",
                )
            ])

        if total_pages > 1:
            nav_buttons: List[InlineKeyboardButton] = []
            if page > 1:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="⬅️ Prev",
                        callback_data=f"gain_alerts:view:userbot:page:{chat_id}:{page-1}",
                    )
                )
            nav_buttons.append(
                InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop")
            )
            if page < total_pages:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="Next ➡️",
                        callback_data=f"gain_alerts:view:userbot:page:{chat_id}:{page+1}",
                    )
                )
            rows.append(nav_buttons)

        rows.append([
            InlineKeyboardButton(text="🔙 Back to Detail", callback_data=f"gain_alerts:view:{chat_id}")
        ])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    def _build_tracking_userbot_keyboard(
        self,
        chat_id: int,
        userbots: List[Dict[str, Any]],
        current_tracking_id: Optional[int],
        fallback_enabled: bool,
        page: int,
    ) -> InlineKeyboardMarkup:
        rows: List[List[InlineKeyboardButton]] = []

        total_userbots = len(userbots)
        page_size = 9
        total_pages = max(1, (total_userbots + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))

        any_prefix = "✅" if current_tracking_id is None else "🔄"
        rows.append([
            InlineKeyboardButton(
                text=f"{any_prefix} Any available (pooled)",
                callback_data=f"gain_alerts:view:tracking:set:{chat_id}:any",
            )
        ])

        status_icons = {
            "active": "🟢",
            "running": "🟢",
            "idle": "🟡",
            "error": "🔴",
        }

        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        row_buffer: List[InlineKeyboardButton] = []
        for record in userbots[start_index:end_index]:
            bot_id = int(record.get("id"))
            label = record.get("label") or f"Userbot {bot_id}"
            status = (record.get("status") or "").lower()
            icon = status_icons.get(status, "⚪️")
            button_text = f"{icon} {label}"
            if current_tracking_id == bot_id:
                button_text = f"✅ {label}"

            row_buffer.append(
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"gain_alerts:view:tracking:set:{chat_id}:{bot_id}",
                )
            )
            if len(row_buffer) == 2:
                rows.append(row_buffer)
                row_buffer = []

        if row_buffer:
            rows.append(row_buffer)

        fallback_icon = "✅" if fallback_enabled else "⛔️"
        rows.append([
            InlineKeyboardButton(
                text=f"{fallback_icon} Fallback when offline",
                callback_data=f"gain_alerts:view:tracking:fallback:{chat_id}",
            )
        ])

        if total_pages > 1:
            nav_buttons: List[InlineKeyboardButton] = []
            if page > 1:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="⬅️ Prev",
                        callback_data=f"gain_alerts:view:tracking:page:{chat_id}:{page-1}",
                    )
                )
            nav_buttons.append(
                InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop")
            )
            if page < total_pages:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="Next ➡️",
                        callback_data=f"gain_alerts:view:tracking:page:{chat_id}:{page+1}",
                    )
                )
            rows.append(nav_buttons)

        rows.append([
            InlineKeyboardButton(text="🔙 Back to Detail", callback_data=f"gain_alerts:view:{chat_id}")
        ])

        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def _parse_int(value: Optional[str]) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_int_list(text: Optional[str]) -> List[int]:
        if not text:
            return []
        parts = text.replace(",", " ").split()
        result = []
        for part in parts:
            try:
                result.append(int(part))
            except ValueError:
                continue
        return result
