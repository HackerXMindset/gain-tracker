from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from ui.states import InvestStates

if TYPE_CHECKING:
    from ui.handlers.invest import InvestHandler
    from config.settings import Settings

logger = logging.getLogger(__name__)


def get_invest_router(
    handler: InvestHandler,
    settings: "Settings",
) -> Router:
    """Create and configure the router for investment simulation."""
    router = Router()

    # /invest command entry point
    async def cmd_invest(message: types.Message, state: FSMContext) -> None:
        await handler.start_simulation(message, state)

    router.message.register(
        cmd_invest,
        Command(commands=["invest", "sim"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    # Cancel button handler
    async def handle_cancel(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_cancel(query, state)

    router.callback_query.register(
        handle_cancel,
        F.data == "invest:cancel",
    )

    # Source selection handlers
    async def handle_source_all(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_source_all(query, state)

    router.callback_query.register(
        handle_source_all,
        F.data == "invest:source:all",
        InvestStates.selecting_source,
    )

    async def handle_source_select(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_source_select(query, state)

    router.callback_query.register(
        handle_source_select,
        F.data == "invest:source:select",
        InvestStates.selecting_source,
    )

    async def handle_source_id_selected(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_source_id_selected(query, state)

    router.callback_query.register(
        handle_source_id_selected,
        F.data.startswith("invest:source:id:"),
        InvestStates.selecting_source,
    )

    async def handle_source_page(query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            page = int(query.data.split(":")[-1])
        except ValueError:
            page = 1
        await handler.handle_source_page(query, state, page=page)

    router.callback_query.register(
        handle_source_page,
        F.data.startswith("invest:source:page:"),
        InvestStates.selecting_source,
    )

    async def handle_back_to_source_menu(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_back_to_source_menu(query, state)

    router.callback_query.register(
        handle_back_to_source_menu,
        F.data == "invest:back:source_menu",
        InvestStates.selecting_source,
    )
    router.callback_query.register(
        handle_back_to_source_menu,
        F.data == "invest:back:source_menu",
        InvestStates.selecting_user_scope,
    )

    # User scope selection handlers (groups)
    async def handle_user_scope_all(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_user_scope_all(query, state)

    router.callback_query.register(
        handle_user_scope_all,
        F.data == "invest:users:all",
        InvestStates.selecting_user_scope,
    )

    async def handle_user_scope_select(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_user_scope_select(query, state)

    router.callback_query.register(
        handle_user_scope_select,
        F.data == "invest:users:select",
        InvestStates.selecting_user_scope,
    )

    async def handle_users_page(query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            page = int(query.data.split(":")[-1])
        except ValueError:
            page = 1
        await handler.handle_users_page(query, state, page=page)

    router.callback_query.register(
        handle_users_page,
        F.data.startswith("invest:users:page:"),
        InvestStates.selecting_users,
    )

    async def handle_users_toggle(query: types.CallbackQuery, state: FSMContext) -> None:
        try:
            _, _, _, user_id_str, _, page_str = query.data.split(":")
            user_id = int(user_id_str)
            page = int(page_str)
        except (ValueError, IndexError):
            await query.answer("Invalid selection.")
            return
        await handler.handle_users_toggle(query, state, user_id=user_id, page=page)

    router.callback_query.register(
        handle_users_toggle,
        F.data.startswith("invest:users:toggle:"),
        InvestStates.selecting_users,
    )

    async def handle_users_done(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_users_done(query, state)

    router.callback_query.register(
        handle_users_done,
        F.data == "invest:users:done",
        InvestStates.selecting_users,
    )

    async def handle_users_clear(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_users_clear(query, state)

    router.callback_query.register(
        handle_users_clear,
        F.data == "invest:users:clear",
        InvestStates.selecting_users,
    )

    async def handle_users_back(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_users_back(query, state)

    router.callback_query.register(
        handle_users_back,
        F.data == "invest:users:back",
        InvestStates.selecting_users,
    )

    # Timeframe selection handlers
    async def handle_timeframe_selection(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_timeframe_selection(query, state)

    router.callback_query.register(
        handle_timeframe_selection,
        F.data.startswith("invest:timeframe:"),
        InvestStates.selecting_timeframe,
    )

    async def handle_back_to_source(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_back_to_source(query, state)

    router.callback_query.register(
        handle_back_to_source,
        F.data == "invest:back:source",
        InvestStates.selecting_timeframe,
    )

    # Hold strategy selection handlers
    async def handle_hold_strategy(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_hold_strategy(query, state)

    router.callback_query.register(
        handle_hold_strategy,
        F.data.startswith("invest:hold:"),
        InvestStates.selecting_hold,
    )

    async def handle_back_to_timeframe(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_back_to_timeframe(query, state)

    router.callback_query.register(
        handle_back_to_timeframe,
        F.data == "invest:back:timeframe",
        InvestStates.selecting_hold,
    )

    async def handle_back_to_hold(query: types.CallbackQuery, state: FSMContext) -> None:
        await handler.handle_back_to_hold(query, state)

    router.callback_query.register(
        handle_back_to_hold,
        F.data == "invest:back:hold",
        InvestStates.selecting_hold,
    )

    # Custom input handlers
    async def handle_custom_timeframe_input(message: types.Message, state: FSMContext) -> None:
        await handler.handle_custom_timeframe_input(message, state)

    router.message.register(
        handle_custom_timeframe_input,
        InvestStates.entering_custom_tokens,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    async def handle_custom_hold_input(message: types.Message, state: FSMContext) -> None:
        await handler.handle_custom_hold_input(message, state)

    router.message.register(
        handle_custom_hold_input,
        InvestStates.entering_custom_hold,
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    return router
