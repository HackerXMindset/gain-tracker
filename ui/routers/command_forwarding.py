"""
Command forwarding routing module.
"""

from aiogram import Dispatcher, F

from config import settings
from ui.handlers.command_forwarding import CommandForwardingHandler
from ui.states import ManagementStates


def register(dispatcher: Dispatcher, handler: CommandForwardingHandler) -> None:
    """Register command forwarding handlers."""

    dispatcher.callback_query.register(
        handler.handle_cmd_fwd_action,
        F.data.startswith("cmd_fwd:"),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.wizard_process_command_input,
        ManagementStates.cmd_fwd_add_rule_command,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.wizard_process_user_id_input,
        ManagementStates.cmd_fwd_add_monitored_user_id,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.wizard_process_destination_input,
        ManagementStates.cmd_fwd_add_rule_destination,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.wizard_process_user_id_input,
        ManagementStates.cmd_fwd_add_replying_user_id,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.wizard_process_custom_interval_input,
        ManagementStates.cmd_fwd_add_rule_custom_interval,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.process_edit_command_input,
        ManagementStates.cmd_fwd_edit_command,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    dispatcher.message.register(
        handler.process_excluded_text_input,
        ManagementStates.cmd_fwd_add_excluded_text,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
