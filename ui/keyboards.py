from __future__ import annotations

from typing import Any, Dict, List, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class Keyboards:
    @staticmethod
    def _chunk_buttons(buttons: List[InlineKeyboardButton], per_row: int) -> List[List[InlineKeyboardButton]]:
        rows: List[List[InlineKeyboardButton]] = []
        for idx in range(0, len(buttons), per_row):
            rows.append(buttons[idx:idx + per_row])
        return rows
    @staticmethod
    def main_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📈 Gain Alerts", callback_data="gain_alerts:menu")],
                [InlineKeyboardButton(text="🤖 AutoTrader", callback_data="settings:autotrader")],
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
        keyboard: List[List[InlineKeyboardButton]] = []

        buttons: List[InlineKeyboardButton] = []
        for bot in userbots:
            status_icon = "🟢" if bot["status"] == "active" else "🔴"
            name = (bot.get("display_name") or bot["session_name"])[:20]
            buttons.append(
                InlineKeyboardButton(
                    text=f"{status_icon} {name}",
                    callback_data=f"userbot:view:{bot['id']}",
                )
            )

        keyboard.extend(Keyboards._chunk_buttons(buttons, 2))

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
    def gain_alerts_main_menu(
        entries: List[Dict[str, Any]],
        page: int = 1,
        total_pages: int = 1,
    ) -> InlineKeyboardMarkup:
        keyboard: List[List[InlineKeyboardButton]] = [
            [InlineKeyboardButton(text="➕ Add Monitored Source", callback_data="gain_alerts:add")]
        ]

        buttons: List[InlineKeyboardButton] = []
        for entry in entries:
            chat_id = entry["chat_id"]
            label = entry.get("button_text") or entry.get("label") or str(chat_id)
            if len(label) > 28:
                label = label[:25] + "..."
            buttons.append(InlineKeyboardButton(text=label, callback_data=f"gain_alerts:view:{chat_id}"))

        keyboard.extend(Keyboards._chunk_buttons(buttons, 2))

        if total_pages > 1:
            nav_buttons: List[InlineKeyboardButton] = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"gain_alerts:menu:page:{page-1}"))
            nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"gain_alerts:menu:page:{page+1}"))
            keyboard.append(nav_buttons)

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
    def chart_groups_menu(
        groups: List[Dict[str, Any]],
        page: int = 1,
        total_pages: int = 1,
    ) -> InlineKeyboardMarkup:
        keyboard: List[List[InlineKeyboardButton]] = [
            [InlineKeyboardButton(text="➕ Add Group", callback_data="gain_alerts:chart_groups:add")]
        ]

        buttons: List[InlineKeyboardButton] = []
        for group in groups:
            chat_id = group.get("chat_id")
            label = group.get("label")
            if label:
                trimmed = label if len(label) <= 14 else label[:11] + "..."
                button_text = f"🗑️ {trimmed}"
            else:
                button_text = f"🗑️ {chat_id}"

            buttons.append(
                InlineKeyboardButton(text=button_text, callback_data=f"gain_alerts:chart_groups:remove:{chat_id}")
            )

        keyboard.extend(Keyboards._chunk_buttons(buttons, 2))

        if total_pages > 1:
            nav_buttons: List[InlineKeyboardButton] = []
            if page > 1:
                nav_buttons.append(
                    InlineKeyboardButton(text="⬅️ Prev", callback_data=f"gain_alerts:chart_groups:page:{page-1}")
                )
            nav_buttons.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav_buttons.append(
                    InlineKeyboardButton(text="Next ➡️", callback_data=f"gain_alerts:chart_groups:page:{page+1}")
                )
            keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="gain_alerts:menu")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def settings_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 Gain Alerts", callback_data="gain_alerts:menu")],
            [InlineKeyboardButton(text="🌙 Gain Alert Settings", callback_data="settings:gain_alerts")],
            [InlineKeyboardButton(text="📊 Token Status", callback_data="settings:token_status")],
            [InlineKeyboardButton(text="🤖 AutoTrader", callback_data="settings:autotrader")],
            [InlineKeyboardButton(text="⚠️ AutoTrader Errors", callback_data="settings:autotrader_errors")],
            [InlineKeyboardButton(text="🏆 Rank", callback_data="cmd_fwd:list")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="menu:main")],
        ])

    @staticmethod
    def back_to_settings() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Settings", callback_data="settings:main")],
        ])

    @staticmethod
    def autotrader_destinations() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📨 Send Here", callback_data="autotrader:dest:here"),
                InlineKeyboardButton(text="🙋‍♂️ DM Me", callback_data="autotrader:dest:dm"),
            ],
            [InlineKeyboardButton(text="🔢 Custom Chat ID", callback_data="autotrader:dest:custom")],
            [InlineKeyboardButton(text="🔙 Cancel", callback_data="settings:main")],
        ])

    @staticmethod
    def autotrader_coin_cap() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="50", callback_data="autotrader:cap:50"),
                InlineKeyboardButton(text="100", callback_data="autotrader:cap:100"),
                InlineKeyboardButton(text="200", callback_data="autotrader:cap:200"),
            ],
            [InlineKeyboardButton(text="🔢 Custom", callback_data="autotrader:cap:custom")],
            [InlineKeyboardButton(text="⏭️ Skip (use default 100)", callback_data="autotrader:cap:skip")],
        ])

    @staticmethod
    def autotrader_channel_mode() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Single", callback_data="autotrader:mode:single"),
                InlineKeyboardButton(text="Multi", callback_data="autotrader:mode:multi"),
                InlineKeyboardButton(text="All", callback_data="autotrader:mode:all"),
            ],
        ])

    @staticmethod
    def autotrader_interval() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="60 min", callback_data="autotrader:interval:60"),
                InlineKeyboardButton(text="240 min", callback_data="autotrader:interval:240"),
            ],
            [InlineKeyboardButton(text="🔢 Custom", callback_data="autotrader:interval:custom")],
            [InlineKeyboardButton(text="⏭️ Skip", callback_data="autotrader:interval:skip")],
        ])

    @staticmethod
    def autotrader_channels_list(options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
        buttons = []
        for label, cb in options:
            buttons.append([InlineKeyboardButton(text=label, callback_data=cb)])
        buttons.append([InlineKeyboardButton(text="All Sources", callback_data="autotrader:channels:all")])
        buttons.append([InlineKeyboardButton(text="🔢 Custom", callback_data="autotrader:channels:custom")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    @staticmethod
    def autotrader_errors_nav(page: int, total_pages: int) -> InlineKeyboardMarkup:
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"settings:autotrader_errors:page:{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton(text="➡️ Next", callback_data=f"settings:autotrader_errors:page:{page+1}"))
        rows = [buttons] if buttons else []
        rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="settings:main")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

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
    def scheduler_overview_navigation(page: int, total_pages: int) -> InlineKeyboardMarkup:
        keyboard = []
        if total_pages > 1:
            nav_buttons = []
            if page > 1:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="⬅️ Prev",
                        callback_data=f"settings:scheduler_overview:page:{page-1}",
                    )
                )
            nav_buttons.append(
                InlineKeyboardButton(
                    text=f"{page}/{total_pages}",
                    callback_data="noop",
                )
            )
            if page < total_pages:
                nav_buttons.append(
                    InlineKeyboardButton(
                        text="Next ➡️",
                        callback_data=f"settings:scheduler_overview:page:{page+1}",
                    )
                )
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
    def cmd_fwd_rules_list(rules: List[Dict]) -> InlineKeyboardMarkup:
        keyboard = []
        for rule in rules[:10]:
            status = "✅" if rule["enabled"] else "❌"
            schedule_status = "⏰" if rule.get("schedule_enabled") else ""
            dest_title = rule.get("destination_channel_title", f"ID:{rule['destination_channel_id']}")
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status}{schedule_status} {rule['command_text']} → {dest_title}",
                    callback_data=f"cmd_fwd:view:{rule['id']}"
                )
            ])

        keyboard.append([InlineKeyboardButton(text="➕ Add New Rank Rule", callback_data="cmd_fwd:add")])
        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="settings:main")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_rule_details_menu(rule: Dict) -> InlineKeyboardMarkup:
        status_btn = InlineKeyboardButton(
            text="🔴 Disable" if rule["enabled"] else "🟢 Enable",
            callback_data=f"cmd_fwd:toggle:{rule['id']}"
        )
        schedule_btn = InlineKeyboardButton(
            text="⏰ Disable Schedule" if rule.get("schedule_enabled") else "⏰ Enable Schedule",
            callback_data=f"cmd_fwd:toggle_schedule:{rule['id']}"
        )
        timestamp_btn = InlineKeyboardButton(
            text="🕒 Disable Timestamp" if rule.get("post_timestamp") else "🕒 Enable Timestamp",
            callback_data=f"cmd_fwd:toggle_timestamp:{rule['id']}"
        )

        keyboard = [
            [status_btn],
            [schedule_btn],
            [timestamp_btn],
        ]

        if rule.get("post_timestamp"):
            timezone = rule.get("timestamp_timezone", "IST")
            timezone_btn = InlineKeyboardButton(
                text=f"🌍 Timezone: {timezone}",
                callback_data=f"cmd_fwd:set_timezone:{rule['id']}"
            )
            keyboard.append([timezone_btn])

        keyboard.extend([
            [
                InlineKeyboardButton(text="🧪 Test Rule", callback_data=f"cmd_fwd:test:{rule['id']}"),
            ],
            [
                InlineKeyboardButton(text="👥 Manage Command Users", callback_data=f"cmd_fwd:manage_command_users:{rule['id']}"),
                InlineKeyboardButton(text="👥 Manage Reply Users", callback_data=f"cmd_fwd:manage_reply_users:{rule['id']}"),
            ],
            [
                InlineKeyboardButton(text="🤖 Set Forwarding Bot", callback_data=f"cmd_fwd:set_fwd_bot:{rule['id']}"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Schedule Settings", callback_data=f"cmd_fwd:schedule_settings:{rule['id']}"),
                InlineKeyboardButton(text="🔇 Ignore Messages", callback_data=f"cmd_fwd:manage_excluded:{rule['id']}"),
            ],
            [
                InlineKeyboardButton(text="🗑️ Delete Rule", callback_data=f"cmd_fwd:delete:{rule['id']}"),
            ],
            [
                InlineKeyboardButton(text="🔙 Back to List", callback_data="cmd_fwd:list"),
            ],
        ])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_timezone_selection_keyboard(rule_id: int, current_tz: str) -> InlineKeyboardMarkup:
        timezones = [
            ("IST", "IST"),
            ("UTC", "UTC"),
            ("GMT", "GMT"),
            ("EST", "EST"),
            ("CST", "CST"),
            ("PST", "PST"),
            ("JST", "JST"),
            ("AEST", "AEST"),
            ("CET", "CET"),
        ]
        keyboard = []
        row = []
        for tz_code, tz_label in timezones:
            label = f"✅ {tz_label}" if tz_code == current_tz else tz_label
            row.append(
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"cmd_fwd:select_timezone:{rule_id}:{tz_code}"
                )
            )
            if len(row) == 3:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data=f"cmd_fwd:view:{rule_id}")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_select_source_group_keyboard(groups: List[Dict]) -> InlineKeyboardMarkup:
        keyboard = []
        for group in groups:
            display_name = group.get("display_name") or group.get("title") or str(group.get("tg_chat_id"))
            keyboard.append([
                InlineKeyboardButton(
                    text=display_name,
                    callback_data=f"cmd_fwd:wizard_source_group:{group['id']}"
                )
            ])

        keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cmd_fwd:list")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_manage_users_keyboard(user_ids: List[int], user_type: str, rule_id: int = None) -> InlineKeyboardMarkup:
        keyboard = []
        for user_id in user_ids:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑️ Remove {user_id}",
                    callback_data=f"cmd_fwd:wizard_remove_{user_type}:{user_id}"
                )
            ])

        add_callback = f"cmd_fwd:wizard_add_{user_type}"
        keyboard.append([InlineKeyboardButton(text="➕ Add User ID(s)", callback_data=add_callback)])

        if rule_id:
            keyboard.append([InlineKeyboardButton(text="🔙 Back to Rule", callback_data=f"cmd_fwd:view:{rule_id}")])
        else:
            if user_type == "monitored":
                next_callback = "cmd_fwd:wizard_next_to_fwd_bot"
            elif user_type == "replying":
                next_callback = "cmd_fwd:wizard_next_to_schedule"
            else:
                next_callback = "cmd_fwd:wizard_next_to_destination"
            keyboard.append([InlineKeyboardButton(text="Next ➡️", callback_data=next_callback)])
            keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cmd_fwd:list")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_select_forwarding_bot_keyboard(userbots: List[Dict]) -> InlineKeyboardMarkup:
        keyboard = []
        for bot in userbots:
            name = bot.get("display_name") or bot.get("session_name")
            keyboard.append([
                InlineKeyboardButton(
                    text=name,
                    callback_data=f"cmd_fwd:wizard_fwd_bot:{bot['id']}"
                )
            ])

        keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cmd_fwd:list")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_schedule_options_keyboard() -> InlineKeyboardMarkup:
        keyboard = [
            [InlineKeyboardButton(text="❌ No Schedule (Manual only)", callback_data="cmd_fwd:wizard_schedule:none")],
            [InlineKeyboardButton(text="⏰ Every 1 hour", callback_data="cmd_fwd:wizard_schedule:60")],
            [InlineKeyboardButton(text="⏰ Every 6 hours", callback_data="cmd_fwd:wizard_schedule:360")],
            [InlineKeyboardButton(text="⏰ Every 24 hours", callback_data="cmd_fwd:wizard_schedule:1440")],
            [InlineKeyboardButton(text="⚙️ Custom Interval", callback_data="cmd_fwd:wizard_schedule:custom")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cmd_fwd:list")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_confirm_delete(rule_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Yes, Delete", callback_data=f"cmd_fwd:confirm_delete:{rule_id}"),
                    InlineKeyboardButton(text="❌ Cancel", callback_data=f"cmd_fwd:view:{rule_id}"),
                ]
            ]
        )

    @staticmethod
    def cmd_fwd_rule_summary_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Save Rule", callback_data="cmd_fwd:wizard_save")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="cmd_fwd:list")],
            ]
        )

    @staticmethod
    def cmd_fwd_excluded_messages_keyboard(excluded_texts: List[str], rule_id: int) -> InlineKeyboardMarkup:
        keyboard = []
        for i, exc_text in enumerate(excluded_texts):
            display_text = exc_text if len(exc_text) <= 40 else f"{exc_text[:37]}..."
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗑️ Remove \"{display_text}\"",
                    callback_data=f"cmd_fwd:remove_excluded:{rule_id}:{i}"
                )
            ])

        keyboard.append([InlineKeyboardButton(text="➕ Add Excluded Text", callback_data=f"cmd_fwd:add_excluded:{rule_id}")])
        keyboard.append([InlineKeyboardButton(text="🔙 Back to Rule", callback_data=f"cmd_fwd:view:{rule_id}")])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def cmd_fwd_rule_details_text(rule: Dict, source_group: Dict, dest_channel_info: Dict, fwd_bot: Dict) -> str:
        status = "✅ Enabled" if rule["enabled"] else "❌ Disabled"
        schedule_status = "✅ Enabled" if rule.get("schedule_enabled") else "❌ Disabled"

        source_title = source_group["title"] if source_group else "N/A"
        dest_title = dest_channel_info["title"]
        bot_name = (fwd_bot.get("display_name") or fwd_bot.get("session_name")) if fwd_bot else "Not Set"

        command_users = rule.get("allowed_command_user_ids", []) or []
        reply_users = rule.get("allowed_reply_user_ids", []) or []

        text = (
            f"<b>🏆 Rank Rule Details</b>\n\n"
            f"<b>Status: {status}</b>\n"
            f"<b>Schedule: {schedule_status}</b>\n\n"
            f"<b>Command:</b>\n"
            f"  └ {rule['command_text']}\n\n"
            f"<b>Source Group:</b>\n"
            f"  └ {source_title}\n\n"
            f"<b>Destination Channel:</b>\n"
            f"  └ {dest_title}\n\n"
            f"<b>Forwarding Userbot:</b>\n"
            f"  └ {bot_name}\n\n"
            f"<b>Permissions:</b>\n"
            f"  ├ <b>Command Users:</b> {len(command_users) if command_users else 'Anyone'}\n"
            f"  └ <b>Reply Users:</b> {len(reply_users) if reply_users else 'Anyone'}"
        )

        if rule.get("schedule_enabled") and rule.get("schedule_interval_minutes"):
            hours = rule["schedule_interval_minutes"] // 60
            minutes = rule["schedule_interval_minutes"] % 60
            if hours > 0:
                interval_text = f"{hours}h {minutes}m" if minutes > 0 else f"{hours}h"
            else:
                interval_text = f"{minutes}m"
            text += f"\n\n<b>Schedule:</b>\n  └ Every {interval_text}"

            if rule.get("next_scheduled_at"):
                text += f"\n  └ Next: {rule['next_scheduled_at'].strftime('%Y-%m-%d %H:%M UTC')}"

        timestamp_status = "✅ Enabled" if rule.get("post_timestamp") else "❌ Disabled"
        text += f"\n\n<b>Timestamp Posting: {timestamp_status}</b>"
        if rule.get("post_timestamp"):
            timezone = rule.get("timestamp_timezone", "IST")
            text += f"\n  └ Timezone: {timezone}"

        return text

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
