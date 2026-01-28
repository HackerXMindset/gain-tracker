"""
UI Router for Settings.
"""

from aiogram import Dispatcher, F
from aiogram.filters import StateFilter

from config import settings
from ui.handlers.settings import SettingsHandler
from ui.states import AdminStates, AutoTraderStates


def register(dispatcher: Dispatcher, handler: SettingsHandler) -> None:
    admin_filter = F.from_user.id.in_(settings.admin_telegram_ids_list)

    dispatcher.callback_query.register(
        handler.show_settings_menu,
        F.data.startswith("settings:main"),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.show_gain_alert_settings,
        F.data.startswith("settings:gain_alerts"),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.prompt_edit_gain_threshold,
        F.data.startswith("settings:edit_gain_threshold"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_gain_threshold,
        StateFilter(AdminStates.awaiting_gain_threshold),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.prompt_edit_drop_threshold,
        F.data.startswith("settings:edit_drop_threshold"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_drop_threshold,
        StateFilter(AdminStates.awaiting_drop_threshold),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.prompt_edit_drop_floor,
        F.data.startswith("settings:edit_drop_floor"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_drop_floor,
        StateFilter(AdminStates.awaiting_drop_floor),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.prompt_edit_chart_threshold,
        F.data.startswith("settings:edit_chart_threshold"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_chart_threshold,
        StateFilter(AdminStates.awaiting_global_chart_threshold),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.prompt_edit_chart_bot,
        F.data.startswith("settings:edit_chart_bot"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_chart_bot,
        StateFilter(AdminStates.awaiting_global_chart_bot),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.prompt_edit_gain_template,
        F.data.startswith("settings:edit_gain_template"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_gain_template,
        StateFilter(AdminStates.awaiting_gain_template),
        admin_filter,
    )

    async def edit_guardrail_callback(query, state) -> None:
        metric = query.data.split(":")[-1]
        await handler.prompt_edit_guardrail(query, state, metric=metric)

    dispatcher.callback_query.register(
        edit_guardrail_callback,
        F.data.startswith("settings:edit_guardrail:"),
        admin_filter,
    )
    dispatcher.message.register(
        handler.save_guardrail_value,
        StateFilter(AdminStates.awaiting_guardrail_value),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.show_token_status_menu,
        F.data.startswith("settings:token_status"),
        admin_filter,
    )
    dispatcher.callback_query.register(
        handler.show_scheduler_overview,
        F.data.startswith("settings:scheduler_overview"),
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.show_autotrader_entry,
        F.data.startswith("settings:autotrader"),
        admin_filter,
    )
    dispatcher.callback_query.register(
        handler.autotrader_dest_here,
        F.data == "autotrader:dest:here",
        admin_filter,
    )
    dispatcher.callback_query.register(
        handler.autotrader_dest_dm,
        F.data == "autotrader:dest:dm",
        admin_filter,
    )
    dispatcher.callback_query.register(
        handler.autotrader_dest_custom,
        F.data == "autotrader:dest:custom",
        admin_filter,
    )
    dispatcher.callback_query.register(
        lambda q: handler.show_autotrader_errors(q, page=1),
        F.data == "settings:autotrader_errors",
        admin_filter,
    )
    dispatcher.callback_query.register(
        lambda q: handler.show_autotrader_errors(q, page=int(q.data.split(":")[-1])),
        F.data.startswith("settings:autotrader_errors:page:"),
        admin_filter,
    )
    dispatcher.callback_query.register(
        handler.show_autotrader_errors,
        F.data.startswith("settings:autotrader_errors"),
        admin_filter,
    )

    # AutoTrader FSM (simple linear wizard)
    dispatcher.message.register(
        handler.autotrader_get_destination,
        StateFilter(AutoTraderStates.awaiting_destination),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_budget,
        StateFilter(AutoTraderStates.awaiting_budget),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_per_coin,
        StateFilter(AutoTraderStates.awaiting_per_coin),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_hold,
        StateFilter(AutoTraderStates.awaiting_hold),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_coin_cap,
        StateFilter(AutoTraderStates.awaiting_coin_cap),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_channel_mode,
        StateFilter(AutoTraderStates.awaiting_channel_mode),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_channels,
        StateFilter(AutoTraderStates.awaiting_channels),
        admin_filter,
    )
    dispatcher.message.register(
        handler.autotrader_get_report_interval,
        StateFilter(AutoTraderStates.awaiting_report_interval),
        admin_filter,
    )

    async def tokens_list_callback(query) -> None:
        status = query.data.split(":")[-2]
        page = int(query.data.split(":")[-1])
        await handler.show_tokens_list(query, status=status, page=page)

    dispatcher.callback_query.register(
        tokens_list_callback,
        F.data.startswith("settings:tokens_list:"),
        admin_filter,
    )
