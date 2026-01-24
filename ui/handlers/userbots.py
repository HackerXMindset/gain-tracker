from __future__ import annotations

import logging
import time

from aiogram import types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PasswordHashInvalidError,
)

from config import settings
from models import BotModel
from ui.keyboards import Keyboards
from ui.states import AdminStates

logger = logging.getLogger(__name__)


class UserbotsHandler:
    """Handler for userbot management operations."""

    def __init__(self, db, keyboards: Keyboards, userbot_manager=None) -> None:
        self.db = db
        self.keyboards = keyboards
        self.bot_model = BotModel(db)
        self.userbot_manager = userbot_manager
        self.cache = {}
        self.cache_time = {}

    def is_fresh(self, key: str, seconds: int = 300) -> bool:
        return key in self.cache_time and time.time() - self.cache_time[key] < seconds

    async def get_cached_userbots_with_assignments(self):
        if self.is_fresh("userbots_with_assignments"):
            return self.cache["userbots_with_assignments"]

        userbots = await self.bot_model.get_userbots_with_assignments()
        self.cache["userbots_with_assignments"] = userbots
        self.cache_time["userbots_with_assignments"] = time.time()
        return userbots

    async def get_cached_active_userbots(self):
        if self.is_fresh("active_userbots"):
            return self.cache["active_userbots"]

        userbots = await self.bot_model.get_active_userbots()
        self.cache["active_userbots"] = userbots
        self.cache_time["active_userbots"] = time.time()
        return userbots

    def clear_cache(self) -> None:
        self.cache.clear()
        self.cache_time.clear()

    async def show_userbots_menu(self, query: types.CallbackQuery, page: int = 1) -> None:
        try:
            userbots = await self.get_cached_userbots_with_assignments()
            page_size = 5

            total_pages = (len(userbots) + page_size - 1) // page_size
            start = (page - 1) * page_size
            end = start + page_size
            paginated_userbots = userbots[start:end]

            text = "<b>🤖 Userbots Management</b>\n\n"

            if not userbots:
                text += "No userbots configured.\nClick 'Add Userbot' to create one."
            else:
                for bot in paginated_userbots:
                    status_icon = {
                        "active": "🟢",
                        "inactive": "🟡",
                        "error": "🔴",
                    }.get(bot["status"], "⚪")

                    display_name = bot.get("display_name") or bot["session_name"]
                    text += (
                        f"{status_icon} <b>{display_name}</b>\n"
                        f"  ├ Groups: {bot['assigned_groups']}\n"
                        f"  └ Last seen: {bot['last_seen'] or 'Never'}\n\n"
                    )

            await query.message.edit_text(
                text,
                reply_markup=self.keyboards.userbots_menu(
                    [dict(bot) for bot in paginated_userbots],
                    page,
                    total_pages or 1,
                ),
            )
        except Exception as exc:
            logger.error("Error showing userbots menu: %s", exc)
            await query.answer("❌ Error loading userbots")

    async def handle_userbot_action(self, query: types.CallbackQuery, state: FSMContext) -> None:
        parts = query.data.split(":")

        if parts[0] == "userbots_page" and parts[1] == "page":
            page = int(parts[2])
            await self.show_userbots_menu(query, page=page)
            return

        action = parts[1]

        if action == "add":
            await self.start_userbot_login(query, state)
        elif action == "view":
            userbot_id = int(parts[2])
            await self.show_userbot_details(query, userbot_id)
        elif action == "health":
            await self.check_userbots_health(query)
        elif action == "refresh_sources":
            await self.refresh_all_sources(query)
        elif action == "check":
            userbot_id = int(parts[2])
            await self.check_individual_userbot(query, userbot_id)
        elif action == "delete":
            userbot_id = int(parts[2])
            await self.delete_userbot(query, userbot_id)
        elif action == "confirm_delete":
            userbot_id = int(parts[2])
            await self.confirm_delete_userbot(query, userbot_id)
        elif action == "set_name":
            userbot_id = int(parts[2])
            await self.start_set_userbot_name(query, userbot_id, state)
        elif action == "start":
            userbot_id = int(parts[2])
            await self.start_worker(query, userbot_id)
        elif action == "stop":
            userbot_id = int(parts[2])
            await self.stop_worker(query, userbot_id)
        elif action == "restart":
            userbot_id = int(parts[2])
            await self.restart_worker(query, userbot_id)

    async def start_userbot_login(self, query: types.CallbackQuery, state: FSMContext) -> None:
        await query.message.edit_text(
            "<b>➕ Add New Userbot</b>\n\n"
            "I'll help you login a userbot account.\n"
            "Please enter the phone number (with country code):\n\n"
            "Example: +919876543210\n\n"
            "Type /cancel to abort.",
            reply_markup=self.keyboards.cancel_button("menu:userbots"),
        )
        await state.set_state(AdminStates.userbot_login_phone)
        await state.update_data(message_id=query.message.message_id, retry_count=0)

    async def process_phone_input(self, message: types.Message, state: FSMContext) -> None:
        if message.text == "/cancel":
            await message.answer("❌ Userbot login cancelled.")
            await state.clear()
            return

        phone = message.text.strip()
        await message.delete()

        existing_bot = await self.bot_model.get_by_phone(phone)
        if existing_bot:
            await message.answer(f"❌ Userbot with phone number {phone} already exists.")
            await state.clear()
            return

        if not phone.startswith("+"):
            await message.answer("❌ Please include country code (e.g., +919876543210)")
            return

        if not phone[1:].replace(" ", "").replace("-", "").isdigit():
            await message.answer("❌ Invalid phone number format. Use: +919876543210")
            return

        try:
            session_name = f"userbot_{phone.replace('+', '')[-8:]}"
            masked_phone = "*" * (len(phone) - 4) + phone[-4:]

            client = TelegramClient(StringSession(), settings.api_id, settings.api_hash)
            await client.connect()

            try:
                me = await client.get_me()
                if me and hasattr(me, "id"):
                    session_string = client.session.save()
                    await client.disconnect()
                    await self._save_userbot(session_name, session_string, me, phone)
                    await message.answer(
                        "✅ <b>Userbot Already Authorized!</b>\n\n"
                        f"Name: {me.first_name}\n"
                        f"Username: @{me.username or 'none'}\n"
                        f"Session: {session_name}"
                    )
                    await state.clear()
                    return
            except Exception:
                pass

            sent_code = await client.send_code_request(phone)
            session_string = client.session.save()
            await client.disconnect()

            code_request_time = time.time()
            await state.update_data(
                phone=phone,
                session_name=session_name,
                session_string=session_string,
                phone_code_hash=sent_code.phone_code_hash,
                code_request_time=code_request_time,
            )
            await state.set_state(AdminStates.userbot_login_code)

            masked_phone = "*" * (len(phone) - 4) + phone[-4:]
            await message.answer(
                "<b>📱 Code Sent</b>\n\n"
                f"A verification code has been sent to: {masked_phone}\n"
                "Please enter the 5-digit code:\n\n"
                "Type /cancel to abort.",
                reply_markup=self.keyboards.cancel_button("menu:userbots"),
            )

        except FloodWaitError as exc:
            await message.answer(
                "❌ <b>Rate Limited</b>\n\n"
                f"Please wait {exc.seconds} seconds before trying again."
            )
            await state.clear()
        except Exception as exc:
            logger.error("Phone processing error: %s", exc)
            await message.answer(
                "❌ <b>Error</b>\n\n"
                f"Failed to send verification code: {str(exc)}\n"
                "Please try again with /start"
            )
            await state.clear()

    async def process_code_input(self, message: types.Message, state: FSMContext) -> None:
        if message.text == "/cancel":
            await message.answer("❌ Userbot login cancelled.")
            await state.clear()
            return

        code = message.text.strip()
        await message.delete()

        if not code.isdigit() or len(code) != 5:
            await message.answer("❌ Please enter a valid 5-digit verification code.")
            return

        data = await state.get_data()
        phone = data.get("phone")
        session_name = data.get("session_name")
        session_string = data.get("session_string")
        phone_code_hash = data.get("phone_code_hash")
        code_request_time = data.get("code_request_time", 0)

        if not all([phone, session_name, session_string, phone_code_hash]):
            await message.answer("❌ Session data lost. Please start again with /start.")
            await state.clear()
            return

        time_elapsed = time.time() - code_request_time
        if time_elapsed > 300:
            await message.answer(
                "⚠️ **Code Request Expired**\n\n"
                f"⏰ Time elapsed: {time_elapsed:.1f} seconds\n"
                "📱 Telegram codes expire after 5 minutes\n\n"
                "Please start over with /start"
            )
            await state.clear()
            return

        try:
            client = TelegramClient(StringSession(session_string), settings.api_id, settings.api_hash)
            await client.connect()

            me = await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
            final_session = client.session.save()
            await client.disconnect()

            await self._save_userbot(session_name, final_session, me, phone)

            await message.answer(
                "✅ <b>Userbot Added Successfully!</b>\n\n"
                f"Name: {me.first_name}\n"
                f"Username: @{me.username or 'none'}\n"
                f"ID: <code>{me.id}</code>\n\n"
                f"Session: {session_name}"
            )
            await state.clear()

        except SessionPasswordNeededError:
            try:
                from telethon import functions

                password_info = await client(functions.account.GetPasswordRequest())
                hint = password_info.hint or "No hint available"
                await client.disconnect()

                updated_session = client.session.save()
                await state.update_data(
                    session_string=updated_session,
                    password_hint=hint,
                    retry_count=0,
                )
                await state.set_state(AdminStates.userbot_login_2fa)

                await message.answer(
                    "🔐 <b>2FA Required</b>\n\n"
                    "This account has two-factor authentication enabled.\n"
                    f"Hint: <i>{hint}</i>\n\n"
                    "Please enter your 2FA password:\n\n"
                    "Type /cancel to abort."
                )

            except Exception as exc:
                logger.error("2FA setup error: %s", exc)
                await message.answer(
                    "🔐 <b>2FA Required</b>\n\n"
                    "Please enter your 2FA password:\n\n"
                    "Type /cancel to abort."
                )
                await client.disconnect()
                await state.set_state(AdminStates.userbot_login_2fa)

        except PhoneCodeExpiredError:
            await message.answer(
                "❌ **Verification Code Expired**\n\n"
                f"⏰ Time elapsed: {time_elapsed:.1f} seconds\n"
                "📱 Telegram codes expire after 5 minutes\n\n"
                "Please start over with /start"
            )
            await client.disconnect()
            await state.clear()

        except PhoneCodeInvalidError:
            await message.answer(
                "❌ <b>Invalid Code</b>\n\n"
                "The verification code is incorrect. Please try again:"
            )
            await client.disconnect()

        except FloodWaitError as exc:
            await message.answer(
                "❌ <b>Rate Limited</b>\n\n"
                f"Please wait {exc.seconds} seconds before trying again."
            )
            await client.disconnect()
            await state.clear()

        except Exception as exc:
            error_msg = str(exc).lower()
            if any(word in error_msg for word in ["expired", "timeout", "time"]):
                await message.answer(
                    "❌ **Authentication Timeout**\n\n"
                    f"⏰ Time elapsed: {time_elapsed:.1f} seconds\n"
                    f"Error: {str(exc)}\n\n"
                    "Please start over with /start"
                )
            else:
                await message.answer(
                    "❌ <b>Error</b>\n\n"
                    f"Authentication failed: {str(exc)}\n"
                    "Please start again with /start"
                )
            try:
                await client.disconnect()
            except Exception:
                pass
            await state.clear()

    async def process_2fa_input(self, message: types.Message, state: FSMContext) -> None:
        if message.text == "/cancel":
            await message.answer("❌ Userbot login cancelled.")
            await state.clear()
            return

        password = message.text
        await message.delete()

        data = await state.get_data()
        phone = data.get("phone")
        session_name = data.get("session_name")
        session_string = data.get("session_string")
        password_hint = data.get("password_hint", "No hint available")
        retry_count = data.get("retry_count", 0)

        if not all([phone, session_name, session_string]):
            await message.answer("❌ Session data lost. Please start again with /start.")
            await state.clear()
            return

        if retry_count >= 3:
            await message.answer(
                "❌ <b>Maximum Attempts Exceeded</b>\n\n"
                "Too many failed attempts. Please start again with /start."
            )
            await state.clear()
            return

        try:
            client = TelegramClient(StringSession(session_string), settings.api_id, settings.api_hash)
            await client.connect()

            me = await client.sign_in(password=password)

            final_session = client.session.save()
            await client.disconnect()

            await self._save_userbot(session_name, final_session, me, phone)

            await message.answer(
                "✅ <b>Userbot Added Successfully!</b>\n\n"
                f"Name: {me.first_name}\n"
                f"Username: @{me.username or 'none'}\n"
                f"ID: <code>{me.id}</code>\n\n"
                f"Session: {session_name}"
            )
            await state.clear()

        except PasswordHashInvalidError:
            await client.disconnect()

            retry_count += 1
            attempts_left = 3 - retry_count

            await state.update_data(retry_count=retry_count)

            if attempts_left > 0:
                await message.answer(
                    "❌ <b>Invalid 2FA Password</b>\n\n"
                    f"Hint: <i>{password_hint}</i>\n\n"
                    f"Attempts remaining: {attempts_left}\n"
                    "Please try again:\n\n"
                    "Type /cancel to abort."
                )
            else:
                await message.answer(
                    "❌ <b>Maximum Attempts Exceeded</b>\n\n"
                    "Too many failed 2FA attempts. Please start again with /start."
                )
                await state.clear()

        except FloodWaitError as exc:
            await message.answer(
                "❌ <b>Rate Limited</b>\n\n"
                f"Please wait {exc.seconds} seconds before trying again."
            )
            await client.disconnect()
            await state.clear()

        except Exception as exc:
            error_msg = str(exc).lower()

            if any(word in error_msg for word in ["password", "invalid", "wrong", "incorrect", "hash"]):
                await client.disconnect()

                retry_count += 1
                attempts_left = 3 - retry_count

                await state.update_data(retry_count=retry_count)

                if attempts_left > 0:
                    await message.answer(
                        "❌ <b>Authentication Failed</b>\n\n"
                        f"Error: {str(exc)}\n\n"
                        f"Attempts remaining: {attempts_left}\n"
                        "Please try again:\n\n"
                        "Type /cancel to abort."
                    )
                else:
                    await message.answer(
                        "❌ <b>Maximum Attempts Exceeded</b>\n\n"
                        "Please start again with /start."
                    )
                    await state.clear()
            else:
                await message.answer(
                    "❌ <b>Authentication Error</b>\n\n"
                    f"Unexpected error: {str(exc)}\n"
                    "Please start again with /start."
                )
                try:
                    await client.disconnect()
                except Exception:
                    pass
                await state.clear()

    async def _save_userbot(self, session_name: str, session_string: str, me, phone: str) -> None:
        display_name = None
        if me.first_name and me.last_name:
            display_name = f"{me.first_name} {me.last_name}"
        elif me.first_name:
            display_name = me.first_name
        elif me.username:
            display_name = f"@{me.username}"
        else:
            display_name = session_name

        await self.bot_model.create(
            {
                "kind": "userbot",
                "session_name": session_name,
                "status": "active",
                "session_string": session_string,
                "telegram_id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "display_name": display_name,
                "phone": phone,
            }
        )

        self.clear_cache()

    async def show_userbot_details(self, query_or_message: types.Message | types.CallbackQuery, userbot_id: int) -> None:
        try:
            userbot = await self.bot_model.get_by_id(userbot_id)
            assigned_groups = await self.bot_model.get_assigned_groups(userbot_id)

            if not userbot:
                if isinstance(query_or_message, types.CallbackQuery):
                    await query_or_message.answer("Userbot not found!")
                else:
                    await query_or_message.answer("Userbot not found!")
                return

            worker = None
            if self.userbot_manager:
                worker = self.userbot_manager.get_worker(userbot_id)
            is_running = worker and worker.running

            db_status = userbot.get("status", "inactive")
            status_icon = {
                "active": "🟢",
                "inactive": "🟡",
                "error": "🔴",
            }.get(db_status, "⚪")

            display_name = userbot.get("display_name") or userbot["session_name"]
            phone_number = userbot.get("phone", "Not available")
            text = (
                "<b>🤖 Userbot Details</b>\n\n"
                f"<b>{display_name}</b>\n"
                f"Status: {status_icon} {db_status.title()}\n"
                f"Phone: <code>{phone_number}</code>\n"
                f"Last Seen: {userbot['last_seen'] or 'Never'}\n\n"
                "<b>Assignments:</b>\n"
            )

            if assigned_groups:
                for group in assigned_groups:
                    group_label = group["title"] or f"Chat {group['tg_chat_id']}"
                    text += f"├ {group_label}\n"
                text = text.rstrip("\n") + "\n"
            else:
                text += "└ No groups assigned\n"

            keyboard_rows = []
            action_buttons = []

            if is_running:
                action_buttons.append(InlineKeyboardButton(text="🛑 Stop", callback_data=f"userbot:stop:{userbot_id}"))
                action_buttons.append(InlineKeyboardButton(text="🔄 Restart", callback_data=f"userbot:restart:{userbot_id}"))
            else:
                action_buttons.append(InlineKeyboardButton(text="▶️ Start", callback_data=f"userbot:start:{userbot_id}"))

            keyboard_rows.append(action_buttons)
            keyboard_rows.append([
                InlineKeyboardButton(text="✏️ Set Name", callback_data=f"userbot:set_name:{userbot_id}"),
                InlineKeyboardButton(text="🔎 Check Status", callback_data=f"userbot:check:{userbot_id}"),
            ])
            keyboard_rows.append([InlineKeyboardButton(text="🗑 Delete", callback_data=f"userbot:delete:{userbot_id}")])
            keyboard_rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="menu:userbots")])

            keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

            if isinstance(query_or_message, types.CallbackQuery):
                await query_or_message.message.edit_text(text, reply_markup=keyboard)
            else:
                await query_or_message.answer(text, reply_markup=keyboard, parse_mode="HTML")

        except Exception as exc:
            logger.error("Error showing userbot details: %s", exc)
            if isinstance(query_or_message, types.CallbackQuery):
                await query_or_message.answer("❌ Error loading userbot details")

    async def check_userbots_health(self, query: types.CallbackQuery) -> None:
        try:
            userbots = await self.get_cached_active_userbots()

            if not userbots:
                await query.answer("No userbots to check")
                return

            text = "<b>🔄 Userbot Health Check</b>\n\n"

            for userbot in userbots:
                status_icon = "🟢" if userbot["status"] == "active" else "🔴"
                text += f"{status_icon} {userbot['session_name']}: {userbot['status']}\n"

            text += "\n✅ Health check completed"

            await query.message.edit_text(text, reply_markup=self.keyboards.back_button("menu:userbots"))

        except Exception as exc:
            logger.error("Error checking userbot health: %s", exc)
            await query.answer("❌ Error checking userbot health")

    async def refresh_all_sources(self, query: types.CallbackQuery) -> None:
        if not self.userbot_manager:
            await query.answer("❌ Userbot manager not available.")
            return

        try:
            await query.message.edit_text(
                "<b>🔄 Refreshing Sources</b>\n\n"
                "Please wait while we refresh source monitoring for all active userbots...",
                reply_markup=None,
            )

            await self.userbot_manager.sync_workers_with_database()

            text = "✅ <b>Sources Refreshed Successfully</b>\n\n"
            text += "Running userbots have been synced with the latest source configurations."

            await query.message.edit_text(text, reply_markup=self.keyboards.back_button("menu:userbots"))
            await query.answer("✅ Sources refreshed successfully")

        except Exception as exc:
            logger.error("Error refreshing sources: %s", exc)
            await query.answer("❌ Error refreshing sources")

    async def check_individual_userbot(self, query: types.CallbackQuery, userbot_id: int) -> None:
        if not self.userbot_manager:
            await query.answer("❌ Userbot manager not available.")
            return

        try:
            userbot = await self.bot_model.get_by_id(userbot_id)
            if not userbot:
                await query.answer("Userbot not found!")
                return

            await query.message.edit_text(
                "<b>🔄 Checking Userbot Status...</b>\n\n"
                "Please wait while we check the live worker status...",
                reply_markup=None,
            )

            worker = self.userbot_manager.get_worker(userbot_id)
            if worker and worker.running:
                health = await worker.health_check()
                if health.get("healthy"):
                    status_icon = "✅"
                    status_text = "Running and Healthy"
                    details = (
                        f"User ID: {health['session']['user_id']}\n"
                        f"Username: @{health['session']['username'] or 'none'}"
                    )
                else:
                    status_icon = "🔴"
                    status_text = "Running but Unhealthy"
                    details = f"Error: {health.get('error', 'Unknown error')}"
            else:
                status_icon = "🟡"
                status_text = "Inactive / Not Running"
                details = "The userbot worker is not currently running."

            text = (
                "<b>🔍 Userbot Status Check</b>\n\n"
                f"<b>{userbot.get('display_name') or userbot['session_name']}</b>\n\n"
                f"Status: {status_icon} {status_text}\n"
                f"Details: {details}\n\n"
                "✅ Check completed."
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data=f"userbot:view:{userbot_id}")]]
            )

            await query.message.edit_text(text, reply_markup=keyboard)

        except Exception as exc:
            logger.error("Error checking individual userbot: %s", exc)
            await query.answer("❌ Error checking userbot status")

    async def delete_userbot(self, query: types.CallbackQuery, userbot_id: int) -> None:
        try:
            userbot = await self.bot_model.get_by_id(userbot_id)
            if not userbot:
                await query.answer("Userbot not found!")
                return

            text = (
                "<b>🗑 Delete Userbot</b>\n\n"
                "Are you sure you want to delete:\n"
                f"<b>{userbot['session_name']}</b>\n\n"
                "⚠️ <b>Warning:</b>\n"
                "• This will permanently remove the userbot\n"
                "• All assignments will be lost\n"
                "• This action cannot be undone\n\n"
                "Confirm deletion?"
            )

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Yes, Delete", callback_data=f"userbot:confirm_delete:{userbot_id}"),
                    InlineKeyboardButton(text="❌ Cancel", callback_data=f"userbot:view:{userbot_id}"),
                ]]
            )

            await query.message.edit_text(text, reply_markup=keyboard)

        except Exception as exc:
            logger.error("Error showing delete confirmation: %s", exc)
            await query.answer("❌ Error loading delete confirmation")

    async def confirm_delete_userbot(self, query: types.CallbackQuery, userbot_id: int) -> None:
        try:
            userbot = await self.bot_model.get_by_id(userbot_id)
            if not userbot:
                await query.answer("Userbot not found!")
                return

            session_name = userbot["session_name"]
            success = await self.bot_model.delete(userbot_id)
            self.clear_cache()

            if success:
                text = (
                    "✅ <b>Userbot Deleted</b>\n\n"
                    "Successfully removed:\n"
                    f"<b>{session_name}</b>\n\n"
                    "The userbot and all its assignments have been permanently deleted."
                )
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="🔙 Back to Userbots", callback_data="menu:userbots")]]
                )
                await query.answer("✅ Userbot deleted successfully")
            else:
                text = (
                    "❌ <b>Deletion Failed</b>\n\n"
                    "Could not delete userbot:\n"
                    f"<b>{session_name}</b>\n\n"
                    "The userbot may not exist or there was a database error."
                )
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data=f"userbot:view:{userbot_id}")]]
                )
                await query.answer("❌ Failed to delete userbot")

            await query.message.edit_text(text, reply_markup=keyboard)

        except Exception as exc:
            logger.error("Error confirming userbot deletion: %s", exc)
            await query.answer("❌ Error deleting userbot")
            try:
                await query.message.edit_text(
                    "❌ <b>Deletion Error</b>\n\n" f"Error: {str(exc)}",
                    reply_markup=self.keyboards.back_button("menu:userbots"),
                )
            except Exception:
                pass

    async def start_set_userbot_name(self, query: types.CallbackQuery, userbot_id: int, state: FSMContext) -> None:
        try:
            userbot = await self.bot_model.get_by_id(userbot_id)
            if not userbot:
                await query.answer("Userbot not found!")
                return

            current_name = userbot.get("display_name") or userbot["session_name"]

            await query.message.edit_text(
                "<b>✏️ Set Userbot Name</b>\n\n"
                f"Current name: <b>{current_name}</b>\n\n"
                "Enter a new custom name for this userbot:\n\n"
                "Type /cancel to abort.",
                reply_markup=self.keyboards.cancel_button(f"userbot:view:{userbot_id}"),
            )

            await state.set_state(AdminStates.userbot_set_name)
            await state.update_data(userbot_id=userbot_id, message_id=query.message.message_id)

        except Exception as exc:
            logger.error("Error starting userbot name setting: %s", exc)
            await query.answer("❌ Error starting name setting")

    async def process_userbot_name_input(self, message: types.Message, state: FSMContext) -> None:
        if message.text == "/cancel":
            data = await state.get_data()
            userbot_id = data.get("userbot_id")
            await message.answer("❌ Name setting cancelled.")
            await state.clear()
            if userbot_id:
                await self.show_userbot_details(message, userbot_id)
            return

        new_name = message.text.strip()
        await message.delete()

        if not new_name or len(new_name) > 50:
            await message.answer("❌ Name must be 1-50 characters long.")
            return

        try:
            data = await state.get_data()
            userbot_id = data.get("userbot_id")

            if not userbot_id:
                await message.answer("❌ Session data lost. Please try again.")
                await state.clear()
                return

            await self.db.execute(
                "UPDATE bots SET display_name = $1 WHERE id = $2",
                new_name,
                userbot_id,
            )

            await message.answer(
                "✅ <b>Name Updated Successfully!</b>\n\n"
                f"Userbot name set to: <b>{new_name}</b>"
            )

            await state.clear()

        except Exception as exc:
            logger.error("Error updating userbot name: %s", exc)
            await message.answer(f"❌ Error updating name: {str(exc)}")
            await state.clear()

    async def start_worker(self, query: types.CallbackQuery, userbot_id: int) -> None:
        if not self.userbot_manager:
            await query.answer("❌ Userbot manager not available.")
            return

        await query.message.edit_text("▶️ Starting worker...")
        try:
            userbot = await self.bot_model.get_by_id(userbot_id)
            if userbot and userbot.get("session_string"):
                await self.userbot_manager.start_worker(userbot_id, userbot["session_string"])
                await query.answer("✅ Worker started!")
            else:
                await query.answer("❌ Could not find userbot or session string.")
        except Exception as exc:
            logger.error("Error starting worker %s: %s", userbot_id, exc)
            await query.answer(f"❌ Error: {exc}")
        await self.show_userbot_details(query, userbot_id)

    async def stop_worker(self, query: types.CallbackQuery, userbot_id: int) -> None:
        if not self.userbot_manager:
            await query.answer("❌ Userbot manager not available.")
            return

        await query.message.edit_text("🛑 Stopping worker...")
        try:
            await self.userbot_manager.stop_worker(userbot_id)
            await query.answer("✅ Worker stopped!")
        except Exception as exc:
            logger.error("Error stopping worker %s: %s", userbot_id, exc)
            await query.answer(f"❌ Error: {exc}")
        await self.show_userbot_details(query, userbot_id)

    async def restart_worker(self, query: types.CallbackQuery, userbot_id: int) -> None:
        if not self.userbot_manager:
            await query.answer("❌ Userbot manager not available.")
            return

        await query.message.edit_text("🔄 Restarting worker...")
        try:
            await self.userbot_manager.restart_worker(userbot_id)
            await query.answer("✅ Worker restarted!")
        except Exception as exc:
            logger.error("Error restarting worker %s: %s", userbot_id, exc)
            await query.answer(f"❌ Error: {exc}")
        await self.show_userbot_details(query, userbot_id)
