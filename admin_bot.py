"""
Admin bot entrypoint for standalone gain alert service.
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command

from aiogram.types import BufferedInputFile, BotCommand

from alerts.templates import DEFAULT_GAIN_ALERT_TEMPLATE, missing_required_placeholders
from config import settings
from db import db
from models import MonitoredSourceModel, SettingsModel, TokenModel
from ui.handlers import GainAlertsHandler, SettingsHandler, UserbotsHandler
from ui.handlers.analytics_commands import AnalyticsCommandsHandler
from ui.handlers.info import InfoHandler
from ui.handlers.invest import InvestHandler
from ui.keyboards import Keyboards
from ui.routers.invest import get_invest_router
from ui.routers.registry import get_router_factories
from ui.handlers.command_forwarding import CommandForwardingHandler
from utils.logging_setup import configure_logging
from utils.tier_calculator import calculate_next_poll_time, format_duration, get_poll_interval_for_tier
from scheduler.dex_service import DexService, get_dex_service
from services.dexscreener_api import get_dexscreener_client
from models.analytics import AnalyticsModel

logger = logging.getLogger(__name__)


async def run_admin_bot() -> None:
    configure_logging()
    if not settings.mgmt_bot_token:
        raise RuntimeError("MGMT_BOT_TOKEN is required for the admin bot.")

    await db.connect()

    bot = Bot(
        token=settings.mgmt_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    logger.info("Admin bot online. Admin IDs: %s", settings.admin_telegram_ids_list)

    keyboards = Keyboards()
    token_model = TokenModel(db)
    settings_model = SettingsModel(db)
    source_model = MonitoredSourceModel(db)
    analytics_model = AnalyticsModel(db)
    dexscreener_api = get_dexscreener_client()
    sol_pattern = re.compile(settings.solana_pattern)
    bnb_pattern = re.compile(settings.bnb_pattern, re.IGNORECASE)

    async def cmd_menu(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        logger.info("[ADMIN_MENU] /menu from user %s (admins=%s)", user_id, settings.admin_telegram_ids_list)
        if user_id not in settings.admin_telegram_ids_list:
            logger.info("[ADMIN_MENU] User %s not authorized for /menu", user_id)
            return
        await message.answer(
            "<b>🎛 Gain Alert Console</b>\n\nSelect an option:",
            reply_markup=keyboards.main_menu(),
        )

    async def show_menu(query: types.CallbackQuery) -> None:
        user_id = query.from_user.id if query.from_user else None
        logger.info("[ADMIN_MENU] menu callback from user %s", user_id)
        await query.message.edit_text(
            "<b>🎛 Gain Alert Console</b>\n\nSelect an option:",
            reply_markup=keyboards.main_menu(),
        )
        await query.answer()

    dp.message.register(cmd_menu, Command(commands=["menu", "start"]))
    dp.callback_query.register(
        show_menu,
        F.data == "menu:main",
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    def _detect_chain(address: str) -> str | None:
        if sol_pattern.fullmatch(address):
            return "SOL"
        if bnb_pattern.fullmatch(address):
            return "BNB"
        return None

    def _format_timestamp(value) -> str:
        if not value:
            return "N/A"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        elapsed = int((datetime.now(timezone.utc) - value).total_seconds())
        return f"{value.strftime('%Y-%m-%d %H:%M UTC')} ({format_duration(elapsed)} ago)"

    def _format_mc(value) -> str:
        try:
            if value is None:
                return "N/A"
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return "N/A"
        if decimal_value <= 0:
            return "N/A"
        return DexService._format_mc_shorthand(decimal_value)

    async def cmd_all_commands(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        await message.answer(
            "<b>Gain alert:</b>\n"
            "📚 <b>Available Gain Alert Commands</b>\n\n"

            "🔍 <b>Token Inspector</b>\n"
            "<code>/i &lt;ca&gt;</code> - Inspect token details\n\n"

            "🎯 <b>Trigger Gain Alert</b>\n"
            "<code>/tri &lt;ca&gt; [p] [c]</code> - Force gain alert\n"
            "<code>/tri &lt;chat_id&gt; &lt;ca&gt; [p] [c]</code> - To specific chat\n"
            "Flags: <code>p</code>=peak MC, <code>c</code>=include chart\n\n"

            "📊 <b>Analytics</b>\n"
            "<code>/stats &lt;chat_id&gt; [period]</code> - Performance stats\n"
            "<code>/top [period]</code> - Leaderboard of best sources\n"
            "<code>/patterns &lt;chat_id&gt;</code> - Time pattern analysis\n"
            "<code>/besthold [chat_id] [period]</code> - Best hold duration\n"
            "<code>/invest &lt;amount&gt;</code> - Simulate investment P&L\n"
            "<code>/info &lt;chat_id&gt;|user:&lt;user_id&gt;|@username</code> - DB info & stats\n\n"

            "⏱ <b>Timeframes</b>\n"
            "<code>/timeframes</code> - List all hold durations\n"
            "<code>/addtimeframe &lt;label&gt; &lt;sec&gt; [def]</code> - Add new\n"
            "<code>/deltimeframe &lt;label&gt;</code> - Remove\n\n"

            "🔄 <b>Restart Monitoring</b>\n"
            "<code>/str &lt;ca&gt; [tier]</code> - Restart stopped token\n\n"

            "⛔ <b>Stop Monitoring</b>\n"
            "<code>/stop &lt;ca&gt;</code> - Stop tracking token\n\n"

            "⏸ <b>Pause Gain Alerts</b>\n"
            "<code>/stop_ca</code> - Pause alerts for all sources\n"
            "<code>/stop_ca &lt;chat_id&gt;</code> - Pause alerts for one chat/channel\n\n"
            "▶️ <b>Resume Gain Alerts</b>\n"
            "<code>/start_ca</code> - Resume alerts for all sources\n"
            "<code>/start_ca &lt;chat_id&gt;</code> - Resume alerts for one chat/channel\n\n"

            "🎛 <b>Management</b>\n"
            "<code>/menu</code> or <code>/start</code> - Show main menu\n"
            "<code>/all</code> - Show this command list",
            parse_mode="HTML",
        )

    async def cmd_inspect(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "🔍 <b>Token Inspector</b>\n\n"
                "Usage:\n"
                "<code>/i &lt;contract_address&gt;</code>\n\n"
                "Examples:\n"
                "• <code>/i HnKk7xPZmL7KRuUg...</code>\n"
                "• <code>/i 0x907D7eE6FB40C...</code>",
                parse_mode="HTML",
            )
            return

        raw_address = parts[1].strip()
        chain = _detect_chain(raw_address)
        if chain is None:
            await message.answer("❌ Unrecognised address. Provide a Solana or BNB contract.")
            return

        token = await token_model.db.fetchrow(
            "SELECT * FROM tokens_tracked WHERE LOWER(address) = LOWER($1) LIMIT 1",
            raw_address,
        )
        if not token:
            await message.answer(
                f"❌ Token not found: <code>{html.escape(raw_address)}</code>",
                parse_mode="HTML",
            )
            return

        token_id = token["id"]
        ticker = token.get("ticker") or raw_address[:8]
        status = token.get("status") or "unknown"
        tier = token.get("current_tier") or "N/A"
        first_seen_at = token.get("first_seen_at")
        last_checked_at = token.get("last_checked_at")

        tracked_rows = await token_model.db.fetch(
            """
            SELECT DISTINCT ON (tga.chat_id, tga.original_user_id)
                tga.chat_id,
                tga.original_user_id,
                tga.first_seen_mc,
                tga.last_alert_mc,
                tga.last_alert_at,
                ms.label,
                ms.name,
                ms.is_enabled,
                ms.sensitivity_pct,
                ms.assigned_userbot_id,
                ms.use_management_bot,
                ms.chart_enabled
            FROM token_group_alerts tga
            LEFT JOIN monitored_sources ms
                ON ms.chat_id = tga.chat_id
               AND (ms.user_id = tga.original_user_id OR ms.user_id IS NULL)
            WHERE tga.token_id = $1
            ORDER BY tga.chat_id, tga.original_user_id, (ms.user_id IS NULL)
            """,
            token_id,
        )

        lines = [
            "🔍 <b>Token Inspector</b>",
            "",
            f"<b>Token:</b> {html.escape(ticker)}",
            f"<b>Address:</b> <code>{html.escape(raw_address)}</code>",
            f"<b>Chain:</b> {chain}",
            f"<b>Status:</b> {html.escape(status)}",
            f"<b>Tier:</b> {html.escape(tier)}",
            f"<b>First Seen:</b> {_format_timestamp(first_seen_at)}",
            f"<b>Last Checked:</b> {_format_timestamp(last_checked_at)}",
            f"<b>First MC:</b> {_format_mc(token.get('first_seen_mc'))}",
            f"<b>Last MC:</b> {_format_mc(token.get('last_mc'))}",
            f"<b>Peak MC:</b> {_format_mc(token.get('peak_mc'))}",
            f"<b>Last Alert MC:</b> {_format_mc(token.get('last_alert_mc'))}",
            "",
            f"<b>Tracked Chats:</b> {len(tracked_rows)}",
        ]

        if tracked_rows:
            lines.append("")
            lines.append("<b>Chats</b>")
            max_rows = 8
            for row in tracked_rows[:max_rows]:
                label = row.get("label") or row.get("name")
                label_text = f" ({html.escape(label)})" if label else ""
                enabled = row.get("is_enabled")
                enabled_text = "🟢" if enabled or enabled is None else "🔴"
                sensitivity = row.get("sensitivity_pct")
                sensitivity_text = f"{Decimal(str(sensitivity)):.0f}%" if sensitivity is not None else "global"
                sender_text = "mgmt" if row.get("use_management_bot") else "userbot"
                chart_text = "chart" if row.get("chart_enabled") else "no chart"
                chat_id = row.get("chat_id")
                lines.append(
                    f"• <code>{chat_id}</code>{label_text} {enabled_text} "
                    f"| sens {sensitivity_text} | {sender_text} | {chart_text}"
                )
            if len(tracked_rows) > max_rows:
                lines.append(f"<i>... and {len(tracked_rows) - max_rows} more</i>")

        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_restart(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "🔄 <b>Restart Monitoring</b>\n\n"
                "Usage:\n"
                "<code>/str &lt;contract_address&gt; [tier]</code>\n\n"
                "Examples:\n"
                "• <code>/str HnKk7xPZmL7...</code>\n"
                "• <code>/str HnKk7xPZmL7... tier_c</code>",
                parse_mode="HTML",
            )
            return

        raw_address = parts[1].strip()
        chain = _detect_chain(raw_address)
        if chain is None:
            await message.answer("❌ Unrecognised address. Provide a Solana or BNB contract.")
            return

        token = await token_model.get_by_address(raw_address)
        if not token:
            await message.answer(
                f"❌ Token not found: <code>{html.escape(raw_address)}</code>",
                parse_mode="HTML",
            )
            return

        token_id = token["id"]
        first_seen_at = token.get("first_seen_at") or datetime.now(timezone.utc)

        tier = None
        next_poll = None
        if len(parts) >= 3:
            tier = parts[2].strip().lower()
            poll_seconds = get_poll_interval_for_tier(tier)
            next_poll = datetime.now(timezone.utc) + timedelta(seconds=poll_seconds)
        else:
            tier, next_poll = calculate_next_poll_time(first_seen_at)

        await token_model.set_status(token_id, "active")
        await token_model.set_stop_reason(token_id, None)
        await token_model.update_tier(token_id, tier, next_poll)

        ticker = token.get("ticker") or raw_address[:8]
        await message.answer(
            f"✅ Restarted monitoring token <b>{html.escape(ticker)}</b>\n"
            f"Address: <code>{html.escape(raw_address)}</code>\n"
            f"Status: <b>active</b>\n"
            f"Tier: <b>{html.escape(tier)}</b>\n"
            f"Next Poll: {next_poll.strftime('%H:%M:%S UTC')}",
            parse_mode="HTML",
        )

    async def cmd_stop(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "⛔ <b>Stop Monitoring</b>\n\n"
                "Usage:\n"
                "<code>/stop &lt;contract_address&gt;</code>\n\n"
                "Example:\n"
                "• <code>/stop HnKk7xPZmL7...</code>",
                parse_mode="HTML",
            )
            return

        raw_address = parts[1].strip()
        chain = _detect_chain(raw_address)
        if chain is None:
            await message.answer("❌ Unrecognised address. Provide a Solana or BNB contract.")
            return

        token = await token_model.get_by_address(raw_address)
        if not token:
            await message.answer(
                f"❌ Token not found: <code>{html.escape(raw_address)}</code>",
                parse_mode="HTML",
            )
            return

        token_id = token["id"]
        current_status = token.get("status")
        if current_status == "stopped":
            await message.answer(
                f"⚠️ Token <code>{html.escape(raw_address)}</code> is already stopped.\n"
                f"Stop Reason: {html.escape(token.get('stop_reason') or 'Unknown')}",
                parse_mode="HTML",
            )
            return

        await token_model.set_status(token_id, "stopped")
        await token_model.set_stop_reason(token_id, "admin_manual_stop")

        ticker = token.get("ticker") or raw_address[:8]
        await message.answer(
            f"✅ Stopped monitoring token <b>{html.escape(ticker)}</b>\n"
            f"Address: <code>{html.escape(raw_address)}</code>\n"
            f"Status: <b>stopped</b>\n"
            f"Reason: admin_manual_stop",
            parse_mode="HTML",
        )

    async def cmd_stop_ca(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) == 1:
            result = await db.execute(
                """
                UPDATE tokens_tracked
                SET status = 'stopped',
                    stop_reason = 'admin_ca_stop_all'
                WHERE status != 'stopped'
                """
            )
            count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
            await message.answer(f"⛔ Stopped monitoring all contracts ({count} updated).", parse_mode="HTML")
            return

        raw_arg = parts[1].strip()

        # If numeric, treat as chat ID to stop all contracts associated with that chat
        try:
            chat_id_arg = int(raw_arg)
            token_rows = await db.fetch(
                """
                SELECT DISTINCT token_id
                FROM token_group_alerts
                WHERE chat_id = $1
                """,
                chat_id_arg,
            )
            if not token_rows:
                await message.answer(f"❌ No contracts found for chat <code>{chat_id_arg}</code>.", parse_mode="HTML")
                return
            token_ids = [row["token_id"] for row in token_rows]
            await db.execute(
                """
                UPDATE tokens_tracked
                SET status = 'stopped',
                    stop_reason = 'admin_ca_stop_chat'
                WHERE id = ANY($1::BIGINT[])
                """,
                token_ids,
            )
            await message.answer(
                f"⛔ Stopped monitoring {len(token_ids)} contract(s) for chat <code>{chat_id_arg}</code>.",
                parse_mode="HTML",
            )
            return
        except ValueError:
            pass

        # Otherwise treat all remaining args as contract addresses
        addresses = parts[1:]
        stopped = 0
        not_found: list[str] = []
        invalid: list[str] = []

        for raw_address in addresses:
            address = raw_address.strip()
            chain = _detect_chain(address)
            if chain is None:
                invalid.append(address)
                continue

            token = await token_model.get_by_address(address)
            if not token:
                not_found.append(address)
                continue

            await token_model.set_status(token["id"], "stopped")
            await token_model.set_stop_reason(token["id"], "admin_ca_stop")
            stopped += 1

        lines = []
        if stopped:
            lines.append(f"✅ Stopped monitoring {stopped} contract(s).")
        if not_found:
            lines.append("❌ Not found: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in not_found))
        if invalid:
            lines.append("⚠️ Invalid address format: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in invalid))

        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_start_ca(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "✅ <b>Resume Token Monitoring</b>\n\n"
                "Usage:\n"
                "<code>/start_ca &lt;contract_address&gt; [tier]</code>\n\n"
                "Tier optional (a-f).",
                parse_mode="HTML",
            )
            return

        addresses = [parts[1].strip()]
        tier_arg = parts[2].strip().lower() if len(parts) >= 3 else None

        restarted = 0
        invalid = []
        not_found = []
        bad_tier = False

        valid_tiers = {"tier_a", "tier_b", "tier_c", "tier_d", "tier_e", "tier_f", "a", "b", "c", "d", "e", "f"}
        if tier_arg and tier_arg not in valid_tiers:
            bad_tier = True

        for raw_address in addresses:
            chain = _detect_chain(raw_address)
            if chain is None:
                invalid.append(raw_address)
                continue

            token = await token_model.get_by_address(raw_address)
            if not token:
                not_found.append(raw_address)
                continue

            token_id = token["id"]

            if bad_tier:
                continue

            if tier_arg:
                tier = f"tier_{tier_arg}" if len(tier_arg) == 1 else tier_arg
                poll_seconds = get_poll_interval_for_tier(tier)
                next_poll = datetime.now(timezone.utc) + timedelta(seconds=poll_seconds)
            else:
                first_seen_at = token.get("first_seen_at") or datetime.now(timezone.utc)
                tier, next_poll = calculate_next_poll_time(first_seen_at)

            await token_model.set_status(token_id, "active")
            await token_model.set_stop_reason(token_id, None)
            await token_model.update_tier(token_id, tier, next_poll)
            restarted += 1

        lines = []
        if restarted:
            lines.append(f"✅ Resumed monitoring {restarted} contract(s).")
        if bad_tier:
            lines.append("⚠️ Invalid tier. Use a-f (or tier_a..tier_f).")
        if not_found:
            lines.append("❌ Not found: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in not_found))
        if invalid:
            lines.append("⚠️ Invalid address format: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in invalid))

        await message.answer("\n".join(lines), parse_mode="HTML")


    async def cmd_clean_contracts(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2 or parts[1].strip().lower() not in ("confirm", "yes"):
            await message.answer(
                "🧹 <b>Danger Zone</b>\n\n"
                "This will wipe every tracked contract address and related alerts.\n\n"
                "To confirm, run:\n"
                "<code>/clean_ca confirm</code>",
                parse_mode="HTML",
            )
            return

        await db.execute("DELETE FROM tokens_tracked")
        await message.answer("✅ All tracked contract addresses have been wiped.", parse_mode="HTML")

    async def cmd_trigger(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "🎯 <b>Trigger Gain Alert Command</b>\n\n"
                "Force-send gain alerts to chats where a token was posted.\n\n"
                "📋 <b>Usage:</b>\n"
                "<code>/tri &lt;contract_address&gt; [flags]</code>\n"
                "<code>/tri &lt;chat_id&gt; &lt;contract_address&gt; [flags]</code>\n\n"
                "🚩 <b>Flags:</b>\n"
                "  <code>p</code> = Use <b>peak MC</b> instead of current MC\n"
                "  <code>c</code> = Include <b>chart</b> in alert\n\n"
                "📖 <b>Examples:</b>\n"
                "• <code>/tri HnKk7xPZmL7...</code>\n"
                "• <code>/tri HnKk7xPZmL7... c</code>\n"
                "• <code>/tri HnKk7xPZmL7... p</code>\n"
                "• <code>/tri -1001234567890 HnKk7xPZmL7... p c</code>",
                parse_mode="HTML",
            )
            return

        target_chat_id = None
        raw_address = None
        include_chart = False
        use_peak_mc = False

        first_arg = parts[1].strip()
        try:
            potential_chat_id = int(first_arg)
            if len(parts) < 3:
                await message.answer(
                    "❌ Missing contract address after chat ID\n"
                    "Usage: /tri <chat_id> <contract_address> [p] [c]",
                    parse_mode="HTML",
                )
                return
            target_chat_id = potential_chat_id
            raw_address = parts[2].strip()
            flags = [p.lower() for p in parts[3:]]
        except ValueError:
            raw_address = first_arg
            flags = [p.lower() for p in parts[2:]]

        include_chart = "c" in flags
        use_peak_mc = "p" in flags or "peak" in flags

        chain = _detect_chain(raw_address)
        if chain is None:
            await message.answer("❌ Unrecognised address. Provide a Solana or BNB contract.")
            return

        token = await token_model.get_by_address(raw_address)
        if not token:
            await message.answer(
                f"❌ Token not found: <code>{html.escape(raw_address)}</code>",
                parse_mode="HTML",
            )
            return

        ticker = token.get("ticker") or raw_address[:8]
        first_seen_mc = token.get("first_seen_mc") or Decimal(0)
        chosen_mc = token.get("peak_mc") if use_peak_mc else token.get("last_mc")
        chosen_mc = Decimal(str(chosen_mc or 0))

        if chosen_mc <= 0 or first_seen_mc <= 0:
            await message.answer(
                f"❌ Cannot trigger alert for <b>{html.escape(ticker)}</b>\n"
                "Missing market cap data. Token may need to be polled first.",
                parse_mode="HTML",
            )
            return

        template_context = {
            "address": raw_address,
            "token_symbol": ticker,
            "elapsed_time": DexService._format_elapsed_time(token.get("first_seen_at")),
        }

        global_template = await settings_model.get_gain_alert_template_text()

        tracking_rows = await db.fetch(
            """
            SELECT
                tga.chat_id,
                tga.original_message_id,
                tga.original_user_id,
                tga.first_seen_mc AS group_first_seen_mc,
                ms.is_enabled,
                ms.sensitivity_pct,
                ms.assigned_userbot_id,
                ms.template_text,
                ms.use_management_bot,
                ms.chart_enabled,
                ms.chart_bot_id,
                ms.chart_mc_threshold,
                ARRAY_REMOVE(ARRAY_AGG(mst.target_chat_id), NULL) AS extra_targets
            FROM token_group_alerts tga
            LEFT JOIN monitored_sources ms
                ON ms.chat_id = tga.chat_id
               AND (ms.user_id = tga.original_user_id OR ms.user_id IS NULL)
            LEFT JOIN monitored_source_targets mst ON mst.source_id = ms.id
            WHERE tga.token_id = $1
            GROUP BY
                tga.chat_id,
                tga.original_message_id,
                tga.original_user_id,
                tga.first_seen_mc,
                ms.is_enabled,
                ms.sensitivity_pct,
                ms.assigned_userbot_id,
                ms.template_text,
                ms.use_management_bot,
                ms.chart_enabled,
                ms.chart_bot_id,
                ms.chart_mc_threshold
            """,
            token["id"],
        )

        if target_chat_id is not None:
            tracking_rows = [row for row in tracking_rows if row.get("chat_id") == target_chat_id]

        if not tracking_rows:
            await message.answer(
                f"❌ No tracked chats found for <b>{html.escape(ticker)}</b>.",
                parse_mode="HTML",
            )
            return

        # Fetch chart once before the loop (like main script)
        chart_bytes = None
        if include_chart:
            dex_service = get_dex_service()
            if dex_service.chart_fetcher:
                chart_config = await settings_model.get_global_chart_settings()
                chart_bot_id = chart_config.get("chart_bot_id")
                if chart_bot_id:
                    try:
                        logger.info("[TRIGGER] Fetching chart for %s...", raw_address[:8])
                        chart_bytes = await dex_service.chart_fetcher.fetch_chart_for_token(
                            contract_address=raw_address,
                            chart_bot_id=int(chart_bot_id),
                        )
                        if chart_bytes:
                            logger.info("[TRIGGER] Chart fetched (%s bytes)", len(chart_bytes))
                    except Exception as exc:
                        logger.error("[TRIGGER] Chart fetch failed: %s", exc, exc_info=True)
                else:
                    logger.warning("[TRIGGER] Chart requested but no chart_bot_id configured")
            else:
                logger.warning("[TRIGGER] Chart requested but chart_fetcher not available (userbots not running?)")

        status_msg = (
            f"🎯 Triggering forced gain alert for <b>{html.escape(ticker)}</b>\n"
            f"📍 Targets: {len(tracking_rows)}\n"
            f"💰 {'PEAK' if use_peak_mc else 'CURRENT'} MC: {DexService._format_mc_shorthand(chosen_mc)}\n"
            f"📊 Chart: {'✅ Fetched' if chart_bytes else ('⚠️ Failed' if include_chart else '❌ Disabled')}\n\n"
            "Sending alerts..."
        )
        await message.answer(status_msg, parse_mode="HTML")

        success_count = 0
        failed_count = 0
        skipped_userbot = 0

        dex_service = get_dex_service()
        workers_cache = {}

        for row in tracking_rows:
            chat_id = row.get("chat_id")
            is_enabled = row.get("is_enabled")
            if is_enabled is False:
                continue

            use_management_bot_flag = bool(row.get("use_management_bot")) if row.get("use_management_bot") is not None else False
            assigned_userbot_id = row.get("assigned_userbot_id")

            group_first_seen = row.get("group_first_seen_mc") or first_seen_mc
            try:
                group_first_seen = Decimal(str(group_first_seen))
            except (InvalidOperation, TypeError, ValueError):
                group_first_seen = first_seen_mc

            multiplier_value = float(chosen_mc / group_first_seen) if group_first_seen > 0 else 1.0
            template_values = dict(template_context)
            template_values.update(
                {
                    "multiplier": f"{multiplier_value:.1f}x",
                    "first_market_cap": DexService._format_mc_shorthand(group_first_seen),
                    "current_market_cap": DexService._format_mc_shorthand(chosen_mc),
                    "gain_emoji": DexService._multiplier_to_emoji(multiplier_value),
                }
            )

            template_override = row.get("template_text")
            if not template_override:
                try:
                    chat_records = await source_model.get_by_chat(chat_id)
                    template_override = next(
                        (record.get("template_text") for record in chat_records if record.get("template_text")),
                        None,
                    )
                except Exception:
                    template_override = None

            template_candidate = template_override or global_template or DEFAULT_GAIN_ALERT_TEMPLATE
            missing = missing_required_placeholders(template_candidate)
            if missing:
                template_candidate = global_template or DEFAULT_GAIN_ALERT_TEMPLATE

            try:
                alert_message = template_candidate.format(**template_values)
            except KeyError:
                failed_count += 1
                continue

            extra_targets = row.get("extra_targets") or []
            target_chats = {chat_id}
            target_chats.update(extra_targets)

            for target_chat in target_chats:
                try:
                    target_chat_int = int(target_chat)
                except (TypeError, ValueError):
                    failed_count += 1
                    continue

                reply_id = row.get("original_message_id") if target_chat_int == chat_id else None

                try:
                    result = None

                    if use_management_bot_flag:
                        # Send via management bot (supports photos)
                        if dex_service.management_bot:
                            result = await dex_service.management_bot.send_message(
                                chat_id=target_chat_int,
                                message=alert_message,
                                reply_to_message_id=reply_id,
                                photo_bytes=chart_bytes,
                            )
                        else:
                            # Fallback to bot.send_photo/send_message
                            if chart_bytes:
                                input_file = BufferedInputFile(chart_bytes, filename="chart.jpg")
                                sent = await bot.send_photo(
                                    chat_id=target_chat_int,
                                    photo=input_file,
                                    caption=alert_message,
                                    reply_to_message_id=reply_id,
                                )
                            else:
                                sent = await bot.send_message(
                                    chat_id=target_chat_int,
                                    text=alert_message,
                                    reply_to_message_id=reply_id,
                                    disable_web_page_preview=True,
                                )
                            result = {"success": True, "message_id": sent.message_id}
                    else:
                        # Send via userbot
                        if not dex_service.userbot_manager:
                            skipped_userbot += 1
                            continue

                        worker = None
                        if assigned_userbot_id:
                            worker = dex_service.userbot_manager.get_all_workers().get(assigned_userbot_id)
                            if not worker:
                                logger.warning("[TRIGGER] Assigned userbot %s not available", assigned_userbot_id)

                        if not worker:
                            workers = dex_service.userbot_manager.get_all_workers()
                            if not workers:
                                skipped_userbot += 1
                                continue
                            worker = next(iter(workers.values()))

                        worker_id = getattr(worker, "userbot_id", None)
                        if worker_id is None:
                            skipped_userbot += 1
                            continue

                        executor = workers_cache.get(worker_id)
                        if executor is None:
                            executor = getattr(worker, "call_executor", None)
                            workers_cache[worker_id] = executor

                        if executor:
                            result = await executor.send_alert_message(
                                target_chat_id=target_chat_int,
                                message=alert_message,
                                reply_to_message_id=reply_id,
                                photo_bytes=chart_bytes,
                            )
                        else:
                            skipped_userbot += 1
                            continue

                    if result and result.get("success"):
                        success_count += 1
                        await db.execute(
                            """
                            UPDATE token_group_alerts
                            SET last_alert_mc = $1
                            WHERE token_id = $2 AND chat_id = $3
                            """,
                            chosen_mc,
                            token["id"],
                            chat_id,
                        )
                    else:
                        failed_count += 1

                except Exception as exc:
                    logger.error("[TRIGGER] Error sending to %s: %s", target_chat_int, exc)
                    failed_count += 1

        if success_count:
            await token_model.update_last_alert_mc(token["id"], chosen_mc)

        summary = (
            f"✅ Sent: {success_count}\n"
            f"❌ Failed: {failed_count}\n"
            f"⏭ Skipped (no userbot): {skipped_userbot}"
        )
        await message.answer(summary, parse_mode="HTML")

    gain_alerts_handler = GainAlertsHandler(db)
    settings_handler = SettingsHandler(db, keyboards)
    userbots_handler = UserbotsHandler(db, keyboards)
    cmd_fwd_handler = CommandForwardingHandler(db, keyboards)
    analytics_handler = AnalyticsCommandsHandler(db)
    info_handler = InfoHandler()
    invest_handler = InvestHandler(analytics_model, dexscreener_api, source_model)

    async def show_settings(query: types.CallbackQuery) -> None:
        await settings_handler.show_settings_menu(query)

    dp.callback_query.register(
        show_settings,
        F.data == "menu:settings",
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    for register_factory in get_router_factories(gain_alerts_handler, userbots_handler, settings_handler, cmd_fwd_handler):
        register_factory(dp)

    invest_router = get_invest_router(invest_handler, settings)
    dp.include_router(invest_router)

    dp.message.register(
        cmd_all_commands,
        Command(commands=["all", "commands", "help"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_inspect,
        Command(commands=["i"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_restart,
        Command(commands=["restart", "str"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_stop,
        Command(commands=["stop"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_stop_ca,
        Command(commands=["stop_ca"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_start_ca,
        Command(commands=["start_ca"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_clean_contracts,
        Command(commands=["clean_ca", "wipe_ca"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        cmd_trigger,
        Command(commands=["trigger", "tri"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    # Analytics commands
    dp.message.register(
        analytics_handler.cmd_stats,
        Command(commands=["stats"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        analytics_handler.cmd_top,
        Command(commands=["top", "leaderboard"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        analytics_handler.cmd_patterns,
        Command(commands=["patterns"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        analytics_handler.cmd_besthold,
        Command(commands=["besthold"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        info_handler.cmd_info,
        Command(commands=["info", "whois", "chatinfo"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.callback_query.register(
        analytics_handler.handle_timezone_selection,
        F.data.startswith("patterns:tz:"),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        settings_handler.cmd_timeframes,
        Command(commands=["timeframes"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        settings_handler.cmd_add_timeframe,
        Command(commands=["addtimeframe"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(
        settings_handler.cmd_del_timeframe,
        Command(commands=["deltimeframe"]),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="i", description="Inspect token details"),
        BotCommand(command="tri", description="Force gain alert"),
        BotCommand(command="str", description="Restart stopped token"),
        BotCommand(command="stop", description="Stop tracking token"),
        BotCommand(command="stop_ca", description="Stop CA tracking"),
        BotCommand(command="start_ca", description="Resume CA tracking"),
        BotCommand(command="stats", description="Performance stats"),
        BotCommand(command="top", description="Leaderboard"),
        BotCommand(command="patterns", description="Time pattern analysis"),
        BotCommand(command="besthold", description="Best hold duration"),
        BotCommand(command="invest", description="Investment simulator"),
        BotCommand(command="info", description="DB info"),
        BotCommand(command="whois", description="DB info"),
        BotCommand(command="timeframes", description="Hold durations"),
        BotCommand(command="menu", description="Show main menu"),
        BotCommand(command="all", description="Show all commands"),
    ])
    await dp.start_polling(bot)


async def create_admin_dispatcher() -> None:
    """Create and run admin bot dispatcher (for use when integrated with main service)."""
    if not settings.mgmt_bot_token:
        raise RuntimeError("MGMT_BOT_TOKEN is required for the admin bot.")

    bot = Bot(
        token=settings.mgmt_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    logger.info("Admin bot online (integrated). Admin IDs: %s", settings.admin_telegram_ids_list)

    keyboards = Keyboards()
    token_model = TokenModel(db)
    settings_model = SettingsModel(db)
    source_model = MonitoredSourceModel(db)
    sol_pattern = re.compile(settings.solana_pattern)
    bnb_pattern = re.compile(settings.bnb_pattern, re.IGNORECASE)

    def _detect_chain(address: str) -> str | None:
        if sol_pattern.fullmatch(address):
            return "SOL"
        if bnb_pattern.fullmatch(address):
            return "BNB"
        return None

    def _format_timestamp(value) -> str:
        if not value:
            return "N/A"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        elapsed = int((datetime.now(timezone.utc) - value).total_seconds())
        return f"{value.strftime('%Y-%m-%d %H:%M UTC')} ({format_duration(elapsed)} ago)"

    def _format_mc(value) -> str:
        try:
            if value is None:
                return "N/A"
            decimal_value = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return "N/A"
        if decimal_value <= 0:
            return "N/A"
        return DexService._format_mc_shorthand(decimal_value)

    async def cmd_menu(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else None
        logger.info("[ADMIN_MENU] /menu from user %s (admins=%s)", user_id, settings.admin_telegram_ids_list)
        if user_id not in settings.admin_telegram_ids_list:
            logger.info("[ADMIN_MENU] User %s not authorized for /menu", user_id)
            return
        await message.answer(
            "<b>🎛 Gain Alert Console</b>\n\nSelect an option:",
            reply_markup=keyboards.main_menu(),
        )

    async def show_menu(query: types.CallbackQuery) -> None:
        user_id = query.from_user.id if query.from_user else None
        logger.info("[ADMIN_MENU] menu callback from user %s", user_id)
        await query.message.edit_text(
            "<b>🎛 Gain Alert Console</b>\n\nSelect an option:",
            reply_markup=keyboards.main_menu(),
        )
        await query.answer()

    dp.message.register(cmd_menu, Command(commands=["menu", "start"]))
    dp.callback_query.register(
        show_menu,
        F.data == "menu:main",
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    async def cmd_all_commands(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return
        await message.answer(
            "<b>Gain alert:</b>\n"
            "📚 <b>Available Gain Alert Commands</b>\n\n"

            "🔍 <b>Token Inspector</b>\n"
            "<code>/i &lt;ca&gt;</code> - Inspect token details\n\n"

            "🎯 <b>Trigger Gain Alert</b>\n"
            "<code>/tri &lt;ca&gt; [p] [c]</code> - Force gain alert\n"
            "<code>/tri &lt;chat_id&gt; &lt;ca&gt; [p] [c]</code> - To specific chat\n"
            "Flags: <code>p</code>=peak MC, <code>c</code>=include chart\n\n"

            "📊 <b>Analytics</b>\n"
            "<code>/stats &lt;chat_id&gt; [period]</code> - Performance stats\n"
            "<code>/top [period]</code> - Leaderboard of best sources\n"
            "<code>/patterns &lt;chat_id&gt;</code> - Time pattern analysis\n"
            "<code>/besthold [chat_id] [period]</code> - Best hold duration\n"
            "<code>/invest &lt;amount&gt;</code> - Simulate investment P&L\n"
            "<code>/info &lt;chat_id&gt;|user:&lt;user_id&gt;|@username</code> - DB info & stats\n\n"

            "⏱ <b>Timeframes</b>\n"
            "<code>/timeframes</code> - List all hold durations\n"
            "<code>/addtimeframe &lt;label&gt; &lt;sec&gt; [def]</code> - Add new\n"
            "<code>/deltimeframe &lt;label&gt;</code> - Remove\n\n"

            "🔄 <b>Restart Monitoring</b>\n"
            "<code>/str &lt;ca&gt; [tier]</code> - Restart stopped token\n\n"

            "⛔ <b>Stop Monitoring</b>\n"
            "<code>/stop &lt;ca&gt;</code> - Stop tracking token\n\n"

            "⛔ <b>Stop Token Monitoring</b>\n"
            "<code>/stop_ca</code> - Stop monitoring ALL contract addresses\n"
            "<code>/stop_ca &lt;chat_id&gt;</code> - Stop monitoring all contracts from that chat/channel\n"
            "<code>/stop_ca &lt;ca&gt; [&lt;ca&gt;...]</code> - Stop specific contract address(es)\n\n"
            "✅ <b>Resume Token Monitoring</b>\n"
            "<code>/start_ca &lt;ca&gt; [tier]</code> - Resume monitoring a contract address (tier optional)\n\n"

            "🎛 <b>Management</b>\n"
            "<code>/menu</code> or <code>/start</code> - Show main menu\n"
            "<code>/all</code> - Show this command list",
            parse_mode="HTML",
        )

    async def cmd_inspect(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "🔍 <b>Token Inspector</b>\n\nUsage: <code>/i &lt;contract_address&gt;</code>",
                parse_mode="HTML",
            )
            return
        raw_address = parts[1].strip()
        chain = _detect_chain(raw_address)
        if chain is None:
            await message.answer("❌ Unrecognised address.")
            return
        token = await token_model.db.fetchrow(
            "SELECT * FROM tokens_tracked WHERE LOWER(address) = LOWER($1) LIMIT 1",
            raw_address,
        )
        if not token:
            await message.answer(f"❌ Token not found: <code>{html.escape(raw_address)}</code>", parse_mode="HTML")
            return
        ticker = token.get("ticker") or raw_address[:8]
        lines = [
            f"🔍 <b>{html.escape(ticker)}</b>",
            f"Address: <code>{html.escape(raw_address)}</code>",
            f"Status: {token.get('status') or 'unknown'}",
            f"First MC: {_format_mc(token.get('first_seen_mc'))}",
            f"Last MC: {_format_mc(token.get('last_mc'))}",
            f"Peak MC: {_format_mc(token.get('peak_mc'))}",
        ]
        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_restart(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Usage: <code>/str &lt;ca&gt; [tier]</code>", parse_mode="HTML")
            return
        raw_address = parts[1].strip()
        token = await token_model.get_by_address(raw_address)
        if not token:
            await message.answer(f"❌ Token not found", parse_mode="HTML")
            return
        token_id = token["id"]
        first_seen_at = token.get("first_seen_at") or datetime.now(timezone.utc)
        valid_tiers = {"tier_a", "tier_b", "tier_c", "tier_d", "tier_e", "tier_f", "a", "b", "c", "d", "e", "f"}
        tier = parts[2].strip().lower() if len(parts) >= 3 else None
        if tier:
            if tier not in valid_tiers:
                await message.answer("❌ Invalid tier. Use: a, b, c, d, e, f (or tier_a, tier_b, etc.)", parse_mode="HTML")
                return
            if len(tier) == 1:
                tier = f"tier_{tier}"
            poll_seconds = get_poll_interval_for_tier(tier)
            next_poll = datetime.now(timezone.utc) + timedelta(seconds=poll_seconds)
        else:
            tier, next_poll = calculate_next_poll_time(first_seen_at)
        await token_model.set_status(token_id, "active")
        await token_model.set_stop_reason(token_id, None)
        await token_model.update_tier(token_id, tier, next_poll)
        await message.answer(f"✅ Restarted {token.get('ticker') or raw_address[:8]}", parse_mode="HTML")

    async def cmd_stop(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer("Usage: <code>/stop &lt;ca&gt;</code>", parse_mode="HTML")
            return
        raw_address = parts[1].strip()
        token = await token_model.get_by_address(raw_address)
        if not token:
            await message.answer(f"❌ Token not found", parse_mode="HTML")
            return
        await token_model.set_status(token["id"], "stopped")
        await token_model.set_stop_reason(token["id"], "admin_manual_stop")
        await message.answer(f"✅ Stopped {token.get('ticker') or raw_address[:8]}", parse_mode="HTML")

    async def cmd_stop_ca(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) == 1:
            result = await db.execute(
                """
                UPDATE tokens_tracked
                SET status = 'stopped',
                    stop_reason = 'admin_ca_stop_all'
                WHERE status != 'stopped'
                """
            )
            count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
            await message.answer(f"⛔ Stopped monitoring all contracts ({count} updated).", parse_mode="HTML")
            return

        raw_arg = parts[1].strip()

        # If numeric, treat as chat ID to stop all contracts associated with that chat
        try:
            chat_id_arg = int(raw_arg)
            token_rows = await db.fetch(
                """
                SELECT DISTINCT token_id
                FROM token_group_alerts
                WHERE chat_id = $1
                """,
                chat_id_arg,
            )
            if not token_rows:
                await message.answer(f"❌ No contracts found for chat <code>{chat_id_arg}</code>.", parse_mode="HTML")
                return
            token_ids = [row["token_id"] for row in token_rows]
            await db.execute(
                """
                UPDATE tokens_tracked
                SET status = 'stopped',
                    stop_reason = 'admin_ca_stop_chat'
                WHERE id = ANY($1::BIGINT[])
                """,
                token_ids,
            )
            await message.answer(
                f"⛔ Stopped monitoring {len(token_ids)} contract(s) for chat <code>{chat_id_arg}</code>.",
                parse_mode="HTML",
            )
            return
        except ValueError:
            pass

        # Otherwise treat all remaining args as contract addresses
        addresses = parts[1:]
        stopped = 0
        not_found: list[str] = []
        invalid: list[str] = []

        for raw_address in addresses:
            address = raw_address.strip()
            chain = _detect_chain(address)
            if chain is None:
                invalid.append(address)
                continue

            token = await token_model.get_by_address(address)
            if not token:
                not_found.append(address)
                continue

            await token_model.set_status(token["id"], "stopped")
            await token_model.set_stop_reason(token["id"], "admin_ca_stop")
            stopped += 1

        lines = []
        if stopped:
            lines.append(f"✅ Stopped monitoring {stopped} contract(s).")
        if not_found:
            lines.append("❌ Not found: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in not_found))
        if invalid:
            lines.append("⚠️ Invalid address format: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in invalid))

        await message.answer("\n".join(lines), parse_mode="HTML")

    async def cmd_start_ca(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "✅ <b>Resume Token Monitoring</b>\n\n"
                "Usage:\n"
                "<code>/start_ca &lt;contract_address&gt; [tier]</code>\n\n"
                "Tier optional (a-f).",
                parse_mode="HTML",
            )
            return

        addresses = [parts[1].strip()]
        tier_arg = parts[2].strip().lower() if len(parts) >= 3 else None

        restarted = 0
        invalid = []
        not_found = []
        bad_tier = False

        valid_tiers = {"tier_a", "tier_b", "tier_c", "tier_d", "tier_e", "tier_f", "a", "b", "c", "d", "e", "f"}
        if tier_arg and tier_arg not in valid_tiers:
            bad_tier = True

        for raw_address in addresses:
            chain = _detect_chain(raw_address)
            if chain is None:
                invalid.append(raw_address)
                continue

            token = await token_model.get_by_address(raw_address)
            if not token:
                not_found.append(raw_address)
                continue

            token_id = token["id"]

            if bad_tier:
                continue

            if tier_arg:
                tier = f"tier_{tier_arg}" if len(tier_arg) == 1 else tier_arg
                poll_seconds = get_poll_interval_for_tier(tier)
                next_poll = datetime.now(timezone.utc) + timedelta(seconds=poll_seconds)
            else:
                first_seen_at = token.get("first_seen_at") or datetime.now(timezone.utc)
                tier, next_poll = calculate_next_poll_time(first_seen_at)

            await token_model.set_status(token_id, "active")
            await token_model.set_stop_reason(token_id, None)
            await token_model.update_tier(token_id, tier, next_poll)
            restarted += 1

        lines = []
        if restarted:
            lines.append(f"✅ Resumed monitoring {restarted} contract(s).")
        if bad_tier:
            lines.append("⚠️ Invalid tier. Use a-f (or tier_a..tier_f).")
        if not_found:
            lines.append("❌ Not found: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in not_found))
        if invalid:
            lines.append("⚠️ Invalid address format: " + ", ".join(f"<code>{html.escape(a)}</code>" for a in invalid))

        await message.answer("\n".join(lines), parse_mode="HTML")


    async def cmd_clean_contracts(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2 or parts[1].strip().lower() not in ("confirm", "yes"):
            await message.answer(
                "🧹 <b>Danger Zone</b>\n\n"
                "This will wipe every tracked contract address and related alerts.\n\n"
                "To confirm, run:\n"
                "<code>/clean_ca confirm</code>",
                parse_mode="HTML",
            )
            return

        await db.execute("DELETE FROM tokens_tracked")
        await message.answer("✅ All tracked contract addresses have been wiped.", parse_mode="HTML")

    async def cmd_trigger(message: types.Message) -> None:
        if message.from_user.id not in settings.admin_telegram_ids_list:
            return

        parts = (message.text or "").split()
        if len(parts) < 2:
            await message.answer(
                "🎯 <b>Trigger Gain Alert</b>\n\n"
                "Usage: <code>/tri &lt;ca&gt; [p] [c]</code>\n"
                "Flags: <code>p</code>=peak MC, <code>c</code>=chart",
                parse_mode="HTML",
            )
            return

        target_chat_id = None
        raw_address = None
        first_arg = parts[1].strip()
        try:
            potential_chat_id = int(first_arg)
            if len(parts) < 3:
                await message.answer("❌ Missing contract address after chat ID", parse_mode="HTML")
                return
            target_chat_id = potential_chat_id
            raw_address = parts[2].strip()
            flags = [p.lower() for p in parts[3:]]
        except ValueError:
            raw_address = first_arg
            flags = [p.lower() for p in parts[2:]]

        include_chart = "c" in flags
        use_peak_mc = "p" in flags or "peak" in flags

        chain = _detect_chain(raw_address)
        if chain is None:
            await message.answer("❌ Unrecognised address.")
            return

        token = await token_model.get_by_address(raw_address)
        if not token:
            await message.answer(f"❌ Token not found: <code>{html.escape(raw_address)}</code>", parse_mode="HTML")
            return

        ticker = token.get("ticker") or raw_address[:8]
        first_seen_mc = token.get("first_seen_mc") or Decimal(0)
        chosen_mc = token.get("peak_mc") if use_peak_mc else token.get("last_mc")
        chosen_mc = Decimal(str(chosen_mc or 0))

        if chosen_mc <= 0 or first_seen_mc <= 0:
            await message.answer(f"❌ Missing market cap data for <b>{html.escape(ticker)}</b>", parse_mode="HTML")
            return

        template_context = {
            "address": raw_address,
            "token_symbol": ticker,
            "elapsed_time": DexService._format_elapsed_time(token.get("first_seen_at")),
        }

        global_template = await settings_model.get_gain_alert_template_text()

        tracking_rows = await db.fetch(
            """
            SELECT
                tga.chat_id, tga.original_message_id, tga.original_user_id,
                tga.first_seen_mc AS group_first_seen_mc,
                ms.is_enabled, ms.sensitivity_pct, ms.assigned_userbot_id,
                ms.template_text, ms.use_management_bot, ms.chart_enabled,
                ms.chart_bot_id, ms.chart_mc_threshold,
                ARRAY_REMOVE(ARRAY_AGG(mst.target_chat_id), NULL) AS extra_targets
            FROM token_group_alerts tga
            LEFT JOIN monitored_sources ms ON ms.chat_id = tga.chat_id
               AND (ms.user_id = tga.original_user_id OR ms.user_id IS NULL)
            LEFT JOIN monitored_source_targets mst ON mst.source_id = ms.id
            WHERE tga.token_id = $1
            GROUP BY tga.chat_id, tga.original_message_id, tga.original_user_id,
                tga.first_seen_mc, ms.is_enabled, ms.sensitivity_pct,
                ms.assigned_userbot_id, ms.template_text, ms.use_management_bot,
                ms.chart_enabled, ms.chart_bot_id, ms.chart_mc_threshold
            """,
            token["id"],
        )

        if target_chat_id is not None:
            tracking_rows = [row for row in tracking_rows if row.get("chat_id") == target_chat_id]

        if not tracking_rows:
            await message.answer(f"❌ No tracked chats for <b>{html.escape(ticker)}</b>.", parse_mode="HTML")
            return

        # Fetch chart once before loop
        chart_bytes = None
        if include_chart:
            dex_svc = get_dex_service()
            if dex_svc.chart_fetcher:
                chart_config = await settings_model.get_global_chart_settings()
                chart_bot_id = chart_config.get("chart_bot_id")
                if chart_bot_id:
                    try:
                        logger.info("[TRIGGER] Fetching chart for %s...", raw_address[:8])
                        chart_bytes = await dex_svc.chart_fetcher.fetch_chart_for_token(
                            contract_address=raw_address,
                            chart_bot_id=int(chart_bot_id),
                        )
                        if chart_bytes:
                            logger.info("[TRIGGER] Chart fetched (%s bytes)", len(chart_bytes))
                    except Exception as exc:
                        logger.error("[TRIGGER] Chart fetch failed: %s", exc)

        status_msg = (
            f"🎯 Triggering for <b>{html.escape(ticker)}</b>\n"
            f"📍 Targets: {len(tracking_rows)}\n"
            f"💰 {'PEAK' if use_peak_mc else 'CURRENT'} MC: {DexService._format_mc_shorthand(chosen_mc)}\n"
            f"📊 Chart: {'✅ Fetched' if chart_bytes else ('⚠️ Failed' if include_chart else '❌ Disabled')}\n\n"
            "Sending..."
        )
        await message.answer(status_msg, parse_mode="HTML")

        success_count = 0
        failed_count = 0
        skipped_userbot = 0
        dex_svc = get_dex_service()
        workers_cache = {}

        for row in tracking_rows:
            chat_id = row.get("chat_id")
            if row.get("is_enabled") is False:
                continue

            use_mgmt = bool(row.get("use_management_bot")) if row.get("use_management_bot") is not None else False
            assigned_userbot_id = row.get("assigned_userbot_id")

            group_first_seen = row.get("group_first_seen_mc") or first_seen_mc
            try:
                group_first_seen = Decimal(str(group_first_seen))
            except (InvalidOperation, TypeError, ValueError):
                group_first_seen = first_seen_mc

            multiplier_value = float(chosen_mc / group_first_seen) if group_first_seen > 0 else 1.0
            template_values = dict(template_context)
            template_values.update({
                "multiplier": f"{multiplier_value:.1f}x",
                "first_market_cap": DexService._format_mc_shorthand(group_first_seen),
                "current_market_cap": DexService._format_mc_shorthand(chosen_mc),
                "gain_emoji": DexService._multiplier_to_emoji(multiplier_value),
            })

            template_override = row.get("template_text")
            if not template_override:
                try:
                    chat_records = await source_model.get_by_chat(chat_id)
                    template_override = next(
                        (r.get("template_text") for r in chat_records if r.get("template_text")), None
                    )
                except Exception:
                    template_override = None

            template_candidate = template_override or global_template or DEFAULT_GAIN_ALERT_TEMPLATE
            missing = missing_required_placeholders(template_candidate)
            if missing:
                template_candidate = global_template or DEFAULT_GAIN_ALERT_TEMPLATE

            try:
                alert_message = template_candidate.format(**template_values)
            except KeyError:
                failed_count += 1
                continue

            extra_targets = row.get("extra_targets") or []
            target_chats = {chat_id}
            target_chats.update(extra_targets)

            for target_chat in target_chats:
                try:
                    target_chat_int = int(target_chat)
                except (TypeError, ValueError):
                    failed_count += 1
                    continue

                reply_id = row.get("original_message_id") if target_chat_int == chat_id else None

                try:
                    result = None
                    if use_mgmt:
                        if dex_svc.management_bot:
                            result = await dex_svc.management_bot.send_message(
                                chat_id=target_chat_int,
                                message=alert_message,
                                reply_to_message_id=reply_id,
                                photo_bytes=chart_bytes,
                            )
                        else:
                            if chart_bytes:
                                input_file = BufferedInputFile(chart_bytes, filename="chart.jpg")
                                sent = await bot.send_photo(
                                    chat_id=target_chat_int,
                                    photo=input_file,
                                    caption=alert_message,
                                    reply_to_message_id=reply_id,
                                )
                            else:
                                sent = await bot.send_message(
                                    chat_id=target_chat_int,
                                    text=alert_message,
                                    reply_to_message_id=reply_id,
                                    disable_web_page_preview=True,
                                )
                            result = {"success": True, "message_id": sent.message_id}
                    else:
                        if not dex_svc.userbot_manager:
                            skipped_userbot += 1
                            continue
                        worker = None
                        if assigned_userbot_id:
                            worker = dex_svc.userbot_manager.get_all_workers().get(assigned_userbot_id)
                        if not worker:
                            workers = dex_svc.userbot_manager.get_all_workers()
                            if not workers:
                                skipped_userbot += 1
                                continue
                            worker = next(iter(workers.values()))
                        worker_id = getattr(worker, "userbot_id", None)
                        if worker_id is None:
                            skipped_userbot += 1
                            continue
                        executor = workers_cache.get(worker_id)
                        if executor is None:
                            executor = getattr(worker, "call_executor", None)
                            workers_cache[worker_id] = executor
                        if executor:
                            result = await executor.send_alert_message(
                                target_chat_id=target_chat_int,
                                message=alert_message,
                                reply_to_message_id=reply_id,
                                photo_bytes=chart_bytes,
                            )
                        else:
                            skipped_userbot += 1
                            continue

                    if result and result.get("success"):
                        success_count += 1
                        await db.execute(
                            "UPDATE token_group_alerts SET last_alert_mc=$1 WHERE token_id=$2 AND chat_id=$3",
                            chosen_mc, token["id"], chat_id,
                        )
                    else:
                        failed_count += 1
                except Exception as exc:
                    logger.error("[TRIGGER] Error sending to %s: %s", target_chat_int, exc)
                    failed_count += 1

        if success_count:
            await token_model.update_last_alert_mc(token["id"], chosen_mc)

        summary = f"✅ Sent: {success_count}\n❌ Failed: {failed_count}\n⏭ Skipped: {skipped_userbot}"
        await message.answer(summary, parse_mode="HTML")

    gain_alerts_handler = GainAlertsHandler(db)
    settings_handler = SettingsHandler(db, keyboards)
    userbots_handler = UserbotsHandler(db, keyboards)
    analytics_handler = AnalyticsCommandsHandler(db)
    info_handler = InfoHandler()
    cmd_fwd_handler = CommandForwardingHandler(db, keyboards)
    analytics_model = AnalyticsModel(db)
    dexscreener_api = get_dexscreener_client()
    invest_handler = InvestHandler(analytics_model, dexscreener_api, source_model)

    async def show_settings(query: types.CallbackQuery) -> None:
        await settings_handler.show_settings_menu(query)

    dp.callback_query.register(
        show_settings,
        F.data == "menu:settings",
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )

    for register_factory in get_router_factories(gain_alerts_handler, userbots_handler, settings_handler, cmd_fwd_handler):
        register_factory(dp)

    invest_router = get_invest_router(invest_handler, settings)
    dp.include_router(invest_router)

    dp.message.register(cmd_all_commands, Command(commands=["all", "commands", "help"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_inspect, Command(commands=["i"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_restart, Command(commands=["restart", "str"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_stop, Command(commands=["stop"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_stop_ca, Command(commands=["stop_ca"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_start_ca, Command(commands=["start_ca"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_clean_contracts, Command(commands=["clean_ca", "wipe_ca"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(cmd_trigger, Command(commands=["trigger", "tri"]), F.from_user.id.in_(settings.admin_telegram_ids_list))

    # Analytics commands
    dp.message.register(analytics_handler.cmd_stats, Command(commands=["stats"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(analytics_handler.cmd_top, Command(commands=["top", "leaderboard"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(analytics_handler.cmd_patterns, Command(commands=["patterns"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(analytics_handler.cmd_besthold, Command(commands=["besthold"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(info_handler.cmd_info, Command(commands=["info", "whois", "chatinfo"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.callback_query.register(
        analytics_handler.handle_timezone_selection,
        F.data.startswith("patterns:tz:"),
        F.from_user.id.in_(settings.admin_telegram_ids_list),
    )
    dp.message.register(settings_handler.cmd_timeframes, Command(commands=["timeframes"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(settings_handler.cmd_add_timeframe, Command(commands=["addtimeframe"]), F.from_user.id.in_(settings.admin_telegram_ids_list))
    dp.message.register(settings_handler.cmd_del_timeframe, Command(commands=["deltimeframe"]), F.from_user.id.in_(settings.admin_telegram_ids_list))

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands([
        BotCommand(command="i", description="Inspect token details"),
        BotCommand(command="tri", description="Force gain alert"),
        BotCommand(command="str", description="Restart stopped token"),
        BotCommand(command="stop", description="Stop tracking token"),
        BotCommand(command="stop_ca", description="Stop CA tracking"),
        BotCommand(command="start_ca", description="Resume CA tracking"),
        BotCommand(command="stats", description="Performance stats"),
        BotCommand(command="top", description="Leaderboard"),
        BotCommand(command="patterns", description="Time pattern analysis"),
        BotCommand(command="besthold", description="Best hold duration"),
        BotCommand(command="invest", description="Investment simulator"),
        BotCommand(command="info", description="DB info"),
        BotCommand(command="whois", description="DB info"),
        BotCommand(command="timeframes", description="Hold durations"),
        BotCommand(command="menu", description="Show main menu"),
        BotCommand(command="all", description="Show all commands"),
    ])
    logger.info("Admin bot polling started (integrated mode)")
    await dp.start_polling(bot, handle_signals=False)


def main() -> None:
    asyncio.run(run_admin_bot())


if __name__ == "__main__":
    main()
