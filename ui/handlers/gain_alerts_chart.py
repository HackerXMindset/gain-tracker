"""
Chart and global settings mixin for GainAlertsHandler.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from alerts.templates import DEFAULT_GAIN_ALERT_TEMPLATE, missing_required_placeholders, normalise_template
from config import DEFAULT_CHART_GUARDRAILS, DEFAULT_GLOBAL_CHART_THRESHOLD, GAIN_THRESHOLD_DEFAULT_PCT
from ui.states import AdminStates

logger = logging.getLogger(__name__)


class ChartAndSettingsMixin:
    GUARDRAIL_METRICS = (
        "min_age_minutes",
        "min_liquidity_usd",
        "min_volume_usd",
        "min_multiplier",
        "max_price_change_pct",
        "checks_required",
    )
    # ----------------- chart settings -----------------

    async def show_chart_settings(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            rendered = await self._render_chart_settings_view(chat_id, bot=query.bot)
            if not rendered:
                await query.answer("Monitored source not found.", show_alert=True)
                return
            text, markup = rendered
            await query.message.edit_text(
                text,
                reply_markup=markup,
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing chart settings for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load chart settings", show_alert=True)

    async def toggle_chart_enabled(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return
            new_status = not bool(records[0].get("chart_enabled"))
            for record in records:
                if record.get("id"):
                    await self.model.update_source_fields(int(record["id"]), chart_enabled=new_status)
            await self.show_chart_settings(query, chat_id)
            await query.answer("Charts enabled." if new_status else "Charts disabled.")
        except Exception as exc:
            logger.error("Error toggling chart for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to toggle charts", show_alert=True)

    async def start_edit_chart_threshold(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            global_chart = await self.settings_model.get_global_chart_settings()
            global_threshold = global_chart["chart_threshold_override"] or global_chart["chart_threshold_default"]
            current_value = records[0].get("chart_mc_threshold") or global_threshold

            await state.clear()
            await state.set_state(AdminStates.gain_alerts_edit_chart_threshold)
            await state.update_data(
                chat_id=chat_id,
                detail_chat_id=query.message.chat.id,
                detail_message_id=query.message.message_id,
                return_view="chart_settings",
                return_to_chat_id=chat_id,
            )

            prompt = (
                "<b>📈 Chart MC Threshold</b>\n\n"
                f"Current: <code>{self._format_mc(current_value)}</code>\n"
                f"Global default: <code>{self._format_mc(global_threshold)}</code>\n\n"
                "Send a market cap value (USD) to require before fetching charts.\n"
                "Type <code>default</code> to inherit the global threshold."
            )

            await query.message.edit_text(
                prompt,
                reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting chart threshold edit for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to open chart threshold editor", show_alert=True)

    async def handle_edit_chart_threshold_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if chat_id is None or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please reopen chart settings.")
            await state.clear()
            return

        raw_value = (message.text or "").strip().lower()
        if not raw_value:
            await message.answer("❌ Provide a number or 'default'.")
            return

        if raw_value in {"default", "clear", "reset"}:
            new_value: Optional[float] = None
        else:
            normalized = raw_value.replace(",", "").replace("_", "")
            try:
                decimal_value = Decimal(normalized)
            except Exception:
                await message.answer("❌ Couldn't parse that number. Try again (e.g., 150000).")
                return

            if decimal_value <= 0:
                await message.answer("❌ Threshold must be greater than zero.")
                return
            new_value = float(decimal_value)

        records = await self.model.get_by_chat(int(chat_id))
        for record in records:
            if record.get("id"):
                await self.model.update_source_fields(int(record["id"]), chart_mc_threshold=new_value)

        await state.clear()
        await message.answer("✅ Chart threshold updated." if new_value is not None else "✅ Chart threshold reset to global default.")
        await self._refresh_chart_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    async def start_edit_chart_bot(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            global_chart = await self.settings_model.get_global_chart_settings()
            current_value = records[0].get("chart_bot_id") or global_chart.get("chart_bot_id")

            await state.clear()
            await state.set_state(AdminStates.gain_alerts_edit_chart_bot)
            await state.update_data(
                chat_id=chat_id,
                detail_chat_id=query.message.chat.id,
                detail_message_id=query.message.message_id,
                return_view="chart_settings",
                return_to_chat_id=chat_id,
            )

            prompt = (
                "<b>🤖 Chart Bot ID</b>\n\n"
                f"Current: <code>{current_value or 'not set'}</code>\n\n"
                "Send the Telegram user ID of the chart bot to listen for.\n"
                "Type <code>clear</code> to inherit the global value."
            )

            await query.message.edit_text(
                prompt,
                reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting chart bot edit for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to open chart bot editor", show_alert=True)

    async def handle_edit_chart_bot_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if chat_id is None or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please reopen chart settings.")
            await state.clear()
            return

        raw_value = (message.text or "").strip().lower()
        if not raw_value:
            await message.answer("❌ Provide a bot user ID or 'clear'.")
            return

        if raw_value in {"clear", "default", "reset"}:
            new_value: Optional[int] = None
        else:
            bot_id = self._parse_int(raw_value)
            if bot_id is None or bot_id <= 0:
                await message.answer("❌ Bot ID must be a positive integer.")
                return
            new_value = bot_id

        records = await self.model.get_by_chat(int(chat_id))
        for record in records:
            if record.get("id"):
                await self.model.update_source_fields(int(record["id"]), chart_bot_id=new_value)

        await state.clear()
        await message.answer("✅ Chart bot updated." if new_value is not None else "✅ Chart bot reset to global default.")
        await self._refresh_chart_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    async def cancel_chart_settings(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        await state.clear()
        await self.show_chart_settings(query, chat_id)

    async def prompt_edit_source_guardrail(self, query: types.CallbackQuery, state: FSMContext, chat_id: int, metric: str) -> None:
        try:
            records = await self.model.get_by_chat(chat_id)
            if not records:
                await query.answer("Monitored source not found.", show_alert=True)
                return

            entry = dict(records[0])

            current_override = entry.get(f"chart_{metric}")
            global_guardrails = await self.settings_model.get_chart_guardrails()
            global_value = global_guardrails.get(metric, 0)

            if metric == "min_age_minutes":
                current_val = int(current_override) if current_override is not None else int(global_value)
                override_note = " <i>(override)</i>" if current_override is not None else " <i>(global)</i>"
                prompt = (
                    "Enter new minimum age in minutes (e.g., 30 for 30 minutes):\n\n"
                    f"Current: {current_val} minutes{override_note}"
                )
            elif metric == "min_liquidity_usd":
                current_val = current_override if current_override is not None else global_value
                override_note = " <i>(override)</i>" if current_override is not None else " <i>(global)</i>"
                prompt = (
                    "Enter new minimum liquidity in USD (e.g., 5000 for $5,000):\n\n"
                    f"Current: {self._format_guardrail_currency(current_val)}{override_note}"
                )
            elif metric == "min_volume_usd":
                current_val = current_override if current_override is not None else global_value
                override_note = " <i>(override)</i>" if current_override is not None else " <i>(global)</i>"
                prompt = (
                    "Enter new minimum 24h volume in USD (e.g., 10000 for $10,000):\n\n"
                    f"Current: {self._format_guardrail_currency(current_val)}{override_note}"
                )
            elif metric == "min_multiplier":
                current_val = current_override if current_override is not None else global_value
                override_note = " <i>(override)</i>" if current_override is not None else " <i>(global)</i>"
                prompt = (
                    "Enter new minimum multiplier (e.g., 1.5 for 1.5x):\n\n"
                    f"Current: x{current_val:.2f}{override_note}"
                )
            elif metric == "max_price_change_pct":
                current_val = current_override if current_override is not None else global_value
                override_note = " <i>(override)</i>" if current_override is not None else " <i>(global)</i>"
                prompt = (
                    "Enter new max price change percentage (e.g., 50 for 50%):\n\n"
                    f"Current: {current_val:.1f}%{override_note}"
                )
            elif metric == "checks_required":
                total_checks = len(self.GUARDRAIL_METRICS)
                current_val = int(current_override) if current_override is not None else int(global_value)
                override_note = " <i>(override)</i>" if current_override is not None else " <i>(global)</i>"
                prompt = (
                    f"Enter how many checks must pass (1 to {total_checks}):\n\n"
                    f"0 or {total_checks} = All must pass\n\n"
                    f"Current: {self._describe_guardrail_strategy(current_val, total_checks)}{override_note}"
                )
            else:
                await query.answer("Unknown metric.", show_alert=True)
                return

            await state.clear()
            await state.set_state(AdminStates.awaiting_source_guardrail_override)
            await state.update_data(
                chat_id=chat_id,
                metric=metric,
                detail_chat_id=query.message.chat.id,
                detail_message_id=query.message.message_id,
            )

            await query.message.edit_text(
                f"<b>📊 Edit Chart Guardrail Override</b>\n\n{prompt}\n\n<i>Type 'clear' to remove override</i>",
                reply_markup=self.keyboards.cancel_button(f"gain_alerts:chart_settings:cancel:{chat_id}"),
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error starting guardrail override editor for %s metric %s: %s", chat_id, metric, exc, exc_info=True)
            await query.answer("❌ Failed to start guardrail editor", show_alert=True)

    async def save_source_guardrail(self, message: types.Message, state: FSMContext) -> None:
        try:
            data = await state.get_data()
            chat_id = data.get("chat_id")
            metric = data.get("metric")

            if not chat_id or not metric:
                await message.answer("Error: Could not determine which setting to update.")
                await state.clear()
                return

            raw_value = message.text.strip() if message.text else ""

            if raw_value.lower() == "clear":
                await self.db.execute(
                    f"UPDATE monitored_sources SET chart_{metric} = NULL WHERE chat_id = $1",
                    chat_id,
                )
                await message.answer(f"✅ Guardrail '{metric.replace('_', ' ').title()}' override cleared.")
            else:
                if metric in ("min_age_minutes", "checks_required"):
                    value = int(raw_value)
                else:
                    value = float(raw_value.replace("$", "").replace(",", ""))

                await self.db.execute(
                    f"UPDATE monitored_sources SET chart_{metric} = $1 WHERE chat_id = $2",
                    value,
                    chat_id,
                )
                await message.answer(f"✅ Guardrail '{metric.replace('_', ' ').title()}' override updated.")

            await state.clear()

            detail_chat_id = data.get("detail_chat_id")
            detail_message_id = data.get("detail_message_id")
            if detail_chat_id and detail_message_id:
                await self._refresh_chart_settings_message(
                    message.bot,
                    detail_chat_id=detail_chat_id,
                    detail_message_id=detail_message_id,
                    source_chat_id=int(chat_id),
                )

        except (ValueError, TypeError):
            await message.answer("❌ Invalid input. Please enter a valid number.")
        except Exception as exc:
            logger.error("Error saving guardrail override: %s", exc, exc_info=True)
            await message.answer("❌ Error saving setting.")

    async def reset_source_guardrail(self, query: types.CallbackQuery, chat_id: int, metric: str) -> None:
        try:
            await self.db.execute(
                f"UPDATE monitored_sources SET chart_{metric} = NULL WHERE chat_id = $1",
                chat_id,
            )

            await query.answer("✅ Override cleared", show_alert=False)
            await self.show_chart_settings(query, chat_id)
        except Exception as exc:
            logger.error("Error resetting guardrail override for %s metric %s: %s", chat_id, metric, exc, exc_info=True)
            await query.answer("❌ Failed to reset override", show_alert=True)

    async def show_chart_groups(self, query: types.CallbackQuery, chat_id: int) -> None:
        try:
            rendered = await self._render_chart_groups_view(chat_id)
            if not rendered:
                await query.answer("No chart groups configured yet.")
                return
            text, markup = rendered
            await query.message.edit_text(
                text,
                reply_markup=markup,
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing chart groups for %s: %s", chat_id, exc, exc_info=True)
            await query.answer("❌ Failed to load chart groups", show_alert=True)

    async def start_add_chart_group(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        await state.clear()
        await state.set_state(AdminStates.gain_alerts_add_chart_group)
        await state.update_data(
            chat_id=chat_id,
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
        )

        prompt = (
            "<b>➕ Add Chart Request Group</b>\n\n"
            "Send the Telegram chat ID of a group where chart bot replies are available.\n"
            "Chat IDs must be negative (e.g., <code>-1001234567890</code>)."
        )

        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_add_chart_group_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if chat_id is None or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please reopen chart groups.")
            await state.clear()
            return

        group_chat_id = self._parse_int(message.text)
        if group_chat_id is None or group_chat_id >= 0:
            await message.answer("❌ Chart request group IDs must be negative integers.")
            return

        added = await self.chart_groups.add_group(group_chat_id)
        if added:
            await message.answer(f"✅ Added chart request group <code>{group_chat_id}</code>.", parse_mode="HTML")
        else:
            await message.answer("⚠️ Group already exists.")

        await state.clear()
        await self._refresh_chart_groups_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    async def start_remove_chart_group(self, query: types.CallbackQuery, state: FSMContext, chat_id: int) -> None:
        await state.clear()
        await state.set_state(AdminStates.gain_alerts_remove_chart_group)
        await state.update_data(
            chat_id=chat_id,
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
        )

        prompt = (
            "<b>❌ Remove Chart Request Group</b>\n\n"
            "Send the chat ID of the chart request group to remove."
        )

        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_remove_chart_group_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if chat_id is None or detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please reopen chart groups.")
            await state.clear()
            return

        group_chat_id = self._parse_int(message.text)
        if group_chat_id is None:
            await message.answer("❌ Invalid chat ID. Provide a numeric value.")
            return

        removed = await self.chart_groups.remove_by_chat(group_chat_id)
        if removed:
            await message.answer(f"✅ Removed chart group <code>{group_chat_id}</code>.", parse_mode="HTML")
        else:
            await message.answer("⚠️ Group not found.")

        await state.clear()
        await self._refresh_chart_groups_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
            source_chat_id=int(chat_id),
        )

    # ----------------- global settings -----------------

    async def show_global_settings(self, query: types.CallbackQuery) -> None:
        try:
            rendered = await self._render_global_settings_view()
            if not rendered:
                await query.answer("Failed to load settings.", show_alert=True)
                return
            text, markup = rendered
            await query.message.edit_text(
                text,
                reply_markup=markup,
                parse_mode="HTML",
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing global settings: %s", exc, exc_info=True)
            await query.answer("❌ Failed to load settings", show_alert=True)

    async def start_edit_gain_threshold(self, query: types.CallbackQuery, state: FSMContext) -> None:
        gain_settings = await self.settings_model.get_gain_alert_settings()
        current_threshold = gain_settings.get("gain_threshold_pct") or GAIN_THRESHOLD_DEFAULT_PCT

        await state.clear()
        await state.set_state(AdminStates.awaiting_gain_threshold)
        await state.update_data(
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
        )

        prompt = (
            "<b>🎯 Global Gain Threshold</b>\n\n"
            f"Current: <code>+{float(current_threshold) * 100:.0f}%</code>\n"
            f"Default: <code>+{float(GAIN_THRESHOLD_DEFAULT_PCT) * 100:.0f}%</code>\n\n"
            "Send a percentage (e.g., <code>30</code> or <code>0.3</code>). Values over 1 are treated as percentages.\n"
            "Type <code>default</code> to reset."
        )

        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_gain_threshold_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Session expired. Please reopen settings.")
            await state.clear()
            return

        raw_value = (message.text or "").strip().lower()
        if not raw_value:
            await message.answer("❌ Provide a number or 'default'.")
            return

        if raw_value in {"default", "reset"}:
            new_value = GAIN_THRESHOLD_DEFAULT_PCT
        else:
            normalized = raw_value.replace("%", "").replace("+", "")
            try:
                decimal_value = Decimal(normalized)
            except Exception:
                await message.answer("❌ Couldn't parse that number. Try again (e.g., 30).")
                return

            if decimal_value <= 0:
                await message.answer("❌ Threshold must be greater than zero.")
                return

            if decimal_value >= 1:
                if decimal_value > Decimal("500"):
                    await message.answer("❌ Threshold too high (max 500%).")
                    return
                decimal_value = (decimal_value / 100).quantize(Decimal("0.00001"))
            else:
                if decimal_value > Decimal("5"):
                    await message.answer("❌ Threshold too high (max 500%).")
                    return
                decimal_value = decimal_value.quantize(Decimal("0.00001"))
            new_value = float(decimal_value)

        await self.settings_model.set_gain_threshold_pct(new_value)
        await state.clear()
        await message.answer(f"✅ Gain threshold set to +{new_value * 100:.0f}%.")
        await self._refresh_global_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
        )

    async def start_edit_gain_template(self, query: types.CallbackQuery, state: FSMContext) -> None:
        current_template = await self.settings_model.get_gain_alert_template_text()

        await state.clear()
        await state.set_state(AdminStates.awaiting_gain_template)
        await state.update_data(
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
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

        prompt_lines = [
            "<b>📝 Global Gain Alert Template</b>",
            "",
            "Available placeholders:",
            f"<code>{placeholders_text}</code>",
            "",
            "Send the new template text exactly as you want it to appear.",
            "Type <code>reset</code> to restore the default template.",
            "",
            "<b>Current template:</b>",
            f"<code>{current_template}</code>",
        ]

        await query.message.edit_text(
            "\n".join(prompt_lines),
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_gain_template_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Settings session expired. Please reopen settings.")
            await state.clear()
            return

        raw_input = message.text or ""
        command = raw_input.strip().lower()

        if not raw_input.strip():
            await message.answer("❌ Template cannot be empty. Include placeholders or type 'reset'.")
            return

        if command == "reset":
            cleaned = DEFAULT_GAIN_ALERT_TEMPLATE
        else:
            cleaned = normalise_template(raw_input)
            missing = missing_required_placeholders(cleaned)
            if missing:
                await message.answer(f"⚠️ Missing placeholders: {', '.join(sorted(missing))}")
                return

        await self.settings_model.set_gain_alert_template_text(cleaned)
        await state.clear()
        await message.answer("✅ Global template updated.")
        await self._refresh_global_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
        )

    async def start_edit_global_chart_threshold(self, query: types.CallbackQuery, state: FSMContext) -> None:
        settings = await self.settings_model.get_global_chart_settings()
        current_value = settings.get("chart_threshold_override") or settings.get("chart_threshold_default") or DEFAULT_GLOBAL_CHART_THRESHOLD

        await state.clear()
        await state.set_state(AdminStates.awaiting_global_chart_threshold)
        await state.update_data(
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
        )

        prompt = (
            "<b>📈 Global Chart Threshold</b>\n\n"
            f"Current: <code>{self._format_mc(current_value)}</code>\n\n"
            "Send a market cap value (USD) to require before fetching charts globally.\n"
            "Type <code>default</code> to reset."
        )

        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_global_chart_threshold_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Settings session expired. Please reopen settings.")
            await state.clear()
            return

        raw_value = (message.text or "").strip().lower()
        if not raw_value:
            await message.answer("❌ Provide a number or 'default'.")
            return

        if raw_value in {"default", "reset"}:
            new_value = float(DEFAULT_GLOBAL_CHART_THRESHOLD)
        else:
            normalized = raw_value.replace(",", "").replace("_", "")
            try:
                decimal_value = Decimal(normalized)
            except Exception:
                await message.answer("❌ Couldn't parse that number. Try again (e.g., 150000).")
                return
            if decimal_value <= 0:
                await message.answer("❌ Threshold must be greater than zero.")
                return
            new_value = float(decimal_value)

        await self.settings_model.set_global_chart_settings(chart_threshold=new_value)
        await state.clear()
        await message.answer(f"✅ Global chart threshold set to {self._format_mc(new_value)}.")
        await self._refresh_global_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
        )

    async def start_edit_global_chart_bot(self, query: types.CallbackQuery, state: FSMContext) -> None:
        settings = await self.settings_model.get_global_chart_settings()
        current_value = settings.get("chart_bot_id")

        await state.clear()
        await state.set_state(AdminStates.awaiting_global_chart_bot)
        await state.update_data(
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
        )

        prompt = (
            "<b>🤖 Global Chart Bot</b>\n\n"
            f"Current: <code>{current_value or 'not set'}</code>\n\n"
            "Send the Telegram user ID of the chart bot to listen for globally.\n"
            "Type <code>clear</code> to remove the global value."
        )

        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_global_chart_bot_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Settings session expired. Please reopen settings.")
            await state.clear()
            return

        raw_value = (message.text or "").strip().lower()
        if not raw_value:
            await message.answer("❌ Provide a bot user ID or 'clear'.")
            return

        if raw_value in {"clear", "default", "reset"}:
            new_value: Optional[int] = None
        else:
            bot_id = self._parse_int(raw_value)
            if bot_id is None or bot_id <= 0:
                await message.answer("❌ Bot ID must be a positive integer.")
                return
            new_value = bot_id

        await self.settings_model.set_global_chart_settings(chart_bot_id=new_value)
        await state.clear()
        await message.answer("✅ Global chart bot updated." if new_value is not None else "✅ Global chart bot cleared.")
        await self._refresh_global_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
        )

    async def start_edit_chart_guardrails(self, query: types.CallbackQuery, state: FSMContext) -> None:
        guardrails = await self.settings_model.get_chart_guardrails()

        await state.clear()
        await state.set_state(AdminStates.awaiting_chart_guardrails)
        await state.update_data(
            detail_chat_id=query.message.chat.id,
            detail_message_id=query.message.message_id,
        )

        guardrail_lines = [f"- {key}: {value}" for key, value in guardrails.items()]
        prompt = (
            "<b>🛡 Chart Guardrails</b>\n\n"
            "Send a JSON object with any guardrail overrides you want to set.\n"
            "Example: <code>{\"min_age_minutes\": 10, \"min_liquidity_usd\": 15000}</code>\n"
            "Supported keys: "
            "<code>min_age_minutes</code>, <code>min_liquidity_usd</code>, <code>min_volume_usd</code>, "
            "<code>min_multiplier</code>, <code>max_price_change_pct</code>, <code>checks_required</code>.\n\n"
            "<b>Current values:</b>\n"
            + "\n".join(guardrail_lines)
        )

        await query.message.edit_text(
            prompt,
            reply_markup=self.keyboards.cancel_button("gain_alerts:cancel"),
            parse_mode="HTML",
        )
        await query.answer()

    async def handle_chart_guardrails_input(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        detail_chat_id = data.get("detail_chat_id")
        detail_message_id = data.get("detail_message_id")

        if detail_chat_id is None or detail_message_id is None:
            await message.answer("❌ Settings session expired. Please reopen settings.")
            await state.clear()
            return

        raw_input = message.text or ""
        try:
            updates = json.loads(raw_input)
        except json.JSONDecodeError:
            await message.answer("❌ Invalid JSON. Please send a JSON object.")
            return

        if not isinstance(updates, dict):
            await message.answer("❌ Guardrail updates must be a JSON object.")
            return

        filtered_updates = {k: v for k, v in updates.items() if k in DEFAULT_CHART_GUARDRAILS}
        if not filtered_updates:
            await message.answer("⚠️ No supported guardrail keys provided.")
            return

        try:
            await self.settings_model.set_chart_guardrails(filtered_updates)
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return

        await state.clear()
        await message.answer("✅ Guardrails updated.")
        await self._refresh_global_settings_message(
            message.bot,
            detail_chat_id=detail_chat_id,
            detail_message_id=detail_message_id,
        )

    # ----------------- render + refresh helpers -----------------

    async def _render_detail_view(self, chat_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
        records = await self.model.get_by_chat(chat_id)
        if not records:
            return None

        entry = self._summarise_records(records)
        userbots = await self.model.list_available_userbots()
        userbot_lookup = {record["id"]: record["label"] for record in userbots}
        if entry["use_management_bot"]:
            entry["sender_label"] = "Management bot"
        elif entry.get("assigned_userbot_id"):
            entry["sender_label"] = userbot_lookup.get(
                entry["assigned_userbot_id"],
                f"Userbot {entry['assigned_userbot_id']}",
            )
        else:
            entry["sender_label"] = "Userbot (pooled)"

        if entry.get("tracking_userbot_id"):
            entry["tracker_label"] = userbot_lookup.get(
                entry["tracking_userbot_id"],
                f"Userbot {entry['tracking_userbot_id']}",
            )
        else:
            entry["tracker_label"] = "Any"
        global_chart = await self.settings_model.get_global_chart_settings()
        global_chart_threshold = global_chart["chart_threshold_override"] or global_chart["chart_threshold_default"]
        chart_threshold = entry["chart_mc_threshold"] or global_chart_threshold
        chart_bot_display = entry["chart_bot_id"] or global_chart.get("chart_bot_id") or "—"
        guardrail_text = self._format_guardrail_result(entry.get("last_guardrail_result"))

        text_lines = [
            "<b>🌙 Gain Alerts – Source Detail</b>",
            f"Chat: <code>{chat_id}</code>",
            f"Type: {entry['chat_type']}",
            f"Enabled: {'✅' if entry['is_enabled'] else '⏸'}",
            f"Display name: {entry['display_name'] or '—'}",
            f"Sensitivity: {entry['sensitivity_text']}",
            f"Template: {'Custom' if entry['has_template'] else 'Global'}",
            f"Sender: {entry['sender_label']}",
            f"Tracker: {entry['tracker_label']}",
            f"Chart: {'📊 On' if entry['chart_enabled'] else '⏸ Off'} (≥ {self._format_mc(chart_threshold)})",
            f"Chart bot: {chart_bot_display}",
            f"Last guardrail: {guardrail_text}",
        ]
        if entry["chat_type"] == "group":
            text_lines.append(f"Tracked users: {entry['tracked_user_count']}")

        markup = self.keyboards.gain_alerts_detail(
            chat_id,
            has_template=entry["has_template"],
            has_sensitivity=entry["has_sensitivity"],
            sender_label=entry["sender_label"],
            has_tracked_users=(entry["tracked_user_count"] > 0),
            has_chart=entry["has_chart"],
            tracker_label=entry["tracker_label"],
        )
        return "\n".join(text_lines), markup

    async def _render_chart_settings_view(
        self,
        chat_id: int,
        bot: Optional[Bot] = None,
    ) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
        records = await self.model.get_by_chat(chat_id)
        if not records:
            return None

        entry = dict(records[0])
        chart_enabled = bool(entry.get("chart_enabled"))
        chart_threshold = entry.get("chart_mc_threshold")
        chart_bot_id = entry.get("chart_bot_id")

        global_guardrails = await self.settings_model.get_chart_guardrails()

        threshold_text = (
            f"{self._format_chart_threshold(DEFAULT_GLOBAL_CHART_THRESHOLD)} <i>(default)</i>"
            if chart_threshold is None
            else self._format_chart_threshold(chart_threshold)
        )

        lines = [
            "<b>📊 Chart Alert Settings</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "",
            f"<b>Status:</b> {'✅ Enabled' if chart_enabled else '⛔️ Disabled'}",
            f"<b>MC Threshold:</b> {threshold_text}",
        ]

        chart_bot_display = None
        if chart_bot_id and bot:
            try:
                chart_bot_display = await self._resolve_chart_bot_display(bot, int(chart_bot_id))
            except Exception:
                chart_bot_display = None

        if chart_bot_id:
            bot_id_int = int(chart_bot_id)
            if chart_bot_display:
                lines.append(f"<b>Chart Bot:</b> {chart_bot_display} (ID: {bot_id_int})")
            else:
                lines.append(f"<b>Chart Bot:</b> ID {bot_id_int}")
        else:
            lines.append("<b>Chart Bot:</b> <i>Not configured</i>")

        lines.extend([
            "",
            "<b>🛡️ Chart Guardrails</b>",
            "━━━━━━━━━━━━━━━━━━━━",
        ])

        metric_labels = {
            "min_age_minutes": "⏰ Token Age",
            "min_liquidity_usd": "💧 Liquidity",
            "min_volume_usd": "📊 Volume",
            "min_multiplier": "📈 Multiplier",
            "max_price_change_pct": "⚡ Price Stability",
            "checks_required": "✅ Checks Required",
        }

        last_result = entry.get("last_guardrail_result")
        if isinstance(last_result, str):
            try:
                last_result = json.loads(last_result)
            except json.JSONDecodeError:
                last_result = None

        metric_status: Dict[str, Dict[str, Any]] = {}
        if last_result and isinstance(last_result, dict):
            checks = last_result.get("checks", [])
            for check in checks:
                metric_name = check.get("name")
                if metric_name:
                    metric_status[metric_name] = {
                        "passed": check.get("passed", False),
                        "actual": check.get("actual_value"),
                        "threshold": check.get("threshold_value"),
                        "reason": check.get("reason"),
                    }

        for metric in self.GUARDRAIL_METRICS:
            metric_label = metric_labels.get(metric, metric.replace("_", " ").title())
            value_str = self._format_guardrail_value(entry, global_guardrails, metric)
            lines.append(f"  {metric_label}: {value_str}")

            if metric in metric_status:
                status = metric_status[metric]
                if status["passed"]:
                    lines.append("     └ 🟢 Last check passed")
                else:
                    reason = status.get("reason", "Failed")
                    lines.append(f"     └ 🔴 {reason}")

        lines.extend([
            "",
            "<i>💡 Tip: Set overrides to customize this source</i>",
        ])

        keyboard = self._build_chart_settings_keyboard(chat_id, chart_enabled, entry)
        return "\n".join(lines), keyboard

    def _build_chart_settings_keyboard(self, chat_id: int, enabled: bool, entry: Dict[str, Any]) -> InlineKeyboardMarkup:
        toggle_text = "⛔️ Disable" if enabled else "✅ Enable"
        keyboard = [
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=f"gain_alerts:view:chart:toggle:{chat_id}",
                ),
                InlineKeyboardButton(
                    text="💰 MC Threshold",
                    callback_data=f"gain_alerts:view:chart:threshold:{chat_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🤖 Chart Bot ID",
                    callback_data=f"gain_alerts:view:chart:bot:{chat_id}",
                )
            ],
        ]

        metric_labels = {
            "min_age_minutes": "⏰ Token Age",
            "min_liquidity_usd": "💧 Liquidity",
            "min_volume_usd": "📊 Volume",
            "min_multiplier": "📈 Multiplier",
            "max_price_change_pct": "⚡ Stability",
            "checks_required": "✅ Checks",
        }

        for metric in self.GUARDRAIL_METRICS:
            metric_label = metric_labels.get(metric, metric.replace("_", " ").title())
            override = entry.get(f"chart_{metric}")

            edit_text = f"{metric_label} ✏️" if override is not None else metric_label

            keyboard.append([
                InlineKeyboardButton(
                    text=edit_text,
                    callback_data=f"gain_alerts:edit_override:{chat_id}:{metric}",
                ),
                InlineKeyboardButton(
                    text="↩️ Reset",
                    callback_data=f"gain_alerts:reset_override:{chat_id}:{metric}",
                ) if override is not None else InlineKeyboardButton(text="—", callback_data="noop"),
            ])

        keyboard.append([
            InlineKeyboardButton(
                text="🔙 Back",
                callback_data=f"gain_alerts:view:{chat_id}",
            )
        ])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def _format_chart_threshold(self, raw_value: Any) -> str:
        try:
            decimal_value = Decimal(str(raw_value))
        except (InvalidOperation, TypeError, ValueError):
            return f"${raw_value}"

        decimal_value = decimal_value.quantize(Decimal("0.01"))
        formatted = format(decimal_value, ",.2f")
        if formatted.endswith(".00"):
            formatted = formatted[:-3]
        return f"${formatted}"

    def _format_guardrail_value(self, entry: Dict[str, Any], global_guardrails: Dict[str, Any], metric: str) -> str:
        override = entry.get(f"chart_{metric}")
        global_value = global_guardrails.get(metric, 0)

        if override is None:
            value = global_value
            label = "<i>(global)</i>"
        else:
            value = override
            label = "<b>✏️ override</b>"

        if metric == "min_age_minutes":
            return f"<code>{int(value)} min</code> {label}"
        if metric in ("min_liquidity_usd", "min_volume_usd"):
            return f"<code>{self._format_guardrail_currency(value)}</code> {label}"
        if metric == "min_multiplier":
            return f"<code>x{value:.2f}</code> {label}"
        if metric == "max_price_change_pct":
            return f"<code>{value:.1f}%</code> {label}"
        if metric == "checks_required":
            total_checks = len(self.GUARDRAIL_METRICS)
            return f"<code>{int(value)}/{total_checks}</code> {label}"
        return f"<code>{value}</code> {label}"

    def _describe_guardrail_strategy(self, checks_required: int, total_checks: int) -> str:
        if checks_required <= 0 or checks_required >= total_checks:
            return "All checks must pass"
        return f"Require any {checks_required} of {total_checks} checks"

    @staticmethod
    def _format_guardrail_currency(value: float) -> str:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return "$0"

        quantised = decimal_value.quantize(Decimal("0.01"))
        formatted = format(quantised, ",.2f")
        if formatted.endswith(".00"):
            formatted = formatted[:-3]
        return f"${formatted}"

    async def _render_chart_groups_view(self, chat_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
        groups = await self.chart_groups.list_all()
        lines = [
            "<b>👥 Chart Request Groups</b>",
            "These groups are used globally when fetching charts.",
            "",
        ]
        if groups:
            lines.extend([f"- <code>{g['chat_id']}</code> {(g.get('label') or '')}".strip() for g in groups])
        else:
            lines.append("No chart request groups configured.")

        markup = self.keyboards.chart_groups(groups, chat_id)
        return "\n".join(lines), markup

    async def _render_global_settings_view(self) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
        gain_settings = await self.settings_model.get_gain_alert_settings()
        template = await self.settings_model.get_gain_alert_template_text()
        chart_settings = await self.settings_model.get_global_chart_settings()
        guardrails = await self.settings_model.get_chart_guardrails()

        chart_threshold = chart_settings["chart_threshold_override"] or chart_settings["chart_threshold_default"]
        chart_bot_display = chart_settings.get("chart_bot_id") or "—"

        guardrail_lines = [f"- {key}: {value}" for key, value in guardrails.items()]

        lines = [
            "<b>⚙️ Global Gain Alert Settings</b>",
            f"Gain threshold: +{float(gain_settings.get('gain_threshold_pct', GAIN_THRESHOLD_DEFAULT_PCT)) * 100:.0f}%",
            f"Chart threshold: {self._format_mc(chart_threshold)}",
            f"Chart bot: {chart_bot_display}",
            "",
            "<b>Guardrails</b>",
            *guardrail_lines,
            "",
            "<b>Current template</b>",
            f"<code>{template}</code>",
        ]
        return "\n".join(lines), self.keyboards.global_settings_menu()

    async def _refresh_detail_message(
        self,
        bot,
        detail_chat_id: int,
        detail_message_id: int,
        source_chat_id: int,
    ) -> None:
        context = await self._build_detail_context(source_chat_id, bot)
        if not context:
            return
        text = context["text"]
        markup = context["keyboard"]
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=detail_chat_id,
                message_id=detail_message_id,
                reply_markup=markup,
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            logger.debug("Detail refresh no-op for chat %s: %s", source_chat_id, exc)

    async def _refresh_chart_settings_message(
        self,
        bot,
        detail_chat_id: int,
        detail_message_id: int,
        source_chat_id: int,
    ) -> None:
        rendered = await self._render_chart_settings_view(source_chat_id, bot=bot)
        if not rendered:
            return
        text, markup = rendered
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=detail_chat_id,
                message_id=detail_message_id,
                reply_markup=markup,
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            logger.debug("Chart settings refresh no-op for chat %s: %s", source_chat_id, exc)

    async def _refresh_chart_groups_message(
        self,
        bot,
        detail_chat_id: int,
        detail_message_id: int,
        source_chat_id: int,
    ) -> None:
        rendered = await self._render_chart_groups_view(source_chat_id)
        if not rendered:
            return
        text, markup = rendered
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=detail_chat_id,
                message_id=detail_message_id,
                reply_markup=markup,
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            logger.debug("Chart groups refresh no-op for chat %s: %s", source_chat_id, exc)

    async def _refresh_global_settings_message(
        self,
        bot,
        detail_chat_id: int,
        detail_message_id: int,
    ) -> None:
        rendered = await self._render_global_settings_view()
        if not rendered:
            return
        text, markup = rendered
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=detail_chat_id,
                message_id=detail_message_id,
                reply_markup=markup,
                parse_mode="HTML",
            )
        except TelegramBadRequest as exc:
            logger.debug("Global settings refresh no-op: %s", exc)

    @staticmethod
    def _format_guardrail_result(result: Optional[Dict[str, Any]]) -> str:
        if not result:
            return "—"
        passed = result.get("passed")
        checks_passed = result.get("checks_passed") or 0
        total_checks = result.get("total_checks") or result.get("checks_required") or 0
        prefix = "✅ Passed" if passed else "⚠️ Failed"
        if total_checks:
            return f"{prefix} ({checks_passed}/{total_checks})"
        return prefix

    @staticmethod
    def _format_mc(value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric >= 1_000_000_000:
            return f"${numeric/1_000_000_000:.2f}B"
        if numeric >= 1_000_000:
            return f"${numeric/1_000_000:.2f}M"
        if numeric >= 1_000:
            return f"${numeric:,.0f}"
        return f"${numeric:.2f}"
