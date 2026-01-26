"""
Settings Handler - Manages gain alert threshold configuration.
"""

from __future__ import annotations

import html
import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, Tuple

from aiogram import types
from aiogram.fsm.context import FSMContext

from models import ChartRequestGroupModel, SettingsModel, AnalyticsModel
from scheduler import get_dex_service
from ui.keyboards import Keyboards
from ui.states import AdminStates
from alerts.templates import (
    DEFAULT_GAIN_ALERT_TEMPLATE,
    normalise_template,
)

logger = logging.getLogger(__name__)


class SettingsHandler:
    """Handler for system settings."""

    GUARDRAIL_METRICS = (
        "min_age_minutes",
        "min_liquidity_usd",
        "min_volume_usd",
        "min_multiplier",
        "max_price_change_pct",
        "checks_required",
    )

    def __init__(self, db_pool, keyboards: Keyboards):
        self.db = db_pool
        self.keyboards = keyboards
        self.settings_model = SettingsModel(db_pool)
        self.chart_group_model = ChartRequestGroupModel(db_pool)
        self.analytics_model = AnalyticsModel(db_pool)

    def _compose_gain_alert_settings_text(
        self,
        gain_threshold: float,
        drop_threshold: float,
        drop_floor: float,
        template_text: str,
        chart_threshold: Decimal,
        chart_threshold_override: bool,
        chart_bot_id: Optional[int],
        guardrails: Dict[str, float],
    ) -> str:
        template_preview = html.escape(template_text)
        threshold_display = self._format_currency(chart_threshold)
        if not chart_threshold_override:
            threshold_display = f"{threshold_display} (default)"

        if chart_bot_id is not None:
            chart_bot_display = f"ID {chart_bot_id}"
        else:
            chart_bot_display = "Not configured"

        guardrail_summary = self._compose_guardrail_summary(guardrails)

        return (
            "<b>🌙 Gain Alert Settings</b>\n\n"
            "Configure market cap monitoring thresholds:\n\n"
            f"<b>📈 Gain Threshold:</b> {gain_threshold*100:.0f}%\n"
            f"  └ Alert when MC rises {gain_threshold*100:.0f}% above last alert\n\n"
            f"<b>📉 Drop Threshold:</b> {drop_threshold*100:.0f}%\n"
            f"  └ Stop monitoring when MC drops to {drop_threshold*100:.0f}% of first seen\n\n"
            f"<b>💰 Minimum Market Cap:</b> ${drop_floor:,.0f}\n"
            "  └ Stop monitoring when MC falls below this absolute floor\n\n"
            f"<b>💰 Chart MC Threshold:</b> {threshold_display}\n"
            "  └ Charts trigger when current MC meets or exceeds this value\n\n"
            f"<b>🤖 Chart Bot ID:</b> {chart_bot_display}\n"
            "  └ Defaults used when monitored sources do not override it\n\n"
            "<b>📊 Chart Guardrails</b>\n"
            f"{guardrail_summary}\n\n"
            "<i>Tap a setting to edit it.</i>\n\n"
            "<b>Current Alert Template</b>\n"
            f"<code>{template_preview}</code>"
        )

    def _compose_guardrail_summary(self, guardrails: Dict[str, float]) -> str:
        total_checks = len(self.GUARDRAIL_METRICS)
        checks_required = int(guardrails.get("checks_required", 0) or 0)

        lines = [
            f"  ├ Minimum Age: {int(guardrails.get('min_age_minutes', 0))} minutes",
            f"  ├ Minimum Liquidity: {self._format_guardrail_currency(guardrails.get('min_liquidity_usd', 0))}",
            f"  ├ Minimum Volume (24h): {self._format_guardrail_currency(guardrails.get('min_volume_usd', 0))}",
            f"  ├ Minimum Multiplier: x{guardrails.get('min_multiplier', 0):.2f}",
            f"  ├ Max Price Change: {guardrails.get('max_price_change_pct', 0):.1f}%",
            f"  └ Strategy: {self._describe_guardrail_strategy(checks_required, total_checks)}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_currency(value: Decimal) -> str:
        quantised = value.quantize(Decimal("0.01"))
        formatted = format(quantised, ",.2f")
        if formatted.endswith(".00"):
            formatted = formatted[:-3]
        return f"${formatted}"

    @staticmethod
    def _format_guardrail_currency(value: float) -> str:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return "$0"
        return SettingsHandler._format_currency(decimal_value)

    def _describe_guardrail_strategy(self, checks_required: int, total_checks: int) -> str:
        if checks_required <= 0 or checks_required >= total_checks:
            return "All checks must pass"
        return f"Require any {checks_required} of {total_checks} checks"

    def _build_guardrail_button_labels(self, guardrails: Dict[str, float]) -> Dict[str, str]:
        labels = {
            "min_age_minutes": f"{int(guardrails.get('min_age_minutes', 0))}m",
            "min_liquidity_usd": self._format_guardrail_currency(guardrails.get("min_liquidity_usd", 0)),
            "min_volume_usd": self._format_guardrail_currency(guardrails.get("min_volume_usd", 0)),
            "min_multiplier": f"x{guardrails.get('min_multiplier', 0):.2f}",
            "max_price_change_pct": f"{guardrails.get('max_price_change_pct', 0):.1f}%",
            "checks_required": self._describe_guardrail_strategy(
                int(guardrails.get("checks_required", 0) or 0),
                len(self.GUARDRAIL_METRICS),
            ),
        }
        return labels

    async def _build_gain_alert_settings_view(self) -> Tuple[str, types.InlineKeyboardMarkup]:
        settings_dict = await self.settings_model.get_gain_alert_settings()
        gain_threshold = settings_dict["gain_threshold_pct"]
        drop_threshold = settings_dict["drop_threshold_pct"]
        drop_floor = settings_dict["drop_floor_mc"]

        global_template = await self.settings_model.get_gain_alert_template_text()
        chart_group_count = await self.chart_group_model.count_groups()
        chart_settings = await self.settings_model.get_global_chart_settings()
        guardrails = await self.settings_model.get_chart_guardrails()

        chart_override: Optional[Decimal] = chart_settings.get("chart_threshold_override")
        chart_default: Decimal = chart_settings["chart_threshold_default"]
        chart_bot_id: Optional[int] = chart_settings.get("chart_bot_id")

        effective_chart_threshold = chart_override or chart_default
        threshold_label = self._format_currency(effective_chart_threshold)
        if chart_override is None:
            threshold_label = f"{threshold_label} (default)"

        chart_bot_label = str(chart_bot_id) if chart_bot_id is not None else "Not set"

        text = self._compose_gain_alert_settings_text(
            gain_threshold,
            drop_threshold,
            drop_floor,
            global_template,
            effective_chart_threshold,
            chart_override is not None,
            chart_bot_id,
            guardrails,
        )

        guardrail_labels = self._build_guardrail_button_labels(guardrails)

        keyboard = self.keyboards.gain_alert_settings_menu(
            gain_threshold,
            drop_threshold,
            drop_floor,
            chart_group_count,
            threshold_label,
            chart_bot_label,
            guardrail_labels,
        )

        return text, keyboard

    async def show_settings_menu(self, query: types.CallbackQuery) -> None:
        try:
            await query.message.edit_text(
                "<b>⚙️ System Settings</b>\n\n"
                "Manage gain alert sources, global thresholds, and scheduler diagnostics.",
                reply_markup=self.keyboards.settings_menu(),
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing settings menu: %s", exc)
            await query.answer("❌ Error loading settings", show_alert=True)

    async def show_gain_alert_settings(self, query: types.CallbackQuery) -> None:
        try:
            text, keyboard = await self._build_gain_alert_settings_view()
            await query.message.edit_text(text, reply_markup=keyboard)
            await query.answer()
        except Exception as exc:
            logger.error("Error showing gain alert settings: %s", exc)
            await query.answer("❌ Error loading gain alert settings", show_alert=True)

    async def prompt_edit_gain_threshold(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            settings_dict = await self.settings_model.get_gain_alert_settings()
            current = settings_dict["gain_threshold_pct"] * 100

            await query.message.edit_text(
                "<b>📈 Edit Gain Threshold</b>\n\n"
                f"Current: {current:.0f}%\n\n"
                "Enter new gain threshold percentage (e.g., 30 for 30%):\n\n"
                "<i>This determines when alerts fire. A 30% threshold means an alert "
                "will be sent when the market cap rises 30% above the last alert level.</i>",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
            )
            await state.set_state(AdminStates.awaiting_gain_threshold)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting gain threshold edit: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def prompt_edit_drop_threshold(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            settings_dict = await self.settings_model.get_gain_alert_settings()
            current = settings_dict["drop_threshold_pct"] * 100

            await query.message.edit_text(
                "<b>📉 Edit Drop Threshold</b>\n\n"
                f"Current: {current:.0f}%\n\n"
                "Enter new drop threshold percentage (e.g., 70 for 70%):\n\n"
                "<i>Monitoring stops when MC drops to this percentage of the initial market cap. "
                "A 70% threshold means monitoring stops when MC falls to 70% of the first seen value.</i>",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
            )
            await state.set_state(AdminStates.awaiting_drop_threshold)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting drop threshold edit: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def prompt_edit_drop_floor(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            settings_dict = await self.settings_model.get_gain_alert_settings()
            current = settings_dict["drop_floor_mc"]

            await query.message.edit_text(
                "<b>💰 Edit Minimum Market Cap</b>\n\n"
                f"Current: ${current:,.0f}\n\n"
                "Enter new minimum market cap (e.g., 8000 for $8,000):\n\n"
                "<i>Monitoring stops when MC falls below this absolute value, "
                "regardless of percentage thresholds.</i>",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
            )
            await state.set_state(AdminStates.awaiting_drop_floor)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting drop floor edit: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def prompt_edit_gain_template(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            template = await self.settings_model.get_gain_alert_template_text()
            placeholder_list = ", ".join([
                "{gain_emoji}",
                "{token_symbol}",
                "{multiplier}",
                "{first_market_cap}",
                "{current_market_cap}",
                "{elapsed_time}",
                "{address}",
            ])
            preview = html.escape(template)

            await query.message.edit_text(
                "<b>📝 Edit Global Gain Alert Template</b>\n\n"
                "Available placeholders:\n"
                f"<code>{placeholder_list}</code>\n\n"
                "<i>Placeholders are optional—use any combination or none at all.</i>\n\n"
                "Send the new template text exactly as it should appear.\n"
                "Type <code>reset</code> to restore the default template.\n\n"
                "<b>Current template:</b>\n"
                f"<code>{preview}</code>",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
                parse_mode="HTML",
            )
            await state.set_state(AdminStates.awaiting_gain_template)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting global template edit: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def prompt_edit_chart_threshold(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            chart_settings = await self.settings_model.get_global_chart_settings()
            chart_override: Optional[Decimal] = chart_settings.get("chart_threshold_override")
            chart_default: Decimal = chart_settings["chart_threshold_default"]

            current_value = chart_override or chart_default
            current_display = self._format_currency(current_value)
            if chart_override is None:
                current_display = f"{current_display} (default)"

            await query.message.edit_text(
                "<b>💰 Set Global MC Threshold</b>\n\n"
                f"Current: {current_display}\n\n"
                "Send the minimum market cap (USD) required to request charts.\n"
                "Type <code>reset</code> to restore the default value.\n\n"
                "<i>This applies when monitored sources have charts enabled but no per-source override.</i>",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
                parse_mode="HTML",
            )
            await state.set_state(AdminStates.awaiting_global_chart_threshold)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting global chart threshold edit: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def prompt_edit_chart_bot(self, query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            chart_settings = await self.settings_model.get_global_chart_settings()
            chart_bot_id = chart_settings.get("chart_bot_id")
            current_display = str(chart_bot_id) if chart_bot_id is not None else "Not configured"

            await query.message.edit_text(
                "<b>🤖 Set Global Chart Bot ID</b>\n\n"
                f"Current: {current_display}\n\n"
                "Send the Telegram user ID of the bot that replies with chart images.\n"
                "Type <code>reset</code> to clear the global default.\n\n"
                "<i>Sources inherit this ID when chart alerts are enabled without overrides.</i>",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
                parse_mode="HTML",
            )
            await state.set_state(AdminStates.awaiting_global_chart_bot)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting global chart bot edit: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def save_gain_threshold(self, message: types.Message, state: FSMContext) -> None:
        try:
            value = float(message.text.strip())

            if value <= 0 or value > 1000:
                await message.answer("❌ Invalid value. Please enter a percentage between 1 and 1000.")
                return

            decimal_value = value / 100.0
            await self.settings_model.set_gain_threshold_pct(decimal_value)

            await message.answer(
                f"✅ Gain threshold updated to {value:.0f}%\n\n"
                f"Alerts will now fire when tokens gain {value:.0f}% from their last alert level."
            )

            await state.clear()
            text, keyboard = await self._build_gain_alert_settings_view()
            await message.answer(text, reply_markup=keyboard)

        except ValueError:
            await message.answer("❌ Invalid input. Please enter a valid number.")
        except Exception as exc:
            logger.error("Error saving gain threshold: %s", exc)
            await message.answer("❌ Error saving setting")

    async def save_drop_threshold(self, message: types.Message, state: FSMContext) -> None:
        try:
            value = float(message.text.strip())

            if value <= 0 or value > 100:
                await message.answer("❌ Invalid value. Please enter a percentage between 1 and 100.")
                return

            decimal_value = value / 100.0
            await self.settings_model.set_drop_threshold_pct(decimal_value)

            await message.answer(
                f"✅ Drop threshold updated to {value:.0f}%\n\n"
                f"Monitoring will stop when tokens drop to {value:.0f}% of their initial market cap."
            )

            await state.clear()
            text, keyboard = await self._build_gain_alert_settings_view()
            await message.answer(text, reply_markup=keyboard)

        except ValueError:
            await message.answer("❌ Invalid input. Please enter a valid number.")
        except Exception as exc:
            logger.error("Error saving drop threshold: %s", exc)
            await message.answer("❌ Error saving setting")

    async def save_drop_floor(self, message: types.Message, state: FSMContext) -> None:
        try:
            value = float(message.text.strip().replace(",", "").replace("$", ""))

            if value < 0 or value > 1_000_000_000:
                await message.answer("❌ Invalid value. Please enter a market cap between 0 and 1,000,000,000.")
                return

            await self.settings_model.set_drop_floor_mc(value)

            await message.answer(
                f"✅ Minimum market cap updated to ${value:,.0f}\n\n"
                f"Monitoring will stop when tokens fall below ${value:,.0f}."
            )

            await state.clear()
            text, keyboard = await self._build_gain_alert_settings_view()
            await message.answer(text, reply_markup=keyboard)

        except ValueError:
            await message.answer("❌ Invalid input. Please enter a valid number.")
        except Exception as exc:
            logger.error("Error saving drop floor: %s", exc)
            await message.answer("❌ Error saving setting")

    async def save_chart_threshold(self, message: types.Message, state: FSMContext) -> None:
        raw_input = (message.text or "").strip()
        lowered = raw_input.lower()

        try:
            if lowered in {"reset", "default"}:
                await self.settings_model.set_global_chart_threshold(None)
                await message.answer("✅ Global chart MC threshold reset to default ($100,000).")
            else:
                numeric_text = raw_input.replace(",", "").replace("$", "")
                value = Decimal(numeric_text)
                if value <= 0:
                    await message.answer("❌ Value must be greater than zero.")
                    return
                if value > Decimal("1000000000"):
                    await message.answer("❌ Please choose a value below $1,000,000,000.")
                    return

                await self.settings_model.set_global_chart_threshold(float(value))
                await message.answer(
                    f"✅ Global chart MC threshold set to {self._format_currency(value)}."
                )

            await state.clear()
            text, keyboard = await self._build_gain_alert_settings_view()
            await message.answer(text, reply_markup=keyboard)
        except (InvalidOperation, ValueError):
            await message.answer("❌ Invalid number. Example: 125000 or 125000.50")
        except Exception as exc:
            logger.error("Error saving global chart threshold: %s", exc)
            await message.answer("❌ Error saving chart threshold")

    async def save_chart_bot(self, message: types.Message, state: FSMContext) -> None:
        raw_input = (message.text or "").strip()
        lowered = raw_input.lower()

        try:
            if lowered in {"reset", "clear", "none"}:
                await self.settings_model.set_global_chart_bot_id(None)
                await message.answer("✅ Global chart bot ID cleared.")
            else:
                bot_id = int(raw_input)
                if bot_id <= 0:
                    await message.answer("❌ Bot ID must be a positive integer.")
                    return

                await self.settings_model.set_global_chart_bot_id(bot_id)
                await message.answer(f"✅ Global chart bot ID set to {bot_id}.")

            await state.clear()
            text, keyboard = await self._build_gain_alert_settings_view()
            await message.answer(text, reply_markup=keyboard)
        except ValueError:
            await message.answer("❌ Invalid ID. Provide the numeric Telegram user ID.")
        except Exception as exc:
            logger.error("Error saving global chart bot ID: %s", exc)
            await message.answer("❌ Error saving chart bot ID")

    async def prompt_edit_guardrail(self, query: types.CallbackQuery, state: FSMContext, metric: str) -> None:
        try:
            guardrails = await self.settings_model.get_chart_guardrails()
            current_value = guardrails.get(metric, 0)

            if metric == "min_age_minutes":
                prompt = f"Enter new minimum age in minutes (e.g., 30 for 30 minutes):\n\nCurrent: {int(current_value)} minutes"
            elif metric == "min_liquidity_usd":
                prompt = f"Enter new minimum liquidity in USD (e.g., 5000 for $5,000):\n\nCurrent: {self._format_guardrail_currency(current_value)}"
            elif metric == "min_volume_usd":
                prompt = f"Enter new minimum 24h volume in USD (e.g., 10000 for $10,000):\n\nCurrent: {self._format_guardrail_currency(current_value)}"
            elif metric == "min_multiplier":
                prompt = f"Enter new minimum multiplier (e.g., 1.5 for 1.5x):\n\nCurrent: x{current_value:.2f}"
            elif metric == "max_price_change_pct":
                prompt = f"Enter new max price change percentage (e.g., 50 for 50%):\n\nCurrent: {current_value:.1f}%"
            elif metric == "checks_required":
                total_checks = len(self.GUARDRAIL_METRICS)
                prompt = (
                    f"Enter how many checks must pass (1 to {total_checks}):\n\n"
                    f"0 or {total_checks} = All must pass\n\n"
                    f"Current: {self._describe_guardrail_strategy(int(current_value), total_checks)}"
                )
            else:
                await query.answer("Unknown metric.", show_alert=True)
                return

            await query.message.edit_text(
                f"<b>📊 Edit Chart Guardrail</b>\n\n{prompt}",
                reply_markup=self.keyboards.cancel_button("settings:gain_alerts"),
            )
            await state.set_state(AdminStates.awaiting_guardrail_value)
            await state.update_data(metric_to_edit=metric)
            await query.answer()
        except Exception as exc:
            logger.error("Error prompting guardrail edit for %s: %s", metric, exc)
            await query.answer("❌ Error", show_alert=True)

    async def save_guardrail_value(self, message: types.Message, state: FSMContext) -> None:
        try:
            data = await state.get_data()
            metric = data.get("metric_to_edit")
            if not metric:
                await message.answer("Error: Could not determine which setting to update.")
                await state.clear()
                return

            raw_value = message.text.strip()

            if metric in ("min_age_minutes", "checks_required"):
                value = int(raw_value)
            else:
                value = float(raw_value.replace("$", "").replace(",", ""))

            await self.settings_model.set_chart_guardrails({metric: value})

            await message.answer(f"✅ Guardrail '{metric.replace('_', ' ').title()}' updated.")
            await state.clear()

            text, keyboard = await self._build_gain_alert_settings_view()
            await message.answer(text, reply_markup=keyboard)

        except (ValueError, TypeError):
            await message.answer("❌ Invalid input. Please enter a valid number.")
        except Exception as exc:
            logger.error("Error saving guardrail value: %s", exc)
            await message.answer("❌ Error saving setting.")

    async def save_gain_template(self, message: types.Message, state: FSMContext) -> None:
        raw_input = message.text or ""
        stripped = raw_input.strip()

        if not stripped:
            await message.answer(
                "❌ Template cannot be empty. Include the required placeholders or type 'reset'."
            )
            return

        if stripped.lower() == "reset":
            template_to_store = DEFAULT_GAIN_ALERT_TEMPLATE
        else:
            template_to_store = normalise_template(raw_input)

        try:
            await self.settings_model.set_gain_alert_template_text(template_to_store)
        except Exception as exc:
            logger.error("Error saving gain alert template: %s", exc, exc_info=True)
            await message.answer("❌ Failed to save template. Please try again.")
            return

        await state.clear()
        preview = html.escape(template_to_store)
        await message.answer(
            "✅ Global gain alert template updated.\n\n"
            "Current template:\n"
            f"<code>{preview}</code>",
            parse_mode="HTML",
        )

    async def show_token_status_menu(self, query: types.CallbackQuery) -> None:
        try:
            await query.message.edit_text(
                "<b>📊 Token Status & Monitoring</b>\n\n"
                "View scheduler health and token details.",
                reply_markup=self.keyboards.token_status_menu(),
            )
            await query.answer()
        except Exception as exc:
            logger.error("Error showing token status menu: %s", exc)
            await query.answer("❌ Error", show_alert=True)

    async def show_scheduler_overview(self, query: types.CallbackQuery) -> None:
        try:
            dex_service = get_dex_service()
            stats = await dex_service.get_service_stats()

            tier_counts = await self.db.fetch(
                """
                SELECT current_tier, COUNT(*) as count
                FROM tokens_tracked
                WHERE status = 'active' AND current_tier IS NOT NULL
                GROUP BY current_tier
                ORDER BY current_tier
                """
            )

            stopped_count = await self.db.fetchval(
                "SELECT COUNT(*) FROM tokens_tracked WHERE status = 'stopped'"
            )

            tier_map = {
                "tier_a": ("Tier A (10s)", 0),
                "tier_b": ("Tier B (30s)", 0),
                "tier_c": ("Tier C (3m)", 0),
                "tier_d": ("Tier D (5m)", 0),
                "tier_e": ("Tier E (10m)", 0),
                "tier_f": ("Tier F (30m)", 0),
            }

            for row in tier_counts:
                tier = row["current_tier"]
                if tier in tier_map:
                    tier_map[tier] = (tier_map[tier][0], row["count"])

            text = (
                "<b>📊 DexScreener Scheduler Status</b>\n\n"
                f"🔄 <b>Scheduler Active:</b> {'✅ Yes' if stats['scheduler_active'] else '❌ No'}\n"
                f"📦 <b>Tokens in Queue:</b> {stats['tokens_in_queue']}\n"
                f"⚙️ <b>Service Running:</b> {'✅ Yes' if stats['running'] else '❌ No'}\n\n"
                "<b>📈 By Tier:</b>\n"
            )

            for tier_name, count in tier_map.values():
                text += f"  ├ {tier_name}: {count} tokens\n"

            text += f"\n⛔ <b>Stopped:</b> {stopped_count or 0} tokens"

            await query.message.edit_text(
                text,
                reply_markup=self.keyboards.back_button("settings:token_status"),
            )
            await query.answer()

        except Exception as exc:
            logger.error("Error showing scheduler overview: %s", exc)
            await query.answer("❌ Error loading scheduler stats", show_alert=True)

    async def show_tokens_list(self, query: types.CallbackQuery, status: str, page: int = 1) -> None:
        try:
            items_per_page = 9
            offset = (page - 1) * items_per_page

            tokens = await self.db.fetch(
                """
                SELECT
                    address, ticker, current_tier, next_poll_at,
                    first_seen_mc, last_mc, last_alert_mc,
                    dex_screener_refreshed_at, stop_reason,
                    first_seen_at
                FROM tokens_tracked
                WHERE status = $1
                ORDER BY
                    CASE WHEN status = 'active' THEN next_poll_at ELSE first_seen_at END DESC
                LIMIT $2 OFFSET $3
                """,
                status,
                items_per_page,
                offset,
            )

            total_count = await self.db.fetchval(
                "SELECT COUNT(*) FROM tokens_tracked WHERE status = $1",
                status,
            )

            total_pages = max(1, (total_count + items_per_page - 1) // items_per_page)

            if status == "active":
                title = f"🪙 Active Tokens (Page {page}/{total_pages})"
            else:
                title = f"⛔ Stopped Tokens (Page {page}/{total_pages})"

            text = f"<b>{title}</b>\n\n"

            if not tokens:
                text += "<i>No tokens found.</i>"
            else:
                for token in tokens:
                    ticker = token["ticker"] or "Unknown"
                    address = token["address"]

                    text += f"<b>{ticker}</b>\n"
                    text += f"  ├ <b>CA:</b> <code>{html.escape(address)}</code>\n"

                    if status == "active":
                        tier = token["current_tier"] or "N/A"
                        next_poll = token["next_poll_at"]

                        tier_display = tier.replace("tier_", "Tier ").upper() if tier != "N/A" else "N/A"

                        text += f"  ├ <b>Tier:</b> {tier_display}\n"

                        if next_poll:
                            text += f"  ├ <b>Next Poll:</b> {next_poll.strftime('%H:%M:%S UTC')}\n"

                        if token["first_seen_mc"]:
                            text += f"  ├ <b>First MC:</b> {self._format_mc_short(token['first_seen_mc'])}\n"

                        if token["last_mc"]:
                            text += f"  ├ <b>Last MC:</b> {self._format_mc_short(token['last_mc'])}\n"

                        if token["last_alert_mc"] and token["last_alert_mc"] > 0:
                            text += f"  ├ <b>Last Alert:</b> {self._format_mc_short(token['last_alert_mc'])}\n"

                        if token["dex_screener_refreshed_at"]:
                            text += f"  └ <b>Refreshed:</b> {token['dex_screener_refreshed_at'].strftime('%H:%M:%S UTC')}\n"
                    else:
                        stop_reason = token["stop_reason"] or "Unknown"
                        reason_display = {
                            "mc_drop_70": "📉 Dropped below 70%",
                            "mc_below_floor": "💰 Below minimum MC",
                        }.get(stop_reason, stop_reason)

                        text += f"  ├ <b>Reason:</b> {reason_display}\n"

                        if token["first_seen_mc"]:
                            text += f"  ├ <b>First MC:</b> {self._format_mc_short(token['first_seen_mc'])}\n"

                        if token["last_mc"]:
                            text += f"  └ <b>Last MC:</b> {self._format_mc_short(token['last_mc'])}\n"

                    text += "\n"

            await query.message.edit_text(
                text,
                reply_markup=self.keyboards.token_list_navigation(status, page, total_pages),
            )
            await query.answer()

        except Exception as exc:
            logger.error("Error showing tokens list: %s", exc)
            await query.answer("❌ Error loading tokens", show_alert=True)

    def _format_mc_short(self, mc):
        if mc is None:
            return "N/A"

        value = float(mc)

        if value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"${value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"${value / 1_000:.1f}K"
        return f"${value:.0f}"

    async def cmd_timeframes(self, message: types.Message) -> None:
        """List all hold timeframes."""
        try:
            timeframes = await self.analytics_model.get_hold_timeframes()

            if not timeframes:
                await message.answer("⏱ <b>No hold timeframes configured.</b>", parse_mode="HTML")
                return

            lines = ["⏱ <b>Hold Timeframes</b>", ""]
            
            defaults = [tf["label"] for tf in timeframes if tf["is_default"]]
            if defaults:
                lines.append("<b>Defaults (shown in /invest):</b>")
                lines.append("✅ " + " | ✅ ".join(defaults))
                lines.append("")

            lines.append("<b>All available:</b>")
            lines.append(", ".join([tf["label"] for tf in timeframes]))
            
            lines.append("\n<b>Commands:</b>")
            lines.append("• <code>/addtimeframe &lt;label&gt; &lt;seconds&gt; [default]</code>")
            lines.append("• <code>/deltimeframe &lt;label&gt;</code>")
            lines.append("\n<i>Example: /addtimeframe 4h 14400 true</i>")

            await message.answer("\n".join(lines), parse_mode="HTML")
        except Exception as exc:
            logger.error("Error in cmd_timeframes: %s", exc)
            await message.answer("❌ Failed to load timeframes.")

    async def cmd_add_timeframe(self, message: types.Message) -> None:
        """Add a new hold timeframe."""
        try:
            parts = message.text.split()
            if len(parts) < 3:
                await message.answer(
                    "<b>Usage:</b>\n<code>/addtimeframe &lt;label&gt; &lt;seconds&gt; [default]</code>\n\n"
                    "Example: <code>/addtimeframe 4h 14400 true</code>",
                    parse_mode="HTML"
                )
                return

            label = parts[1]
            try:
                seconds = int(parts[2])
            except ValueError:
                await message.answer("❌ Seconds must be an integer.")
                return

            is_default = False
            if len(parts) > 3:
                is_default = parts[3].lower() in ("true", "yes", "1")

            success = await self.analytics_model.add_hold_timeframe(label, seconds, is_default)
            if success:
                await message.answer(f"✅ Timeframe <b>{label}</b> added ({seconds}s, default: {is_default})", parse_mode="HTML")
            else:
                await message.answer(f"❌ Failed to add timeframe <b>{label}</b>. It might already exist.", parse_mode="HTML")
        except Exception as exc:
            logger.error("Error in cmd_add_timeframe: %s", exc)
            await message.answer("❌ Error adding timeframe.")

    async def cmd_del_timeframe(self, message: types.Message) -> None:
        """Delete a hold timeframe."""
        try:
            parts = message.text.split()
            if len(parts) < 2:
                await message.answer("<b>Usage:</b>\n<code>/deltimeframe &lt;label&gt;</code>", parse_mode="HTML")
                return

            label = parts[1]
            success = await self.analytics_model.delete_hold_timeframe(label)
            if success:
                await message.answer(f"✅ Timeframe <b>{label}</b> deleted.", parse_mode="HTML")
            else:
                await message.answer(f"❌ Timeframe <b>{label}</b> not found.", parse_mode="HTML")
        except Exception as exc:
            logger.error("Error in cmd_del_timeframe: %s", exc)
            await message.answer("❌ Error deleting timeframe.")
