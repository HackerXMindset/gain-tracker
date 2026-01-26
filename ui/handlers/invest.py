from __future__ import annotations

import asyncio
import html
import logging
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Dict, List, Optional

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ui.states import InvestStates

if TYPE_CHECKING:
    from services.dexscreener_api import DexScreenerAPIClient
    from models.analytics import AnalyticsModel

logger = logging.getLogger(__name__)


class InvestHandler:
    def __init__(
        self,
        analytics_model: AnalyticsModel,
        dexscreener_api: DexScreenerAPIClient,
        source_model = None,
    ) -> None:
        self.analytics_model = analytics_model
        self.dexscreener_api = dexscreener_api
        self.source_model = source_model
        self._member_display_cache: Dict[tuple[int, int], str] = {}
        self._chat_title_cache: Dict[int, str] = {}

    def _build_source_selection_keyboard(self) -> types.InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="🌐 All Sources", callback_data="invest:source:all")
        builder.button(text="✍️ Select Source...", callback_data="invest:source:select")
        builder.button(text="❌ Cancel", callback_data="invest:cancel")
        builder.adjust(2)
        return builder.as_markup()

    def _build_user_scope_keyboard(self) -> types.InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="👥 All users", callback_data="invest:users:all")
        builder.button(text="👤 Select users", callback_data="invest:users:select")
        builder.button(text="⬅️ Back", callback_data="invest:back:source_menu")
        builder.button(text="❌ Cancel", callback_data="invest:cancel")
        builder.adjust(2)
        return builder.as_markup()

    async def start_simulation(self, message: types.Message, state: FSMContext) -> None:
        """Entry point for the /invest command."""
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "Please provide an investment amount.\n"
                "Usage: <code>/invest &lt;amount&gt;</code>\n"
                "Optional: <code>/invest &lt;amount&gt; &lt;chat_id&gt; [user:&lt;user_id&gt;] [hold] [period]</code>",
                parse_mode="HTML",
            )
            return

        try:
            amount = Decimal(parts[1])
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            await message.answer("Invalid amount. Please enter a positive number.")
            return

        if len(parts) > 2:
            parsed = self._parse_direct_args(parts[2:])
            if parsed.get("error"):
                await message.answer(parsed["error"], parse_mode="HTML")
                return
            if parsed.get("direct"):
                await message.answer("⏳ Running simulation, please wait...")
                try:
                    simulation_results = await self.analytics_model.simulate_investment(
                        amount=float(amount),
                        chat_id=parsed.get("chat_id"),
                        user_id=parsed.get("user_id"),
                        token_count=parsed.get("token_count"),
                        timeframe_hours=parsed.get("timeframe_hours"),
                        hold_strategy=parsed.get("hold_strategy", "peak"),
                        allocation="equal",
                    )
                    if simulation_results.get("error"):
                        await message.answer(f"❌ Simulation error: {simulation_results['error']}")
                        return
                    await self._attach_source_display_name(
                        message.bot,
                        simulation_results,
                        parsed.get("chat_id"),
                    )
                    formatted_results = self._format_simulation_results(simulation_results)
                    await message.answer(formatted_results, parse_mode="HTML")
                except Exception as exc:
                    logger.exception("Error during investment simulation: %s", exc)
                    await message.answer(
                        "❌ An unexpected error occurred during simulation. Please try again later."
                    )
                return

        await state.update_data(amount=float(amount))
        await state.set_state(InvestStates.selecting_source)

        await message.answer(
            f"💰 Simulating investment of <b>${amount:,.2f}</b>.\n\n"
            "First, choose the source of the calls to simulate:",
            reply_markup=self._build_source_selection_keyboard(),
        )

    async def handle_cancel(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await query.message.edit_text("❌ Investment simulation cancelled.")
        await query.answer()

    async def handle_source_all(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.update_data(chat_id=None, user_ids=None, selected_user_ids=[])
        await state.set_state(InvestStates.selecting_timeframe)
        await query.message.edit_text(
            "Next, choose the time period for selecting tokens:",
            reply_markup=self._build_timeframe_selection_keyboard(),
        )
        await query.answer()

    async def handle_source_select(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Show list of monitored sources to choose from."""
        if not self.source_model:
            await query.message.edit_text("Source selection is not available (source_model not initialized).")
            await query.answer()
            return

        await self._render_source_page(query, state, page=1)

    async def handle_source_page(self, query: types.CallbackQuery, state: FSMContext, page: int) -> None:
        await self._render_source_page(query, state, page=page)

    async def _render_source_page(self, query: types.CallbackQuery, state: FSMContext, page: int) -> None:
        sources = await self.source_model.get_all()

        if not sources:
            await query.message.edit_text("No monitored sources found. Using all sources instead.")
            await state.update_data(chat_id=None)
            await state.set_state(InvestStates.selecting_timeframe)
            await query.message.edit_text(
                "Next, choose the time period for selecting tokens:",
                reply_markup=self._build_timeframe_selection_keyboard(),
            )
            await query.answer()
            return

        page_size = 9
        total_pages = max(1, (len(sources) + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        start = (page - 1) * page_size
        end = start + page_size
        page_sources = sources[start:end]

        await query.message.edit_text(
            "Select a source:",
            reply_markup=self._build_source_list_keyboard(page_sources, page, total_pages),
        )
        await query.answer()

    def _build_source_list_keyboard(
        self,
        sources: list,
        page: int,
        total_pages: int,
    ) -> types.InlineKeyboardMarkup:
        """Build keyboard with list of sources."""
        rows: list[list[types.InlineKeyboardButton]] = []
        row_buffer: list[types.InlineKeyboardButton] = []

        for source in sources:
            chat_id = source.get("chat_id")
            display_name = source.get("display_name") or source.get("name") or f"Chat {chat_id}"
            if len(display_name) > 20:
                display_name = display_name[:17] + "..."
            row_buffer.append(
                types.InlineKeyboardButton(
                    text=display_name,
                    callback_data=f"invest:source:id:{chat_id}",
                )
            )
            if len(row_buffer) == 2:
                rows.append(row_buffer)
                row_buffer = []

        if row_buffer:
            rows.append(row_buffer)

        if total_pages > 1:
            nav_row: list[types.InlineKeyboardButton] = []
            if page > 1:
                nav_row.append(types.InlineKeyboardButton(text="⬅️ Prev", callback_data=f"invest:source:page:{page-1}"))
            nav_row.append(types.InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav_row.append(types.InlineKeyboardButton(text="Next ➡️", callback_data=f"invest:source:page:{page+1}"))
            rows.append(nav_row)

        rows.append([
            types.InlineKeyboardButton(text="⬅️ Back", callback_data="invest:back:source_menu"),
            types.InlineKeyboardButton(text="❌ Cancel", callback_data="invest:cancel"),
        ])

        return types.InlineKeyboardMarkup(inline_keyboard=rows)

    def _parse_direct_args(self, args: list[str]) -> dict:
        parsed = {
            "direct": True,
            "chat_id": None,
            "user_id": None,
            "token_count": None,
            "timeframe_hours": 24,
            "hold_strategy": "peak",
        }
        idx = 0
        hold_values = {"peak", "current", "1h", "6h", "24h"}
        timeframe_values = {"7d", "30d"}

        if args:
            first = args[0].lower()
            if first not in {"all", *hold_values, *timeframe_values}:
                try:
                    if ":" in first:
                        chat_raw, user_raw = first.split(":", 1)
                        parsed["chat_id"] = int(chat_raw)
                        parsed["user_id"] = int(user_raw)
                    else:
                        parsed["chat_id"] = int(first)
                    idx = 1
                except ValueError:
                    return {"error": "❌ Invalid chat_id. Use: /invest {amount} {chat_id} [user:{user_id}] [hold] [period]"}

        while idx < len(args):
            token = args[idx].lower()
            if token.startswith("user:"):
                try:
                    parsed["user_id"] = int(token.split(":", 1)[1])
                except ValueError:
                    return {"error": "❌ Invalid user_id. Use: /invest {amount} {chat_id} user:{user_id}"}
            elif token in hold_values:
                parsed["hold_strategy"] = token
            elif token in timeframe_values:
                parsed["timeframe_hours"] = 168 if token == "7d" else 720
            idx += 1

        return parsed

    async def handle_source_id_selected(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Handle when a specific source is selected."""
        chat_id = int(query.data.split(":")[-1])
        await state.update_data(chat_id=chat_id, user_ids=None, selected_user_ids=[])

        is_group = False
        if self.source_model:
            records = await self.source_model.get_by_chat(chat_id)
            is_group = any(record.get("chat_type") == "group" for record in records)

        if is_group:
            await state.set_state(InvestStates.selecting_user_scope)
            await query.message.edit_text(
                "This is a group. Scan calls from:",
                reply_markup=self._build_user_scope_keyboard(),
            )
            await query.answer()
            return

        await state.set_state(InvestStates.selecting_timeframe)
        await query.message.edit_text(
            "Next, choose the time period for selecting tokens:",
            reply_markup=self._build_timeframe_selection_keyboard(),
        )
        await query.answer()

    async def handle_user_scope_all(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.update_data(user_ids=None, selected_user_ids=[])
        await state.set_state(InvestStates.selecting_timeframe)
        await query.message.edit_text(
            "Next, choose the time period for selecting tokens:",
            reply_markup=self._build_timeframe_selection_keyboard(),
        )
        await query.answer()

    async def handle_user_scope_select(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.set_state(InvestStates.selecting_users)
        await self._render_user_page(query, state, page=1)

    async def handle_users_page(self, query: types.CallbackQuery, state: FSMContext, page: int) -> None:
        await self._render_user_page(query, state, page=page)

    async def handle_users_toggle(self, query: types.CallbackQuery, state: FSMContext, user_id: int, page: int) -> None:
        data = await state.get_data()
        selected = set(data.get("selected_user_ids") or [])
        if user_id in selected:
            selected.remove(user_id)
        else:
            selected.add(user_id)
        await state.update_data(selected_user_ids=list(selected))
        await self._render_user_page(query, state, page=page)

    async def handle_users_done(self, query: types.CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        selected = data.get("selected_user_ids") or []
        if not selected:
            await query.answer("Select at least one user.", show_alert=True)
            return
        await state.update_data(user_ids=selected)
        await state.set_state(InvestStates.selecting_timeframe)
        await query.message.edit_text(
            "Next, choose the time period for selecting tokens:",
            reply_markup=self._build_timeframe_selection_keyboard(),
        )
        await query.answer()

    async def handle_users_clear(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.update_data(selected_user_ids=[])
        await self._render_user_page(query, state, page=1)

    async def handle_users_back(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await state.set_state(InvestStates.selecting_user_scope)
        await query.message.edit_text(
            "This is a group. Scan calls from:",
            reply_markup=self._build_user_scope_keyboard(),
        )
        await query.answer()

    async def handle_back_to_source_menu(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Go back to the source selection menu."""
        await state.set_state(InvestStates.selecting_source)
        await query.message.edit_text(
            "Choose the source of the calls to simulate:",
            reply_markup=self._build_source_selection_keyboard(),
        )
        await query.answer()

    async def _render_user_page(self, query: types.CallbackQuery, state: FSMContext, page: int) -> None:
        data = await state.get_data()
        chat_id = data.get("chat_id")
        if chat_id is None:
            await query.message.edit_text("No chat selected. Please choose a source again.")
            await state.set_state(InvestStates.selecting_source)
            await query.answer()
            return

        total_users = await self.analytics_model.db.fetchval(
            """
            SELECT COUNT(DISTINCT original_user_id)
            FROM token_group_alerts
            WHERE chat_id = $1 AND original_user_id IS NOT NULL
            """,
            chat_id,
        ) or 0

        if total_users == 0:
            await query.message.edit_text(
                "No users recorded for this group yet.",
                reply_markup=self._build_user_scope_keyboard(),
            )
            await state.set_state(InvestStates.selecting_user_scope)
            await query.answer()
            return

        page_size = 9
        total_pages = max(1, (total_users + page_size - 1) // page_size)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * page_size

        rows = await self.analytics_model.db.fetch(
            """
            SELECT original_user_id AS user_id, COUNT(*) AS token_count
            FROM token_group_alerts
            WHERE chat_id = $1 AND original_user_id IS NOT NULL
            GROUP BY original_user_id
            ORDER BY token_count DESC
            LIMIT $2 OFFSET $3
            """,
            chat_id,
            page_size,
            offset,
        )

        user_ids = [int(row.get("user_id") or 0) for row in rows]
        user_map = await self._resolve_user_display_names(query.bot, chat_id, user_ids)

        users = []
        for row in rows:
            user_id = int(row.get("user_id") or 0)
            users.append(
                {
                    "user_id": user_id,
                    "token_count": int(row.get("token_count") or 0),
                    "display": user_map.get(user_id, str(user_id)),
                }
            )

        selected = set(data.get("selected_user_ids") or [])
        start_idx = offset + 1
        end_idx = min(offset + page_size, total_users)

        text = (
            "Select users to include in the simulation.\n"
            f"Selected: {len(selected)} | Showing {start_idx}-{end_idx} of {total_users}"
        )

        await query.message.edit_text(
            text,
            reply_markup=self._build_user_selection_keyboard(users, page, total_pages, selected),
        )
        await query.answer()

    def _build_user_selection_keyboard(
        self,
        users: List[Dict[str, object]],
        page: int,
        total_pages: int,
        selected: set,
    ) -> types.InlineKeyboardMarkup:
        rows: List[List[types.InlineKeyboardButton]] = []
        row_buffer: List[types.InlineKeyboardButton] = []

        for user in users:
            user_id = int(user["user_id"])
            display = str(user["display"])
            token_count = int(user["token_count"])
            marker = "✅" if user_id in selected else "⬜"
            display_short = display if len(display) <= 16 else display[:13] + "..."
            label = f"{marker} {display_short} {token_count}"
            row_buffer.append(
                types.InlineKeyboardButton(
                    text=label,
                    callback_data=f"invest:users:toggle:{user_id}:page:{page}",
                )
            )
            if len(row_buffer) == 2:
                rows.append(row_buffer)
                row_buffer = []

        if row_buffer:
            rows.append(row_buffer)

        if total_pages > 1:
            nav_row: List[types.InlineKeyboardButton] = []
            if page > 1:
                nav_row.append(types.InlineKeyboardButton(text="⬅️ Prev", callback_data=f"invest:users:page:{page-1}"))
            nav_row.append(types.InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
            if page < total_pages:
                nav_row.append(types.InlineKeyboardButton(text="Next ➡️", callback_data=f"invest:users:page:{page+1}"))
            rows.append(nav_row)

        rows.append([
            types.InlineKeyboardButton(text="✅ Done", callback_data="invest:users:done"),
            types.InlineKeyboardButton(text="🧹 Clear", callback_data="invest:users:clear"),
        ])
        rows.append([
            types.InlineKeyboardButton(text="⬅️ Back", callback_data="invest:users:back"),
            types.InlineKeyboardButton(text="❌ Cancel", callback_data="invest:cancel"),
        ])

        return types.InlineKeyboardMarkup(inline_keyboard=rows)

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

    async def _attach_source_display_name(
        self,
        bot: Bot,
        simulation_results: dict,
        chat_id: Optional[int],
    ) -> None:
        if chat_id is None:
            return
        display_name = await self._resolve_chat_display_name(bot, chat_id)
        if display_name:
            settings = simulation_results.setdefault("settings", {})
            settings["source_display_name"] = display_name

    async def _resolve_chat_display_name(self, bot: Bot, chat_id: int) -> Optional[str]:
        cached = self._chat_title_cache.get(chat_id)
        if cached is not None:
            return cached

        display_name = None
        if self.source_model:
            try:
                records = await self.source_model.get_by_chat(chat_id)
            except Exception:
                records = []
            for record in records:
                name = record.get("display_name")
                if name:
                    display_name = name
                    break

        if not display_name:
            try:
                chat = await bot.get_chat(chat_id)
                title = getattr(chat, "title", None) or getattr(chat, "full_name", None)
                if title:
                    display_name = title
                else:
                    username = getattr(chat, "username", None)
                    if username:
                        display_name = f"@{username}"
            except TelegramBadRequest:
                display_name = None

        if display_name is not None:
            self._chat_title_cache[chat_id] = display_name
        return display_name

    def _build_timeframe_selection_keyboard(self) -> types.InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="Last 24h", callback_data="invest:timeframe:24h")
        builder.button(text="Last 7d", callback_data="invest:timeframe:7d")
        builder.button(text="Last 30d", callback_data="invest:timeframe:30d")
        builder.button(text="Last 100 tokens", callback_data="invest:timeframe:100t")
        builder.button(text="✍️ Custom...", callback_data="invest:timeframe:custom")
        builder.button(text="⬅️ Back", callback_data="invest:back:source")
        builder.button(text="❌ Cancel", callback_data="invest:cancel")
        builder.adjust(2)
        return builder.as_markup()

    async def handle_timeframe_selection(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Handles 'Last 24h', '7d', '30d', '100t', or 'custom'."""
        selection = query.data.split(":")[-1]

        if selection == "custom":
            await state.set_state(InvestStates.entering_custom_tokens)
            await query.message.edit_text(
                "Enter custom timeframe:\n\n"
                "Examples:\n"
                "• <code>48h</code> or <code>2d</code> - Time-based\n"
                "• <code>50</code> or <code>50t</code> - Number of tokens\n\n"
                "Send your input:",
                parse_mode="HTML"
            )
            await query.answer()
            return

        token_count = None
        timeframe_hours = None

        if selection.endswith('t'):
            token_count = int(selection[:-1])
        else:
            timeframe_hours = int(selection[:-1]) * (24 if 'd' in selection else 1)

        await state.update_data(token_count=token_count, timeframe_hours=timeframe_hours)
        await state.set_state(InvestStates.selecting_hold)

        await query.message.edit_text(
            "Next, choose the hold strategy:",
            reply_markup=self._build_hold_strategy_keyboard(),
        )
        await query.answer()

    async def handle_custom_timeframe_input(self, message: types.Message, state: FSMContext) -> None:
        """Handle custom timeframe text input."""
        import re

        input_text = message.text.strip().lower()

        token_count = None
        timeframe_hours = None

        # Try to parse as token count first (e.g., "50", "50t", "100")
        if input_text.endswith('t'):
            try:
                token_count = int(input_text[:-1])
            except ValueError:
                await message.answer("❌ Invalid token count. Example: <code>50t</code> or <code>100</code>", parse_mode="HTML")
                return
        elif input_text.isdigit():
            token_count = int(input_text)
        else:
            # Parse as duration (e.g., "48h", "2d", "3w")
            match = re.match(r'^(\d+)([hdw])$', input_text)
            if not match:
                await message.answer(
                    "❌ Invalid format. Use:\n"
                    "• <code>48h</code> or <code>2d</code> for time\n"
                    "• <code>50</code> or <code>50t</code> for tokens",
                    parse_mode="HTML"
                )
                return

            value, unit = match.groups()
            value = int(value)

            if unit == 'h':
                timeframe_hours = value
            elif unit == 'd':
                timeframe_hours = value * 24
            elif unit == 'w':
                timeframe_hours = value * 24 * 7

        await state.update_data(token_count=token_count, timeframe_hours=timeframe_hours)
        await state.set_state(InvestStates.selecting_hold)

        await message.answer(
            "Next, choose the hold strategy:",
            reply_markup=self._build_hold_strategy_keyboard(),
        )

    async def handle_back_to_source(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Go back to the source selection step."""
        await state.set_state(InvestStates.selecting_source)
        await query.message.edit_text(
            "Choose the source of the calls to simulate:",
            reply_markup=self._build_source_selection_keyboard(),
        )
        await query.answer()

    def _build_hold_strategy_keyboard(self) -> types.InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="To Peak", callback_data="invest:hold:peak")
        builder.button(text="Current", callback_data="invest:hold:current")
        builder.button(text="1h", callback_data="invest:hold:1h")
        builder.button(text="6h", callback_data="invest:hold:6h")
        builder.button(text="24h", callback_data="invest:hold:24h")
        builder.button(text="More...", callback_data="invest:hold:more")
        builder.button(text="✍️ Custom...", callback_data="invest:hold:custom")
        builder.button(text="⬅️ Back", callback_data="invest:back:timeframe")
        builder.button(text="❌ Cancel", callback_data="invest:cancel")
        builder.adjust(2)
        return builder.as_markup()

    async def handle_hold_strategy(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Handles hold strategy selection, runs simulation, and displays results."""
        hold_strategy = query.data.split(":")[-1]

        if hold_strategy == "more":
            await self.handle_hold_more(query, state)
            return

        if hold_strategy == "custom":
            await state.set_state(InvestStates.entering_custom_hold)
            await query.message.edit_text(
                "Enter custom hold duration:\n\n"
                "Examples:\n"
                "• <code>2h</code> - 2 hours\n"
                "• <code>30m</code> - 30 minutes\n"
                "• <code>3d</code> - 3 days\n\n"
                "Send your input:",
                parse_mode="HTML"
            )
            await query.answer()
            return

        await state.update_data(hold_strategy=hold_strategy)

        # Get all data for simulation
        data = await state.get_data()
        await state.clear()

        amount = data.get('amount', 0.0)
        chat_id = data.get('chat_id') # None for all sources
        user_ids = data.get('user_ids')
        token_count = data.get('token_count') # None if timeframe_hours is set
        timeframe_hours = data.get('timeframe_hours') # None if token_count is set
        hold_strategy = data.get('hold_strategy')

        await query.message.edit_text("⏳ Running simulation, please wait...")
        await query.answer()

        try:
            simulation_results = await self.analytics_model.simulate_investment(
                amount=amount,
                chat_id=chat_id,
                user_ids=user_ids,
                token_count=token_count,
                timeframe_hours=timeframe_hours,
                hold_strategy=hold_strategy,
                allocation="equal", # Currently only equal split is supported
            )

            if simulation_results.get("error"):
                await query.message.edit_text(f"❌ Simulation error: {simulation_results['error']}")
                return

            await self._attach_source_display_name(query.bot, simulation_results, chat_id)
            formatted_results = self._format_simulation_results(simulation_results)
            await query.message.edit_text(formatted_results, parse_mode="HTML")

        except Exception as e:
            logger.exception("Error during investment simulation: %s", e)
            await query.message.edit_text(
                "❌ An unexpected error occurred during simulation. Please try again later."
            )

    async def handle_custom_hold_input(self, message: types.Message, state: FSMContext) -> None:
        """Handle custom hold duration text input."""
        import re

        input_text = message.text.strip().lower()

        # Parse duration (e.g., "2h", "30m", "3d")
        match = re.match(r'^(\d+)([smhdw])$', input_text)
        if not match:
            await message.answer(
                "❌ Invalid format. Examples:\n"
                "• <code>30m</code> - 30 minutes\n"
                "• <code>2h</code> - 2 hours\n"
                "• <code>3d</code> - 3 days",
                parse_mode="HTML"
            )
            return

        hold_strategy = input_text
        await state.update_data(hold_strategy=hold_strategy)

        # Get all data for simulation
        data = await state.get_data()
        await state.clear()

        amount = data.get('amount', 0.0)
        chat_id = data.get('chat_id')
        user_ids = data.get('user_ids')
        token_count = data.get('token_count')
        timeframe_hours = data.get('timeframe_hours')
        hold_strategy = data.get('hold_strategy')

        await message.answer("⏳ Running simulation, please wait...")

        try:
            simulation_results = await self.analytics_model.simulate_investment(
                amount=amount,
                chat_id=chat_id,
                user_ids=user_ids,
                token_count=token_count,
                timeframe_hours=timeframe_hours,
                hold_strategy=hold_strategy,
                allocation="equal",
            )

            if simulation_results.get("error"):
                await message.answer(f"❌ Simulation error: {simulation_results['error']}")
                return

            await self._attach_source_display_name(message.bot, simulation_results, chat_id)
            formatted_results = self._format_simulation_results(simulation_results)
            await message.answer(formatted_results, parse_mode="HTML")

        except Exception as e:
            logger.exception("Error during investment simulation: %s", e)
            await message.answer(
                "❌ An unexpected error occurred during simulation. Please try again later."
            )

    async def handle_hold_more(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Show all available hold timeframes from database."""
        try:
            timeframes = await self.analytics_model.get_hold_timeframes(defaults_only=False)

            if not timeframes:
                await query.message.edit_text("No hold timeframes available.")
                await query.answer()
                return

            await query.message.edit_text(
                "Choose hold duration:",
                reply_markup=self._build_hold_more_keyboard(timeframes),
            )
            await query.answer()

        except Exception as e:
            logger.exception("Error loading hold timeframes: %s", e)
            await query.message.edit_text("❌ Failed to load hold timeframes.")
            await query.answer()

    def _build_hold_more_keyboard(self, timeframes: list) -> types.InlineKeyboardMarkup:
        """Build keyboard with all hold timeframes from database."""
        builder = InlineKeyboardBuilder()

        # Add Peak and Current first
        builder.button(text="To Peak", callback_data="invest:hold:peak")
        builder.button(text="Current", callback_data="invest:hold:current")

        # Add all timeframes from DB
        for tf in timeframes[:30]:  # Limit to 30 to avoid overflow
            label = tf.get("label", "")
            builder.button(text=label, callback_data=f"invest:hold:{label}")

        builder.button(text="✍️ Custom...", callback_data="invest:hold:custom")
        builder.button(text="⬅️ Back", callback_data="invest:back:hold")
        builder.button(text="❌ Cancel", callback_data="invest:cancel")
        builder.adjust(3)  # 3 buttons per row
        return builder.as_markup()

    async def handle_back_to_hold(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Go back to the main hold strategy selection."""
        await query.message.edit_text(
            "Choose the hold strategy:",
            reply_markup=self._build_hold_strategy_keyboard(),
        )
        await query.answer()

    async def handle_back_to_timeframe(self, query: types.CallbackQuery, state: FSMContext) -> None:
        """Go back to the timeframe selection step."""
        await state.set_state(InvestStates.selecting_timeframe)
        await query.message.edit_text(
            "Choose the time period for selecting tokens:",
            reply_markup=self._build_timeframe_selection_keyboard(),
        )
        await query.answer()

    def _format_simulation_results(self, results: dict) -> str:
        """Formats the simulation results into a human-readable string."""
        settings = results.get("settings", {})
        total_invested = results.get("total_invested", 0.0)
        total_final_value = results.get("total_final_value", 0.0)
        total_pnl = results.get("total_pnl", 0.0)
        total_pnl_pct = results.get("total_pnl_pct", 0.0)
        total_tokens = results.get("total_tokens", 0)
        winners_count = results.get("winners_count", 0)
        losers_count = results.get("losers_count", 0)
        win_threshold_pct = settings.get("win_threshold_pct", 0.0)
        avg_pnl_pct = results.get("avg_pnl_pct", 0.0)
        top3_profit_share_pct = results.get("top3_profit_share_pct", 0.0)
        slippage_model = settings.get("slippage_model")
        liquidity_pct = settings.get("liquidity_pct_of_mc")
        base_gas_sol = settings.get("base_gas_sol")
        gas_tip_sol = settings.get("gas_tip_sol")
        sol_price_usd = settings.get("sol_price_usd")
        trojan_fee_pct = settings.get("trojan_fee_pct")
        worst_results = results.get("worst_results", [])
        top_15_results = results.get("results", []) # 'results' contains top 15
        fallback_count = results.get("fallback_count", 0)
        fallback_hold_avg_seconds = results.get("fallback_hold_avg_seconds")
        fallback_hold_min_seconds = results.get("fallback_hold_min_seconds")
        fallback_hold_max_seconds = results.get("fallback_hold_max_seconds")
        excluded_due_to_age = results.get("excluded_due_to_age", 0)

        if settings.get("chat_id") is None:
            source_text = "All"
        else:
            chat_id = settings["chat_id"]
            display_name = settings.get("source_display_name")
            if display_name:
                base = f"{html.escape(str(display_name))} (<code>{chat_id}</code>)"
            else:
                base = f"<code>{chat_id}</code>"
            if settings.get("user_id") is not None:
                source_text = f"{base} (User <code>{settings['user_id']}</code>)"
            elif settings.get("user_ids"):
                user_ids = settings.get("user_ids") or []
                if len(user_ids) <= 3:
                    user_list = ", ".join(f"<code>{uid}</code>" for uid in user_ids)
                    source_text = f"{base} (Users {user_list})"
                else:
                    source_text = f"{base} ({len(user_ids)} users selected)"
            else:
                source_text = f"{base} (All users)"
        period_text = ""
        if settings.get("timeframe_hours"):
            period_text = f"Last {settings['timeframe_hours']}h"
        elif settings.get("token_count"):
            period_text = f"Last {settings['token_count']} tokens"
        if slippage_model == "liquidity_ratio" and liquidity_pct is None:
            liquidity_pct = 10.0
        gas_per_token_usd = 0.0
        if base_gas_sol is not None and gas_tip_sol is not None and sol_price_usd is not None:
            gas_per_tx_usd = (base_gas_sol + gas_tip_sol) * sol_price_usd
            gas_per_token_usd = gas_per_tx_usd * 2

        hold_raw = settings.get("hold_strategy", "N/A")
        if hold_raw in ("peak", "current"):
            hold_label = hold_raw.title()
        else:
            hold_label = hold_raw
        if settings.get("timeframe_hours"):
            timeframe_header = f"{settings.get('timeframe_hours')}h"
        elif settings.get("token_count"):
            timeframe_header = f"{settings.get('token_count')} tokens"
        else:
            timeframe_header = "N/A"
        header = f"💰 <b>Investment Simulation — {timeframe_header} | Hold {hold_label}</b>"

        pnl_sign = "+" if total_pnl >= 0 else ""
        pnl_emoji = "🟩" if total_pnl >= 0 else "🟥"
        win_rate_pct = (winners_count / total_tokens * 100) if total_tokens else 0.0

        lines = [
            header,
            "",
            "<b>📊 SUMMARY</b>",
            f"Final Value:        ${total_final_value:,.2f}",
            f"Total P&L:          {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{total_pnl_pct:.0f}%) {pnl_emoji}",
            f"Total Invested:     ${total_invested:,.2f}",
            f"Fees Paid:          ${results.get('total_fees_usd', 0.0):,.2f}",
            f"Win Rate:           {winners_count} / {total_tokens} ({win_rate_pct:.0f}%)",
            f"Average Gain:       {avg_pnl_pct:+.1f}%",
            f"Top 3 Impact:       {top3_profit_share_pct:.0f}% of total profit",
            "",
            "<b>⚙️ SETTINGS</b>",
            f"Per Token:          ${settings.get('amount', 0.0):,.2f}",
            f"Period:             {period_text} ({total_tokens} tokens)",
            f"Hold Time:          {hold_label}",
            f"Sources:            {source_text}",
            f"Slippage:           Liquidity-based ({liquidity_pct:.0f}%)",
            f"Gas Cost:           ${gas_per_token_usd:.2f} per token",
            f"Trojan Fee:         {(trojan_fee_pct or 0):.2f}% per trade",
            "",
        ]
        if fallback_count:
            if fallback_hold_avg_seconds is not None:
                avg_hold = self._format_duration(int(fallback_hold_avg_seconds))
                min_hold = self._format_duration(int(fallback_hold_min_seconds)) if fallback_hold_min_seconds is not None else "N/A"
                max_hold = self._format_duration(int(fallback_hold_max_seconds)) if fallback_hold_max_seconds is not None else "N/A"
                lines.append(
                    f"ℹ️ {fallback_count} token(s) missing {hold_label} data; "
                    f"used last available hold avg {avg_hold} (min {min_hold}, max {max_hold})."
                )
            else:
                lines.append(
                    f"ℹ️ {fallback_count} token(s) missing {hold_label} data; "
                    f"used last available hold."
                )
            lines.append("")
        if excluded_due_to_age:
            lines.append(
                f"ℹ️ {excluded_due_to_age} token(s) excluded (age < {hold_label})."
            )
            lines.append("")

        if top_15_results:
            perf_lines = []
            for i, res in enumerate(top_15_results, 1):
                ticker = html.escape(res.get("ticker") or "")
                final_value = f"{res['final_value']:,.2f}"
                pnl_pct = res["pnl_pct"]
                pnl_sign = "+" if pnl_pct >= 0 else ""
                emoji = "🟩" if pnl_pct >= 0 else "🟥"
                perf_lines.append(
                    f"{i}. {ticker}   {pnl_sign}{pnl_pct:.0f}%   ${final_value} {emoji}"
                )
            lines.append("<b>🚀 TOP PERFORMERS</b>")
            lines.append("<blockquote>" + "\n".join(perf_lines) + "</blockquote>")
            lines.append("")

            mc_lines = []
            for res in top_15_results[:15]:
                ticker = html.escape(res.get("ticker") or "")
                entry_mc = self._format_mc_short(res.get("entry_mc"))
                exit_mc = self._format_mc_short(res.get("exit_mc"))
                mc_lines.append(f"{ticker}:   {entry_mc} → {exit_mc}")
            lines.append("<b>📉 MC MOVE (TOP 15)</b>")
            lines.append("<blockquote expandable>" + "\n".join(mc_lines) + "</blockquote>")
            lines.append("")

        if worst_results:
            worst_lines = []
            for i, res in enumerate(worst_results, 1):
                ticker = html.escape(res.get("ticker") or "")
                final_value = f"{res['final_value']:,.2f}"
                pnl_pct = res["pnl_pct"]
                pnl_sign = "+" if pnl_pct >= 0 else ""
                worst_lines.append(
                    f"{i}. {ticker}   {pnl_sign}{pnl_pct:.0f}%   ${final_value} 🟥"
                )
            lines.append("<b>🔻 WORST PERFORMERS</b>")
            lines.append("<blockquote>" + "\n".join(worst_lines) + "</blockquote>")

        # Add biggest losers if needed (from plan.md, but 'results' only has top 15)
        # For a full implementation, you'd need the whole results list or
        # specific 'worst_performers' in the simulation_results dictionary.
        # For now, we'll just show a placeholder if no losers are in top 15.
        
        return self._sanitize_html("\n".join(lines))

    @staticmethod
    def _format_mc_short(value: object) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric >= 1_000_000_000:
            return f"${numeric / 1_000_000_000:.2f}B"
        if numeric >= 1_000_000:
            return f"${numeric / 1_000_000:.2f}M"
        if numeric >= 1_000:
            return f"${numeric / 1_000:.2f}K"
        return f"${numeric:.2f}"

    @staticmethod
    def _sanitize_html(text: str) -> str:
        allowed = (
            "<b>",
            "</b>",
            "<code>",
            "</code>",
            "<blockquote>",
            "</blockquote>",
            "<blockquote expandable>",
        )
        i = 0
        out: list[str] = []
        while i < len(text):
            if text[i] == "<":
                matched = False
                for tag in allowed:
                    if text.startswith(tag, i):
                        out.append(tag)
                        i += len(tag)
                        matched = True
                        break
                if not matched:
                    out.append("&lt;")
                    i += 1
            else:
                out.append(text[i])
                i += 1
        return "".join(out)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        if seconds < 86400:
            return f"{seconds // 3600}h"
        return f"{seconds // 86400}d"
