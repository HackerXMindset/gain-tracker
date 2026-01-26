"""
Router bindings for gain alerts admin UI.
"""

from __future__ import annotations

from aiogram import Dispatcher, F
from aiogram.filters import StateFilter

from ui.handlers.gain_alerts import GainAlertsHandler
from ui.states import AdminStates


def register(dp: Dispatcher, handler: GainAlertsHandler) -> None:
    async def handle_add_type(query, state) -> None:
        await handler.handle_type_selected(query, state, query.data.split(":")[-1])

    async def show_source_detail(query) -> None:
        await handler.show_source_detail(query, int(query.data.split(":")[-1]))

    async def chart_groups_callback(query, state) -> None:
        parts = query.data.split(":")

        if len(parts) == 3 and parts[2] == "menu":
            await handler.show_chart_groups_menu(query)
            return

        if len(parts) == 3 and parts[2] == "add":
            await handler.start_add_chart_group_menu(query, state)
            return

        if len(parts) == 3 and parts[2] == "cancel":
            await handler.cancel_chart_groups(query, state)
            return

        if len(parts) == 4 and parts[2] == "page":
            try:
                page = int(parts[3])
            except ValueError:
                await query.answer("❌ Invalid page.", show_alert=True)
                return
            await handler.show_chart_groups_menu(query, page=page)
            return

        if len(parts) == 4 and parts[2] == "remove":
            try:
                chat_id = int(parts[3])
            except ValueError:
                await query.answer("❌ Invalid chat ID.", show_alert=True)
                return
            await handler.remove_chart_group(query, chat_id)
            return

        await query.answer("❌ Invalid selection.", show_alert=True)

    async def toggle_source_enabled(query) -> None:
        await handler.toggle_source_enabled(query, int(query.data.split(":")[-1]))

    async def start_edit_name(query, state) -> None:
        await handler.start_edit_name(query, state, int(query.data.split(":")[-1]))

    async def start_sensitivity_custom(query, state) -> None:
        await handler.start_sensitivity_custom(query, state, int(query.data.split(":")[-1]))

    async def show_sensitivity_menu(query) -> None:
        await handler.start_sensitivity_menu(query, int(query.data.split(":")[-1]))

    async def set_sensitivity_value(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 6:
            await query.answer("❌ Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[4])
        except ValueError:
            await query.answer("❌ Invalid identifier.", show_alert=True)
            return
        raw_value = parts[5] if len(parts) >= 6 else None
        await handler.set_sensitivity_value(query, chat_id, raw_value)

    async def start_edit_template(query, state) -> None:
        await handler.start_edit_template(query, state, int(query.data.split(":")[-1]))

    async def toggle_sender(query) -> None:
        await handler.toggle_sender(query, int(query.data.split(":")[-1]))

    async def show_userbot_menu(query) -> None:
        await handler.start_userbot_menu(query, int(query.data.split(":")[-1]), page=1)

    async def set_userbot_assignment(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 6:
            await query.answer("❌ Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[4])
        except ValueError:
            await query.answer("❌ Invalid identifier.", show_alert=True)
            return
        raw_userbot_id = parts[5] if len(parts) >= 6 else None
        await handler.set_userbot_assignment(query, chat_id, raw_userbot_id)

    async def paginate_userbots(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 6:
            await query.answer("❌ Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[4])
            page = int(parts[5])
        except ValueError:
            await query.answer("❌ Invalid identifier.", show_alert=True)
            return
        await handler.start_userbot_menu(query, chat_id, page=page)

    async def show_chart_settings(query) -> None:
        await handler.show_chart_settings(query, int(query.data.split(":")[-1]))

    async def toggle_chart_enabled(query) -> None:
        await handler.toggle_chart_enabled(query, int(query.data.split(":")[-1]))

    async def start_edit_chart_threshold(query, state) -> None:
        await handler.start_edit_chart_threshold(query, state, int(query.data.split(":")[-1]))

    async def start_edit_chart_bot(query, state) -> None:
        await handler.start_edit_chart_bot(query, state, int(query.data.split(":")[-1]))

    async def edit_guardrail_override(query, state) -> None:
        parts = query.data.split(":")
        if len(parts) < 4:
            await query.answer("❌ Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[2])
        except ValueError:
            await query.answer("❌ Invalid identifier.", show_alert=True)
            return
        metric = parts[3]
        await handler.prompt_edit_source_guardrail(query, state, chat_id, metric)

    async def reset_guardrail_override(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 4:
            await query.answer("❌ Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[2])
        except ValueError:
            await query.answer("❌ Invalid identifier.", show_alert=True)
            return
        metric = parts[3]
        await handler.reset_source_guardrail(query, chat_id, metric)

    async def cancel_chart_settings(query, state) -> None:
        parts = query.data.split(":")
        if len(parts) < 4:
            await query.answer("❌ Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[3])
        except ValueError:
            await query.answer("❌ Invalid identifier.", show_alert=True)
            return
        await handler.cancel_chart_settings(query, state, chat_id)

    async def show_tracked_users(query) -> None:
        parts = query.data.split(":")
        chat_id = int(parts[3])
        page = 1
        if len(parts) >= 6 and parts[4] == "page":
            try:
                page = int(parts[5])
            except ValueError:
                page = 1
        await handler.show_tracked_users(query, chat_id, page=page)

    async def remove_user(query) -> None:
        await handler.remove_user(query, int(query.data.split(":")[-1]))

    async def toggle_exclude_user(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 5:
            await query.answer("Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[3])
            user_id = int(parts[4])
        except ValueError:
            await query.answer("Invalid identifier.", show_alert=True)
            return
        page = 1
        if len(parts) >= 7 and parts[5] == "page":
            try:
                page = int(parts[6])
            except ValueError:
                page = 1
        await handler.toggle_user_exclusion(query, chat_id, user_id, page=page)

    async def toggle_track_all(query) -> None:
        await handler.toggle_track_all_users(query, int(query.data.split(":")[-1]))

    async def start_remove_chat(query) -> None:
        await handler.start_remove_chat(query, int(query.data.split(":")[-1]))

    async def confirm_remove_chat(query) -> None:
        await handler.confirm_remove_chat(query, int(query.data.split(":")[-1]))

    async def show_main_menu(query, state) -> None:
        await handler.show_main_menu(query, state)

    async def show_main_menu_page(query, state) -> None:
        parts = query.data.split(":")
        if len(parts) < 4:
            await handler.show_main_menu(query, state)
            return
        try:
            page = int(parts[3])
        except ValueError:
            page = 1
        await handler.show_main_menu(query, state, page=page)

    dp.callback_query.register(show_main_menu, F.data == "gain_alerts:menu")
    dp.callback_query.register(show_main_menu_page, F.data.startswith("gain_alerts:menu:page:"))
    dp.callback_query.register(handler.start_add_flow, F.data == "gain_alerts:add")
    dp.callback_query.register(handle_add_type, F.data.startswith("gain_alerts:add:type:"))
    dp.callback_query.register(handler.confirm_add, F.data == "gain_alerts:add:confirm")
    dp.callback_query.register(chart_groups_callback, F.data.startswith("gain_alerts:chart_groups:"))
    dp.callback_query.register(
        handler.cancel,
        F.data == "gain_alerts:cancel",
        StateFilter(
            AdminStates.gain_alerts_add_type,
            AdminStates.gain_alerts_add_chat_id,
            AdminStates.gain_alerts_add_user_id,
            AdminStates.gain_alerts_confirm_add,
            AdminStates.gain_alerts_edit_name,
            AdminStates.gain_alerts_edit_sensitivity,
            AdminStates.gain_alerts_edit_template,
            AdminStates.gain_alerts_edit_sender,
            AdminStates.gain_alerts_edit_chart_threshold,
            AdminStates.gain_alerts_edit_chart_bot,
            AdminStates.gain_alerts_add_chart_group,
            AdminStates.gain_alerts_remove_chart_group,
            AdminStates.awaiting_source_guardrail_override,
        ),
    )

    dp.callback_query.register(show_source_detail, F.data.regexp(r"^gain_alerts:view:-?\d+$"))
    dp.callback_query.register(toggle_source_enabled, F.data.startswith("gain_alerts:view:toggle:"))
    dp.callback_query.register(start_edit_name, F.data.startswith("gain_alerts:view:edit_name:"))
    dp.callback_query.register(set_sensitivity_value, F.data.startswith("gain_alerts:view:sensitivity:set:"))
    dp.callback_query.register(start_sensitivity_custom, F.data.startswith("gain_alerts:view:sensitivity:custom:"))
    dp.callback_query.register(show_sensitivity_menu, F.data.regexp(r"^gain_alerts:view:sensitivity:-?\d+$"))
    dp.callback_query.register(start_edit_template, F.data.startswith("gain_alerts:view:template:"))
    dp.callback_query.register(toggle_sender, F.data.startswith("gain_alerts:view:sender_toggle:"))
    dp.callback_query.register(set_userbot_assignment, F.data.startswith("gain_alerts:view:userbot:set:"))
    dp.callback_query.register(paginate_userbots, F.data.startswith("gain_alerts:view:userbot:page:"))
    dp.callback_query.register(show_userbot_menu, F.data.regexp(r"^gain_alerts:view:userbot:-?\d+$"))

    async def show_tracking_menu(query) -> None:
        await handler.start_tracking_userbot_menu(query, int(query.data.split(":")[-1]), page=1)

    async def set_tracking_assignment(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 6:
            await query.answer("Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[4])
        except ValueError:
            await query.answer("Invalid identifier.", show_alert=True)
            return
        raw_userbot_id = parts[5] if len(parts) >= 6 else None
        await handler.set_tracking_userbot_assignment(query, chat_id, raw_userbot_id)

    async def toggle_tracking_fallback(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 5:
            await query.answer("Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[4])
        except ValueError:
            await query.answer("Invalid identifier.", show_alert=True)
            return
        await handler.toggle_tracking_fallback(query, chat_id)

    async def paginate_tracking(query) -> None:
        parts = query.data.split(":")
        if len(parts) < 6:
            await query.answer("Invalid selection.", show_alert=True)
            return
        try:
            chat_id = int(parts[4])
            page = int(parts[5])
        except ValueError:
            await query.answer("Invalid identifier.", show_alert=True)
            return
        await handler.start_tracking_userbot_menu(query, chat_id, page=page)

    dp.callback_query.register(set_tracking_assignment, F.data.startswith("gain_alerts:view:tracking:set:"))
    dp.callback_query.register(toggle_tracking_fallback, F.data.startswith("gain_alerts:view:tracking:fallback:"))
    dp.callback_query.register(paginate_tracking, F.data.startswith("gain_alerts:view:tracking:page:"))
    dp.callback_query.register(show_tracking_menu, F.data.regexp(r"^gain_alerts:view:tracking:-?\d+$"))

    async def show_source_stats(query) -> None:
        parts = query.data.split(":")
        chat_id = int(parts[3])
        timeframe = parts[4] if len(parts) > 4 else "24h"
        await handler.show_source_stats(query, chat_id, timeframe)

    dp.callback_query.register(show_source_stats, F.data.startswith("gain_alerts:view:stats:"))
    dp.callback_query.register(show_chart_settings, F.data.regexp(r"^gain_alerts:view:chart:-?\d+$"))
    dp.callback_query.register(toggle_chart_enabled, F.data.startswith("gain_alerts:view:chart:toggle:"))
    dp.callback_query.register(start_edit_chart_threshold, F.data.startswith("gain_alerts:view:chart:threshold:"))
    dp.callback_query.register(start_edit_chart_bot, F.data.startswith("gain_alerts:view:chart:bot:"))
    dp.callback_query.register(edit_guardrail_override, F.data.startswith("gain_alerts:edit_override:"))
    dp.callback_query.register(reset_guardrail_override, F.data.startswith("gain_alerts:reset_override:"))
    dp.callback_query.register(cancel_chart_settings, F.data.startswith("gain_alerts:chart_settings:cancel:"))
    dp.callback_query.register(show_tracked_users, F.data.startswith("gain_alerts:view:users:"))
    dp.callback_query.register(remove_user, F.data.startswith("gain_alerts:view:remove_user:"))
    dp.callback_query.register(toggle_exclude_user, F.data.startswith("gain_alerts:view:exclude_user:"))
    dp.callback_query.register(toggle_track_all, F.data.startswith("gain_alerts:view:track_all:"))
    dp.callback_query.register(
        start_remove_chat,
        F.data.startswith("gain_alerts:view:remove_chat:") & ~F.data.contains("confirm"),
    )
    dp.callback_query.register(confirm_remove_chat, F.data.startswith("gain_alerts:view:remove_chat:confirm:"))

    dp.message.register(handler.handle_chat_id_input, StateFilter(AdminStates.gain_alerts_add_chat_id))
    dp.message.register(handler.handle_user_id_input, StateFilter(AdminStates.gain_alerts_add_user_id))
    dp.message.register(handler.handle_edit_name_input, StateFilter(AdminStates.gain_alerts_edit_name))
    dp.message.register(handler.handle_edit_sensitivity_input, StateFilter(AdminStates.gain_alerts_edit_sensitivity))
    dp.message.register(handler.handle_edit_template_input, StateFilter(AdminStates.gain_alerts_edit_template))
    dp.message.register(handler.handle_edit_chart_threshold_input, StateFilter(AdminStates.gain_alerts_edit_chart_threshold))
    dp.message.register(handler.handle_edit_chart_bot_input, StateFilter(AdminStates.gain_alerts_edit_chart_bot))
    dp.message.register(handler.handle_add_chart_group_input, StateFilter(AdminStates.gain_alerts_add_chart_group))
    dp.message.register(handler.handle_remove_chart_group_input, StateFilter(AdminStates.gain_alerts_remove_chart_group))
    dp.message.register(handler.handle_chart_group_input, StateFilter(AdminStates.chart_groups_add_chat_id))
    dp.message.register(handler.save_source_guardrail, StateFilter(AdminStates.awaiting_source_guardrail_override))
