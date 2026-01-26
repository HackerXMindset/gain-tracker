"""Command Forwarding UI Handler - Manages the button-based wizard for creating command forwarding rules."""

import logging
import traceback
from aiogram import types
from aiogram.fsm.context import FSMContext
from typing import Dict, Any, List

from models import CommandForwardingRuleModel, CommandTrackedMessageModel, GroupModel, BotModel
from ui.keyboards import Keyboards
from ui.states import ManagementStates
from scheduler import get_command_forwarding_service

logger = logging.getLogger(__name__)

class CommandForwardingHandler:
    def __init__(self, db, keyboards: Keyboards):
        self.db = db
        self.keyboards = keyboards
        self.cmd_fwd_model = CommandForwardingRuleModel(db)
        self.cmd_tracked_model = CommandTrackedMessageModel(db)
        self.group_model = GroupModel(db)
        self.bot_model = BotModel(db)

    async def _seed_groups_from_sources(self) -> None:
        rows = await self.db.fetch(
            """
            SELECT DISTINCT chat_id, display_name
            FROM monitored_sources
            WHERE chat_type = 'group'
            """
        )
        for row in rows:
            await self.group_model.upsert_from_source(row["chat_id"], row.get("display_name"))

    async def handle_cmd_fwd_action(self, query: types.CallbackQuery, state: FSMContext):
        try:
            action = query.data.split(':')[1]
            logger.debug(f'Handling command forwarding action: {action}')

            if action == 'list':
                await self.show_rules_list(query)
            elif action == 'add':
                await self.start_add_rule_wizard(query, state)
            elif action == 'view':
                rule_id = int(query.data.split(':')[2])
                await self.show_rule_details(query, rule_id)
            elif action == 'toggle':
                rule_id = int(query.data.split(':')[2])
                await self.toggle_rule_enabled(query, rule_id)
            elif action == 'toggle_schedule':
                rule_id = int(query.data.split(':')[2])
                await self.toggle_schedule_enabled(query, rule_id)
            elif action == 'delete':
                rule_id = int(query.data.split(':')[2])
                await self.confirm_delete_rule(query, rule_id)
            elif action == 'confirm_delete':
                rule_id = int(query.data.split(':')[2])
                await self.delete_rule(query, rule_id)
            elif action == 'edit_command':
                rule_id = int(query.data.split(':')[2])
                await self.edit_command(query, state, rule_id)
            elif action == 'manage_command_users':
                rule_id = int(query.data.split(':')[2])
                await self.edit_command_users(query, state, rule_id)
            elif action == 'manage_reply_users':
                rule_id = int(query.data.split(':')[2])
                await self.edit_reply_users(query, state, rule_id)
            elif action == 'set_fwd_bot':
                rule_id = int(query.data.split(':')[2])
                await self.show_forwarding_bot_selection(query, state, rule_id)
            elif action == 'schedule_settings':
                rule_id = int(query.data.split(':')[2])
                await self.show_schedule_settings(query, state, rule_id)
            elif action == 'toggle_timestamp':
                rule_id = int(query.data.split(':')[2])
                await self.toggle_timestamp_posting(query, rule_id)
            elif action == 'set_timezone':
                rule_id = int(query.data.split(':')[2])
                await self.show_timezone_selection(query, state, rule_id)
            elif action == 'select_timezone':
                rule_id = int(query.data.split(':')[2])
                timezone = query.data.split(':')[3]
                await self.update_timezone(query, rule_id, timezone)
            elif action == 'manage_excluded':
                rule_id = int(query.data.split(':')[2])
                await self.show_excluded_messages(query, rule_id)
            elif action == 'add_excluded':
                rule_id = int(query.data.split(':')[2])
                await self.prompt_add_excluded_text(query, state, rule_id)
            elif action == 'remove_excluded':
                rule_id = int(query.data.split(':')[2])
                index = int(query.data.split(':')[3])
                await self.remove_excluded_text(query, rule_id, index)
            elif action == 'test':
                rule_id = int(query.data.split(':')[2])
                await self.test_rule(query, rule_id)

            # Wizard actions
            elif action == 'wizard_source_group':
                await self.wizard_process_source_group(query, state)
            elif action == 'wizard_add_monitored':
                await self.wizard_prompt_for_user_id(query, state, 'monitored')
            elif action == 'wizard_remove_monitored':
                user_id = int(query.data.split(':')[2])
                await self.wizard_remove_user(query, state, 'monitored', user_id)
            elif action == 'wizard_next_to_fwd_bot':
                await self.wizard_show_forwarding_bot_selection(query, state)
            elif action == 'wizard_fwd_bot':
                await self.wizard_process_forwarding_bot(query, state)
            elif action == 'wizard_next_to_destination':
                await self.wizard_prompt_for_destination(query, state)
            elif action == 'wizard_add_replying':
                await self.wizard_prompt_for_user_id(query, state, 'replying')
            elif action == 'wizard_remove_replying':
                user_id = int(query.data.split(':')[2])
                await self.wizard_remove_user(query, state, 'replying', user_id)
            elif action == 'wizard_next_to_schedule':
                await self.wizard_show_schedule_options(query, state)
            elif action == 'wizard_schedule':
                await self.wizard_process_schedule_option(query, state)
            elif action == 'wizard_next_to_summary':
                await self.wizard_show_summary(query, state)
            elif action == 'wizard_save':
                await self.save_rule(query, state)
            else:
                logger.warning(f'Unknown command forwarding action: {action}')
                await query.answer('❌ Unknown action', show_alert=True)
        except Exception as e:
            logger.error(f'Error in handle_cmd_fwd_action: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def show_rules_list(self, query: types.CallbackQuery):
        logger.debug('Showing command forwarding rules list')
        try:
            rules_records = await self.cmd_fwd_model.get_all_with_details()
            rules = []
            for record in rules_records:
                rule_dict = dict(record)
                dest_info = await self._get_entity_info(query, rule_dict['destination_channel_id'])
                rule_dict['destination_channel_title'] = dest_info['title']
                rules.append(rule_dict)

            keyboard = self.keyboards.cmd_fwd_rules_list(rules)
            text = f'<b>🏆 Rank Rules ({len(rules)})</b>\n\nManage rules for forwarding replies to rank commands and scheduling automatic command sending.'
            await query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
            await query.answer()
        except Exception as e:
            logger.error(f'Error in show_rules_list: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def show_rule_details(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Showing details for command forwarding rule {rule_id}')
        try:
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            if not rule:
                logger.warning(f'Rule {rule_id} not found')
                return await query.answer('Rule not found.')

            source_group = {'title': rule['source_group_title']}

            dest_channel_info = await self._get_entity_info(query, rule['destination_channel_id'])
            fwd_bot = await self.bot_model.get_by_id(rule['forwarding_userbot_id'])
            text = self.keyboards.cmd_fwd_rule_details_text(rule, source_group, dest_channel_info, fwd_bot)
            keyboard = self.keyboards.cmd_fwd_rule_details_menu(rule)
            await query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
            await query.answer()
        except Exception as e:
            logger.error(f'Error in show_rule_details: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def toggle_rule_enabled(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Toggling command forwarding rule {rule_id}')
        try:
            new_status = await self.cmd_fwd_model.toggle_enabled(rule_id)
            await query.answer(f'✅ Rule has been {"enabled" if new_status else "disabled"}.')
            await self.show_rule_details(query, rule_id)
        except Exception as e:
            logger.error(f'Error in toggle_rule_enabled: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def toggle_schedule_enabled(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Toggling schedule for command forwarding rule {rule_id}')
        try:
            new_status = await self.cmd_fwd_model.toggle_schedule_enabled(rule_id)
            await query.answer(f'✅ Schedule has been {"enabled" if new_status else "disabled"}.')
            await self.show_rule_details(query, rule_id)
        except Exception as e:
            logger.error(f'Error in toggle_schedule_enabled: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def toggle_timestamp_posting(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Toggling timestamp posting for command forwarding rule {rule_id}')
        try:
            new_status = await self.cmd_fwd_model.toggle_timestamp_posting(rule_id)
            await query.answer(f'✅ Timestamp posting has been {"enabled" if new_status else "disabled"}.')
            await self.show_rule_details(query, rule_id)
        except Exception as e:
            logger.error(f'Error in toggle_timestamp_posting: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def show_timezone_selection(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        rule = await self.cmd_fwd_model.get_by_id(rule_id)
        if not rule:
            return await query.answer("Rule not found.")

        current_tz = rule.get('timestamp_timezone', 'IST')
        text = f'<b>🌍 Select Timezone</b>\n\nCurrent: <b>{current_tz}</b>\n\nSelect timezone for timestamp display:'
        keyboard = self.keyboards.cmd_fwd_timezone_selection_keyboard(rule_id, current_tz)
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

    async def update_timezone(self, query: types.CallbackQuery, rule_id: int, timezone: str):
        logger.debug(f'Updating timezone for rule {rule_id} to {timezone}')
        try:
            await self.cmd_fwd_model.update_timezone(rule_id, timezone)
            await query.answer(f'✅ Timezone updated to {timezone}')
            await self.show_rule_details(query, rule_id)
        except Exception as e:
            logger.error(f'Error updating timezone: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def show_excluded_messages(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Showing excluded messages for rule {rule_id}')
        try:
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            if not rule:
                return await query.answer('Rule not found.')

            excluded_texts = rule.get('excluded_message_texts', []) or []

            text = '<b>🔇 Excluded Messages</b>\n\n'
            text += 'Messages matching these texts (case-sensitive) will NOT be forwarded:\n\n'

            if excluded_texts:
                for i, exc_text in enumerate(excluded_texts, 1):
                    # Show full text in list
                    display = exc_text if len(exc_text) <= 60 else exc_text[:57] + "..."
                    text += f'{i}. "{display}"\n'
            else:
                text += '<i>No excluded messages configured.</i>'

            keyboard = self.keyboards.cmd_fwd_excluded_messages_keyboard(excluded_texts, rule_id)
            await query.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
            await query.answer()
        except Exception as e:
            logger.error(f'Error showing excluded messages: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def prompt_add_excluded_text(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        logger.debug(f'Prompting to add excluded text for rule {rule_id}')
        try:
            await state.set_data({'rule_id': rule_id})
            await state.set_state(ManagementStates.cmd_fwd_add_excluded_text)
            await query.message.edit_text('<b>➕ Add Excluded Text</b>\n\nEnter the exact text to exclude (case-sensitive):')
            await query.answer()
        except Exception as e:
            logger.error(f'Error prompting for excluded text: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def remove_excluded_text(self, query: types.CallbackQuery, rule_id: int, index: int):
        logger.debug(f'Removing excluded text at index {index} from rule {rule_id}')
        try:
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            if not rule:
                return await query.answer('Rule not found.')

            excluded_texts = rule.get('excluded_message_texts', []) or []

            if index < 0 or index >= len(excluded_texts):
                return await query.answer('❌ List was modified. Please refresh.', show_alert=True)

            text_to_remove = excluded_texts[index]

            # Re-verify text still exists before removal (race condition protection)
            rule_check = await self.cmd_fwd_model.get_by_id(rule_id)
            current_texts = rule_check.get('excluded_message_texts', []) or []
            if text_to_remove not in current_texts:
                return await query.answer('❌ Text already removed.', show_alert=True)

            await self.cmd_fwd_model.remove_excluded_text(rule_id, text_to_remove)

            await query.answer(f'✅ Removed excluded text.')
            await self.show_excluded_messages(query, rule_id)
        except Exception as e:
            logger.error(f'Error removing excluded text: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def process_excluded_text_input(self, message: types.Message, state: FSMContext):
        logger.debug('Processing excluded text input')
        try:
            text = message.text.strip()
            if not text:
                return await message.answer('❌ Text cannot be empty. Please enter text to exclude.')

            if len(text) > 500:
                return await message.answer('❌ Text too long (max 500 characters).')

            data = await state.get_data()
            rule_id = data.get('rule_id')
            if not rule_id:
                await state.clear()
                return await message.answer('❌ Rule not found.')

            await self.cmd_fwd_model.add_excluded_text(rule_id, text)
            await message.delete()

            # Show updated excluded messages list
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            excluded_texts = rule.get('excluded_message_texts', []) or []

            response_text = '<b>🔇 Excluded Messages</b>\n\n'
            response_text += 'Messages matching these texts (case-sensitive) will NOT be forwarded:\n\n'

            for i, exc_text in enumerate(excluded_texts, 1):
                display = exc_text if len(exc_text) <= 60 else exc_text[:57] + "..."
                response_text += f'{i}. "{display}"\n'

            keyboard = self.keyboards.cmd_fwd_excluded_messages_keyboard(excluded_texts, rule_id)
            await message.answer(response_text, reply_markup=keyboard, parse_mode='HTML')
            await state.clear()
        except Exception as e:
            logger.error(f'Error processing excluded text input: {e}\n{traceback.format_exc()}')
            await message.answer('❌ An error occurred. Please try again.')
            await state.clear()

    async def confirm_delete_rule(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Confirming deletion for command forwarding rule {rule_id}')
        try:
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            if not rule:
                return await query.answer('Rule not found.')

            text = f"<b>🗑️ Confirm Deletion</b>\n\nAre you sure you want to delete the rank rule for command '{rule['command_text']}'?"
            keyboard = self.keyboards.cmd_fwd_confirm_delete(rule_id)
            await query.message.edit_text(text, reply_markup=keyboard)
            await query.answer()
        except Exception as e:
            logger.error(f'Error in confirm_delete_rule: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def delete_rule(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f'Deleting command forwarding rule {rule_id}')
        try:
            await self.cmd_fwd_model.delete(rule_id)
            await query.message.edit_text('✅ Rank Rule deleted successfully!')
            await self.show_rules_list(query)
        except Exception as e:
            logger.error(f'Error in delete_rule: {e}\n{traceback.format_exc()}')
            await query.answer('❌ An error occurred. Please try again.', show_alert=True)

    async def test_rule(self, query: types.CallbackQuery, rule_id: int):
        logger.debug(f"Testing rank rule {rule_id}")
        try:
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            if not rule:
                return await query.answer("Rule not found.", show_alert=True)

            group = await self.group_model.get_by_id(rule["source_group_id"])
            if not group:
                return await query.answer("Source group not found.", show_alert=True)

            service = get_command_forwarding_service()
            if not service.userbot_manager:
                return await query.answer("Userbots not ready. Start the service first.", show_alert=True)

            success = await service.send_test_command(rule, group["tg_chat_id"])
            if success:
                await query.answer("✅ Test command sent. Waiting for replies to forward.", show_alert=True)
            else:
                await query.answer("❌ Failed to send test command.", show_alert=True)
        except Exception as exc:
            logger.error("Error testing rank rule: %s\n%s", exc, traceback.format_exc())
            await query.answer("❌ Test failed. Check logs.", show_alert=True)

    async def edit_command(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        rule = await self.cmd_fwd_model.get_by_id(rule_id)
        if not rule:
            return await query.answer("Rule not found.")
        await state.set_data({'rule_id': rule_id})
        await query.message.edit_text(f'<b>💬 Edit Command</b>\n\nCurrent command: <code>{rule["command_text"]}</code>\n\nEnter the new command text:')
        await state.set_state(ManagementStates.cmd_fwd_edit_command)

    async def show_forwarding_bot_selection(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        rule = await self.cmd_fwd_model.get_by_id(rule_id)
        if not rule:
            return await query.answer("Rule not found.")
        await state.set_data({'rule_id': rule_id})
        await self.wizard_show_forwarding_bot_selection(query, state)

    async def show_schedule_settings(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        rule = await self.cmd_fwd_model.get_by_id(rule_id)
        if not rule:
            return await query.answer("Rule not found.")
        await state.set_data({'rule_id': rule_id})
        await self.wizard_show_schedule_options(query, state)

    async def edit_command_users(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        rule = await self.cmd_fwd_model.get_by_id(rule_id)
        if not rule:
            return await query.answer("Rule not found.")
        await state.set_data({'monitored_users': rule.get('allowed_command_user_ids', []) or [], 'rule_id': rule_id})
        await self.wizard_show_monitored_users_menu(query, state)

    async def edit_reply_users(self, query: types.CallbackQuery, state: FSMContext, rule_id: int):
        rule = await self.cmd_fwd_model.get_by_id(rule_id)
        if not rule:
            return await query.answer("Rule not found.")
        await state.set_data({'replying_users': rule.get('allowed_reply_user_ids', []) or [], 'rule_id': rule_id})
        await self.wizard_show_replying_users_menu(query, state)

    async def start_add_rule_wizard(self, query: types.CallbackQuery, state: FSMContext):
        await state.clear()
        await self._seed_groups_from_sources()
        groups = await self.group_model.get_enabled_groups()
        if not groups:
            return await query.answer('❌ No groups available. Please add a group first.', show_alert=True)
        text = '<b>➕ Add Rank Rule (1/8)</b>\n\nSelect the <b>Source Group</b> where the command will be monitored:'
        keyboard = self.keyboards.cmd_fwd_select_source_group_keyboard(groups)
        await query.message.edit_text(text, reply_markup=keyboard)
        await state.set_state(ManagementStates.cmd_fwd_add_rule_source_group)

    async def wizard_process_source_group(self, query: types.CallbackQuery, state: FSMContext):
        group_id = int(query.data.split(':')[2])
        await state.update_data(source_group_id=group_id)
        await self.wizard_show_command_input(query, state)

    async def wizard_show_command_input(self, query: types.CallbackQuery, state: FSMContext):
        await query.message.edit_text('<b>➕ Add Rank Rule (2/8)</b>\n\nEnter the <b>exact command</b> to monitor (e.g., "/rank", "/lb 1h"):')
        await state.set_state(ManagementStates.cmd_fwd_add_rule_command)

    async def wizard_process_command_input(self, message: types.Message, state: FSMContext):
        command_text = message.text.strip()
        if not command_text:
            return await message.answer('❌ Command cannot be empty. Please enter a command.')

        await state.update_data(command_text=command_text)
        await message.delete()
        await self.wizard_show_monitored_users_menu(message, state)

    async def wizard_show_monitored_users_menu(self, query_or_message: types.Message | types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        monitored_users = data.get('monitored_users', [])
        text = f'<b>➕ Add Rank Rule (3/8)</b>\n\nWhose commands should be tracked?'
        text += '\n\n<b>Monitored Users:</b>\n' + (', '.join(map(str, monitored_users)) if monitored_users else 'Anyone')
        keyboard = self.keyboards.cmd_fwd_manage_users_keyboard(monitored_users, 'monitored', rule_id=data.get('rule_id'))
        if isinstance(query_or_message, types.Message):
            await query_or_message.answer(text, reply_markup=keyboard)
        else:
            await query_or_message.message.edit_text(text, reply_markup=keyboard)
        await state.set_state(ManagementStates.cmd_fwd_add_rule_monitored_users)

    async def wizard_prompt_for_user_id(self, query: types.CallbackQuery, state: FSMContext, user_type: str):
        await query.message.edit_text(f'Enter User ID(s) to add (comma-separated):')
        await state.update_data(user_type=user_type)
        if user_type == 'monitored':
            await state.set_state(ManagementStates.cmd_fwd_add_monitored_user_id)
        else:
            await state.set_state(ManagementStates.cmd_fwd_add_replying_user_id)

    async def wizard_process_user_id_input(self, message: types.Message, state: FSMContext):
        try:
            user_ids = [int(uid.strip()) for uid in message.text.split(',')]
            data = await state.get_data()
            user_type = data.get('user_type')
            current_users = data.get(f'{user_type}_users', [])
            current_users.extend(user_ids)
            updated_users = list(set(current_users))
            await state.update_data({f'{user_type}_users': updated_users})

            # Immediately update the database if editing existing rule
            rule_id = data.get('rule_id')
            if rule_id:
                update_data = {}
                if user_type == 'monitored':
                    update_data['allowed_command_user_ids'] = updated_users
                else:
                    update_data['allowed_reply_user_ids'] = updated_users
                await self.cmd_fwd_model.update(rule_id, update_data)

            await message.delete()
            if user_type == 'monitored':
                await self.wizard_show_monitored_users_menu(message, state)
            else:
                await self.wizard_show_replying_users_menu(message, state)
        except ValueError:
            await message.answer('Invalid User ID(s). Please enter number(s) separated by commas.')

    async def wizard_remove_user(self, query: types.CallbackQuery, state: FSMContext, user_type: str, user_id: int):
        data = await state.get_data()
        current_users = data.get(f'{user_type}_users', [])
        if user_id in current_users:
            current_users.remove(user_id)
        await state.update_data({f'{user_type}_users': current_users})

        # Immediately update the database
        rule_id = data.get('rule_id')
        if rule_id:
            update_data = {}
            if user_type == 'monitored':
                update_data['allowed_command_user_ids'] = current_users
            else:
                update_data['allowed_reply_user_ids'] = current_users
            await self.cmd_fwd_model.update(rule_id, update_data)

        if user_type == 'monitored':
            await self.wizard_show_monitored_users_menu(query, state)
        else:
            await self.wizard_show_replying_users_menu(query, state)

    async def wizard_show_forwarding_bot_selection(self, query: types.CallbackQuery, state: FSMContext):
        userbots = await self.bot_model.get_active_userbots()
        text = '<b>➕ Add Rank Rule (4/8)</b>\n\nSelect the <b>Userbot</b> that will forward the reply:'
        keyboard = self.keyboards.cmd_fwd_select_forwarding_bot_keyboard(userbots)
        await query.message.edit_text(text, reply_markup=keyboard)
        await state.set_state(ManagementStates.cmd_fwd_add_rule_forwarding_bot)

    async def wizard_process_forwarding_bot(self, query: types.CallbackQuery, state: FSMContext):
        bot_id = int(query.data.split(':')[2])
        await state.update_data(forwarding_userbot_id=bot_id)
        data = await state.get_data()
        if data.get('rule_id'):
            # If editing, save and return to details
            await self.cmd_fwd_model.update(data['rule_id'], {'forwarding_userbot_id': bot_id})
            await state.clear()
            await self.show_rule_details(query, data['rule_id'])
        else:
            # If creating, continue wizard
            await self.wizard_prompt_for_destination(query, state)

    async def wizard_prompt_for_destination(self, query: types.CallbackQuery, state: FSMContext):
        await query.message.edit_text('<b>➕ Add Rank Rule (5/8)</b>\n\nEnter the ID of the <b>Destination Channel</b>:')
        await state.set_state(ManagementStates.cmd_fwd_add_rule_destination)

    async def wizard_process_destination_input(self, message: types.Message, state: FSMContext):
        try:
            channel_id = int(message.text)
            await state.update_data(destination_channel_id=channel_id)
            await message.delete()
            await self.wizard_show_replying_users_menu(message, state)
        except ValueError:
            await message.answer('Invalid Channel ID. Please enter a number.')

    async def wizard_show_replying_users_menu(self, query_or_message: types.Message | types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        replying_users = data.get('replying_users', [])
        text = f'<b>➕ Add Rank Rule (6/8)</b>\n\nWhose replies should be forwarded?'
        text += '\n\n<b>Replying Users:</b>\n' + (', '.join(map(str, replying_users)) if replying_users else 'Anyone')
        keyboard = self.keyboards.cmd_fwd_manage_users_keyboard(replying_users, 'replying', rule_id=data.get('rule_id'))
        if isinstance(query_or_message, types.Message):
            await query_or_message.answer(text, reply_markup=keyboard)
        else:
            await query_or_message.message.edit_text(text, reply_markup=keyboard)
        await state.set_state(ManagementStates.cmd_fwd_add_rule_replying_users)

    async def wizard_show_schedule_options(self, query: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        step_text = '<b>⚙️ Schedule Settings</b>' if data.get('rule_id') else '<b>➕ Add Rank Rule (7/8)</b>\n\n<b>Schedule Options:</b>'
        text = f'{step_text}\n\nHow often should this command be sent automatically?'
        keyboard = self.keyboards.cmd_fwd_schedule_options_keyboard()
        await query.message.edit_text(text, reply_markup=keyboard)
        await state.set_state(ManagementStates.cmd_fwd_add_rule_schedule)

    async def wizard_process_schedule_option(self, query: types.CallbackQuery, state: FSMContext):
        schedule_option = query.data.split(':')[2]
        data = await state.get_data()

        if schedule_option == 'none':
            await state.update_data(schedule_enabled=False, schedule_interval_minutes=None)
        elif schedule_option == 'custom':
            await query.message.edit_text('<b>⚙️ Custom Interval</b>\n\nEnter interval in minutes (e.g., 30 for 30 minutes, 90 for 1.5 hours):')
            await state.set_state(ManagementStates.cmd_fwd_add_rule_custom_interval)
            return
        else:
            # Preset intervals
            interval_minutes = int(schedule_option)
            await state.update_data(schedule_enabled=True, schedule_interval_minutes=interval_minutes)

        # If editing existing rule, save and return
        if data.get('rule_id'):
            schedule_data = await state.get_data()
            await self.cmd_fwd_model.update_schedule(
                data['rule_id'],
                schedule_data.get('schedule_enabled', False),
                schedule_data.get('schedule_interval_minutes')
            )
            await state.clear()
            await self.show_rule_details(query, data['rule_id'])
        else:
            # Continue wizard
            await self.wizard_show_summary(query, state)

    async def wizard_process_custom_interval_input(self, message: types.Message, state: FSMContext):
        try:
            interval_minutes = int(message.text)
            if interval_minutes < 1:
                return await message.answer('❌ Interval must be at least 1 minute.')

            await state.update_data(schedule_enabled=True, schedule_interval_minutes=interval_minutes)
            await message.delete()

            data = await state.get_data()
            if data.get('rule_id'):
                # If editing, save and return
                await self.cmd_fwd_model.update_schedule(
                    data['rule_id'], True, interval_minutes
                )
                await state.clear()
                await self.show_rule_details_by_id(message, data['rule_id'])
            else:
                # Continue wizard
                await self.wizard_show_summary(message, state)
        except ValueError:
            await message.answer('❌ Invalid number. Please enter interval in minutes (e.g., 30).')

    async def wizard_show_summary(self, query_or_message: types.Message | types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        source_group = await self.group_model.get_by_id(data.get('source_group_id'))
        fwd_bot = await self.bot_model.get_by_id(data.get('forwarding_userbot_id'))

        if isinstance(query_or_message, types.Message):
            dest_channel_info = {'title': f"ID: {data.get('destination_channel_id')}"}
        else:
            dest_channel_info = await self._get_entity_info(query_or_message, data.get('destination_channel_id'))

        text = f'<b>➕ Add Rank Rule (8/8) - Summary</b>\n\n'
        text += f'<b>Source Group:</b> {source_group["title"]}\n'
        text += f'<b>Command:</b> {data.get("command_text")}\n'
        text += f'<b>Monitored Users:</b> {data.get("monitored_users", []) or "Anyone"}\n'
        bot_name = fwd_bot.get("display_name") or fwd_bot.get("session_name") if fwd_bot else "Not Set"
        text += f'<b>Forwarding Bot:</b> {bot_name}\n'
        text += f'<b>Destination Channel:</b> {dest_channel_info["title"]}\n'
        text += f'<b>Replying Users:</b> {data.get("replying_users", []) or "Anyone"}\n'

        # Add schedule info
        if data.get('schedule_enabled') and data.get('schedule_interval_minutes'):
            interval = data['schedule_interval_minutes']
            hours = interval // 60
            minutes = interval % 60
            if hours > 0:
                if minutes > 0:
                    interval_text = f"{hours}h {minutes}m"
                else:
                    interval_text = f"{hours}h"
            else:
                interval_text = f"{minutes}m"
            text += f'<b>Schedule:</b> Every {interval_text}'
        else:
            text += f'<b>Schedule:</b> Manual only'

        keyboard = self.keyboards.cmd_fwd_rule_summary_keyboard()

        if isinstance(query_or_message, types.Message):
            await query_or_message.answer(text, reply_markup=keyboard)
        else:
            await query_or_message.message.edit_text(text, reply_markup=keyboard)
        await state.set_state(ManagementStates.cmd_fwd_add_rule_summary)

    async def save_rule(self, query: types.CallbackQuery, state: FSMContext):
        data = await state.get_data()
        rule_id = data.get('rule_id')
        if rule_id:
            # Update existing rule
            update_data = {}
            if 'monitored_users' in data:
                update_data['allowed_command_user_ids'] = data['monitored_users']
            if 'replying_users' in data:
                update_data['allowed_reply_user_ids'] = data['replying_users']
            if 'command_text' in data:
                update_data['command_text'] = data['command_text']

            if update_data:
                await self.cmd_fwd_model.update(rule_id, update_data)
        else:
            # Create new rule
            await self.cmd_fwd_model.create_rule(
                source_group_id=data['source_group_id'],
                command_text=data['command_text'],
                destination_channel_id=data['destination_channel_id'],
                allowed_command_user_ids=data.get('monitored_users', []),
                allowed_reply_user_ids=data.get('replying_users', []),
                forwarding_userbot_id=data['forwarding_userbot_id'],
                schedule_enabled=data.get('schedule_enabled', False),
                schedule_interval_minutes=data.get('schedule_interval_minutes')
            )
        await state.clear()
        await query.message.edit_text('✅ Rank Rule saved successfully!')
        await self.show_rules_list(query)

    async def process_edit_command_input(self, message: types.Message, state: FSMContext):
        """Process command text edit input"""
        try:
            command_text = message.text.strip()
            if not command_text:
                return await message.answer('❌ Command cannot be empty. Please enter a command.')

            data = await state.get_data()
            rule_id = data.get('rule_id')
            if rule_id:
                await self.cmd_fwd_model.update(rule_id, {'command_text': command_text})
                await message.delete()
                await state.clear()
                await self.show_rule_details_by_id(message, rule_id)
            else:
                await message.answer('❌ Rule not found.')
        except Exception as e:
            logger.error(f'Error processing command edit: {e}')
            await message.answer('❌ An error occurred. Please try again.')

    async def show_rule_details_by_id(self, message: types.Message, rule_id: int):
        """Helper to show rule details via message (for state transitions)"""
        try:
            rule = await self.cmd_fwd_model.get_by_id(rule_id)
            if not rule:
                return await message.answer('Rule not found.')

            source_group = {'title': rule['source_group_title']}
            dest_channel_info = {'title': f"ID: {rule['destination_channel_id']}"}
            fwd_bot = await self.bot_model.get_by_id(rule['forwarding_userbot_id'])
            text = self.keyboards.cmd_fwd_rule_details_text(rule, source_group, dest_channel_info, fwd_bot)
            keyboard = self.keyboards.cmd_fwd_rule_details_menu(rule)
            await message.answer(text, reply_markup=keyboard)
        except Exception as e:
            logger.error(f'Error showing rule details: {e}')
            await message.answer('❌ An error occurred.')

    async def _get_entity_info(self, query_or_message, entity_id: int) -> Dict[str, Any]:
        bot = query_or_message.bot if hasattr(query_or_message, 'bot') else query_or_message.bot
        try:
            chat = await bot.get_chat(entity_id)
            return {'id': chat.id, 'title': chat.title or chat.full_name}
        except Exception:
            return {'id': entity_id, 'title': f'ID: {entity_id}'}
