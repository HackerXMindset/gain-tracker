from __future__ import annotations

from typing import Any, Dict, List, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class Keyboards:
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📈 Gain Alerts", callback_data="gain_alerts:menu")],
                [InlineKeyboardButton(text="👤 Agents", callback_data="menu:userbots")],
                [InlineKeyboardButton(text="⚙️ Settings", callback_data="menu:settings")],
            ]
        )

    @staticmethod
    def cancel_button(callback_data: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]])

    @staticmethod
    def back_button(callback_data: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]])

    @staticmethod
    def pagination(prefix: str, page: int, total_pages: int) -> List[InlineKeyboardButton]:
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:page:{page-1}"))
        buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data=f"{prefix}:page:info"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:page:{page+1}"))
        return buttons

    @staticmethod
    def userbots_menu(userbots: List[Dict[str, Any]], page: int, total_pages: int) -> InlineKeyboardMarkup:
        keyboard = []

        for bot in userbots:
            status_icon = "🟢" if bot["status"] == "active" else "🔴"
            name = (bot.get("display_name") or bot["session_name"])[:20]
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status_icon} {name}",
                    callback_data=f"userbot:view:{bot['id']}",
                )
            ])

        if total_pages > 1:
            keyboard.append(Keyboards.pagination("userbots_page", page, total_pages))

        keyboard.extend([
            [
                InlineKeyboardButton(text="➕ Add Userbot", callback_data="userbot:add"),
                InlineKeyboardButton(text="🔄 Check Health", callback_data="userbot:health"),
            ],
            [
                InlineKeyboardButton(text="🔄 Refresh Sources", callback_data="userbot:refresh_sources"),
            ],
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="menu:main"),
            ],
        ])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def gain_alerts_main_menu(entries: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        keyboard: List[List[InlineKeyboardButton]] = [
            [InlineKeyboardButton(text="➕ Add Monitored Source", callback_data="gain_alerts:add")]
        ]

        for entry in entries:
            chat_id = entry["chat_id"]
            label = entry.get("button_text") or entry.get("label") or str(chat_id)
            keyboard.append([InlineKeyboardButton(text=label, callback_data=f"gain_alerts:view:{chat_id}")])

        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="settings:main")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def gain_alerts_type_selector() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📢 Channel", callback_data="gain_alerts:add:type:channel")],
                [InlineKeyboardButton(text="👥 Group", callback_data="gain_alerts:add:type:group")],
                [InlineKeyboardButton(text="💬 DM", callback_data="gain_alerts:add:type:dm")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="gain_alerts:cancel")],
            ]
        )

    @staticmethod
    def gain_alerts_add_confirm() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Confirm", callback_data="gain_alerts:add:confirm")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="gain_alerts:cancel")],
            ]
        )

    @staticmethod
    def chart_groups_menu(groups: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        keyboard: List[List[InlineKeyboardButton]] = [
            [InlineKeyboardButton(text="➕ Add Group", callback_data="gain_alerts:chart_groups:add")]
        ]

        for group in groups:
            chat_id = group.get("chat_id")
            label = group.get("label")
            if label:
                button_text = f"🗑️ Remove {chat_id} ({label})"
            else:
                button_text = f"🗑️ Remove {chat_id}"

            keyboard.append([
                InlineKeyboardButton(text=button_text, callback_data=f"gain_alerts:chart_groups:remove:{chat_id}")
            ])

        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="gain_alerts:menu")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def settings_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 Gain Alerts", callback_data="gain_alerts:menu")],
            [InlineKeyboardButton(text="🌙 Gain Alert Settings", callback_data="settings:gain_alerts")],
            [InlineKeyboardButton(text="📊 Token Status", callback_data="settings:token_status")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="menu:main")],
        ])

    @staticmethod
    def gain_alert_settings_menu(
        gain_threshold: float,
        drop_threshold: float,
        drop_floor: float,
        chart_group_count: int,
        chart_threshold_label: str,
        chart_bot_label: str,
        guardrail_labels: Dict[str, str],
    ) -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(
                text=f"📈 Gain Threshold: {gain_threshold*100:.0f}%",
                callback_data="settings:edit_gain_threshold"
            )],
            [InlineKeyboardButton(
                text=f"📉 Drop Threshold: {drop_threshold*100:.0f}%",
                callback_data="settings:edit_drop_threshold"
            )],
            [InlineKeyboardButton(
                text=f"💰 Minimum MC: ${drop_floor:,.0f}",
                callback_data="settings:edit_drop_floor"
            )],
            [InlineKeyboardButton(
                text=f"💰 Set MC Threshold ({chart_threshold_label})",
                callback_data="settings:edit_chart_threshold"
            )],
            [InlineKeyboardButton(
                text=f"🤖 Set Chart Bot ID ({chart_bot_label})",
                callback_data="settings:edit_chart_bot"
            )],
            [
                InlineKeyboardButton(
                    text=f"Age: {guardrail_labels['min_age_minutes']}",
                    callback_data="settings:edit_guardrail:min_age_minutes"
                ),
                InlineKeyboardButton(
                    text=f"Liq: {guardrail_labels['min_liquidity_usd']}",
                    callback_data="settings:edit_guardrail:min_liquidity_usd"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"Vol: {guardrail_labels['min_volume_usd']}",
                    callback_data="settings:edit_guardrail:min_volume_usd"
                ),
                InlineKeyboardButton(
                    text=f"MC x: {guardrail_labels['min_multiplier']}",
                    callback_data="settings:edit_guardrail:min_multiplier"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"Price Δ: {guardrail_labels['max_price_change_pct']}",
                    callback_data="settings:edit_guardrail:max_price_change_pct"
                ),
                InlineKeyboardButton(
                    text=f"Strat: {guardrail_labels['checks_required']}",
                    callback_data="settings:edit_guardrail:checks_required"
                ),
            ],
            [InlineKeyboardButton(
                text="📝 Edit Alert Template",
                callback_data="settings:edit_gain_template"
            )],
            [InlineKeyboardButton(
                text=f"⚙️ Chart Request Groups ({chart_group_count})",
                callback_data="gain_alerts:chart_groups:menu"
            )],
            [InlineKeyboardButton(text="🔙 Back", callback_data="settings:main")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def token_status_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Scheduler Overview", callback_data="settings:scheduler_overview")],
            [InlineKeyboardButton(text="🪙 Active Tokens", callback_data="settings:tokens_list:active:1")],
            [InlineKeyboardButton(text="⛔ Stopped Tokens", callback_data="settings:tokens_list:stopped:1")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="settings:main")],
        ])

    @staticmethod
    def token_list_navigation(status: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
        keyboard = []
        if total_pages > 1:
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"settings:tokens_list:{status}:{page-1}"))
            nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"settings:tokens_list:{status}:{page+1}"))
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="settings:token_status")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def gain_alerts_detail(
        chat_id: int,
        has_template: bool,
        has_sensitivity: bool,
        sender_label: str,
        has_tracked_users: bool,
        has_chart: bool,
        tracker_label: str = "Any",
    ) -> InlineKeyboardMarkup:
        buttons = [
            [InlineKeyboardButton(text="✅/⏸ Toggle Alerts", callback_data=f"gain_alerts:view:toggle:{chat_id}")],
            [InlineKeyboardButton(text="✏️ Display Name", callback_data=f"gain_alerts:view:edit_name:{chat_id}")],
            [InlineKeyboardButton(text="🎯 Sensitivity", callback_data=f"gain_alerts:view:sensitivity:{chat_id}")],
            [InlineKeyboardButton(text="📝 Template", callback_data=f"gain_alerts:view:template:{chat_id}")],
            [InlineKeyboardButton(text=f"📤 Sender: {sender_label}", callback_data=f"gain_alerts:view:userbot:{chat_id}")],
            [InlineKeyboardButton(text=f"📡 Tracker: {tracker_label}", callback_data=f"gain_alerts:view:tracking:{chat_id}")],
        ]
        if has_chart:
            buttons.append([InlineKeyboardButton(text="📊 Chart Settings", callback_data=f"gain_alerts:view:chart:{chat_id}")])
        if has_tracked_users:
            buttons.append([InlineKeyboardButton(text="👥 Tracked Users", callback_data=f"gain_alerts:view:users:{chat_id}")])
        buttons.append([InlineKeyboardButton(text="⚠️ Delete Source", callback_data=f"gain_alerts:view:remove_chat:{chat_id}")])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="gain_alerts:menu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def tracked_users(users: List[Dict[str, Any]], chat_id: int) -> InlineKeyboardMarkup:
        buttons = []
        for user in users:
            uid = user.get("user_id")
            source_id = user.get("id")
            if uid and source_id:
                buttons.append([InlineKeyboardButton(text=f"❌ Remove {uid}", callback_data=f"gain_alerts:view:remove_user:{source_id}")])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"gain_alerts:view:{chat_id}")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def confirm_delete(chat_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⚠️ Confirm Delete", callback_data=f"gain_alerts:view:remove_chat:confirm:{chat_id}")],
                [InlineKeyboardButton(text="🔙 Back", callback_data=f"gain_alerts:view:{chat_id}")],
            ]
        )

    @staticmethod
    def chart_settings(chat_id: int, chart_enabled: bool) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅/⏸ Chart On/Off", callback_data=f"gain_alerts:view:chart:toggle:{chat_id}")],
                [InlineKeyboardButton(text="📈 Edit MC Threshold", callback_data=f"gain_alerts:view:chart:threshold:{chat_id}")],
                [InlineKeyboardButton(text="🤖 Chart Bot ID", callback_data=f"gain_alerts:view:chart:bot:{chat_id}")],
                [InlineKeyboardButton(text="🔙 Back to Source", callback_data=f"gain_alerts:view:{chat_id}")],
            ]
        )

    @staticmethod
    def chart_groups(groups: List[Dict[str, Any]], chat_id: int) -> InlineKeyboardMarkup:
        buttons = []
        if groups:
            buttons.append([InlineKeyboardButton(text="❌ Remove Group", callback_data=f"gain_alerts:view:chart:groups:remove:{chat_id}")])
        buttons.append([InlineKeyboardButton(text="➕ Add Group", callback_data=f"gain_alerts:view:chart:groups:add:{chat_id}")])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"gain_alerts:view:chart:{chat_id}")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def global_settings_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Gain Threshold", callback_data="gain_alerts:settings:gain_threshold")],
                [InlineKeyboardButton(text="📝 Gain Template", callback_data="gain_alerts:settings:gain_template")],
                [InlineKeyboardButton(text="📈 Chart Threshold", callback_data="gain_alerts:settings:chart_threshold")],
                [InlineKeyboardButton(text="🤖 Chart Bot ID", callback_data="gain_alerts:settings:chart_bot")],
                [InlineKeyboardButton(text="🛡 Chart Guardrails", callback_data="gain_alerts:settings:guardrails")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="gain_alerts:menu")],
            ]
        )
