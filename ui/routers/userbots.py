"""
Userbot management routing module.
"""

from aiogram import Dispatcher, F
from aiogram.filters import StateFilter

from config import settings
from ui.handlers.userbots import UserbotsHandler
from ui.states import AdminStates


def register(dispatcher: Dispatcher, handler: UserbotsHandler) -> None:
    admin_filter = F.from_user.id.in_(settings.admin_telegram_ids_list)

    dispatcher.callback_query.register(
        handler.show_userbots_menu,
        F.data == "menu:userbots",
        admin_filter,
    )

    dispatcher.callback_query.register(
        handler.handle_userbot_action,
        F.data.startswith(("userbot:", "userbots_page:")),
        admin_filter,
    )

    dispatcher.message.register(
        handler.process_phone_input,
        StateFilter(AdminStates.userbot_login_phone),
        admin_filter,
    )

    dispatcher.message.register(
        handler.process_code_input,
        StateFilter(AdminStates.userbot_login_code),
        admin_filter,
    )

    dispatcher.message.register(
        handler.process_2fa_input,
        StateFilter(AdminStates.userbot_login_2fa),
        admin_filter,
    )

    dispatcher.message.register(
        handler.process_userbot_name_input,
        StateFilter(AdminStates.userbot_set_name),
        admin_filter,
    )
