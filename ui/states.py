from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    # Gain Alerts
    gain_alerts_add_type = State()
    gain_alerts_add_chat_id = State()
    gain_alerts_add_user_id = State()
    gain_alerts_confirm_add = State()
    gain_alerts_edit_name = State()
    gain_alerts_edit_sensitivity = State()
    gain_alerts_edit_template = State()
    gain_alerts_edit_sender = State()
    gain_alerts_edit_chart_threshold = State()
    gain_alerts_edit_chart_bot = State()
    gain_alerts_add_chart_group = State()
    gain_alerts_remove_chart_group = State()
    chart_groups_add_chat_id = State()
    awaiting_gain_threshold = State()
    awaiting_gain_template = State()
    awaiting_global_chart_threshold = State()
    awaiting_global_chart_bot = State()
    awaiting_chart_guardrails = State()
    awaiting_drop_threshold = State()
    awaiting_drop_floor = State()
    awaiting_guardrail_value = State()
    awaiting_source_guardrail_override = State()

    # Userbots
    userbot_login_phone = State()
    userbot_login_code = State()
    userbot_login_2fa = State()
    userbot_set_name = State()


class InvestStates(StatesGroup):
    selecting_source = State()
    selecting_user_scope = State()
    selecting_users = State()
    selecting_timeframe = State()
    selecting_hold = State()
    selecting_allocation = State()
    entering_custom_tokens = State()
    entering_custom_hold = State()


class AutoTraderStates(StatesGroup):
    awaiting_destination = State()
    awaiting_budget = State()
    awaiting_custom_budget = State()
    awaiting_per_coin = State()
    awaiting_custom_per_coin = State()
    awaiting_hold = State()
    awaiting_coin_cap = State()
    awaiting_custom_coin_cap = State()
    awaiting_channel_mode = State()
    awaiting_channels = State()
    awaiting_report_interval = State()
    awaiting_custom_interval = State()
    awaiting_stop_choice = State()
    awaiting_target_value = State()
    awaiting_bankrupt_floor = State()

class ManagementStates(StatesGroup):
    cmd_fwd_add_rule_source_group = State()
    cmd_fwd_add_rule_command = State()
    cmd_fwd_add_rule_monitored_users = State()
    cmd_fwd_add_rule_forwarding_bot = State()
    cmd_fwd_add_rule_destination = State()
    cmd_fwd_add_rule_replying_users = State()
    cmd_fwd_add_rule_schedule = State()
    cmd_fwd_add_rule_custom_interval = State()
    cmd_fwd_add_rule_summary = State()
    cmd_fwd_add_monitored_user_id = State()
    cmd_fwd_add_replying_user_id = State()
    cmd_fwd_edit_command = State()
    cmd_fwd_schedule_settings = State()
    cmd_fwd_add_excluded_text = State()
