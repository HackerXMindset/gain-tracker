from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from typing import Optional

from alerts.management_bot import ManagementBot
from config import settings
from db import db
from scheduler import get_dex_service, get_command_forwarding_service, SnapshotScheduler
from scheduler.stats_refresh import get_stats_refresh_service
from userbot import UserbotManager
from utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def run() -> None:
    configure_logging()
    logger.info("Starting standalone gain alert service")

    stop_event = asyncio.Event()
    shutdown_requested = False

    def _handle_signal(sig: Optional[int]) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("Second signal received, forcing exit")
            stop_event.set()
            return
        shutdown_requested = True
        logger.info("Received signal %s, shutting down", sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    manager: Optional[UserbotManager] = None
    dex_service = None
    stats_service = None
    cmd_fwd_service = None
    management_bot = None
    admin_bot_task: Optional[asyncio.Task] = None
    snapshot_scheduler: Optional[SnapshotScheduler] = None
    autotrader_service = None

    services_started = {
        "stats": False,
        "cmd_fwd": False,
        "dex": False,
        "snapshot": False,
        "autotrader": False,
    }

    try:
        await db.connect()

        manager = UserbotManager()
        await manager.start_all_workers()

        dex_service = get_dex_service()
        dex_service.set_userbot_manager(manager)

        if settings.mgmt_bot_token:
            management_bot = ManagementBot(settings.mgmt_bot_token)
            dex_service.set_management_bot(management_bot)

        stats_service = get_stats_refresh_service()
        await stats_service.start()
        services_started["stats"] = True

        cmd_fwd_service = get_command_forwarding_service()
        cmd_fwd_service.set_userbot_manager(manager)
        await cmd_fwd_service.start()
        services_started["cmd_fwd"] = True

        await dex_service.start()
        services_started["dex"] = True

        if settings.new_scheduler:
            snapshot_scheduler = SnapshotScheduler()
            await snapshot_scheduler.start()
            services_started["snapshot"] = True

        if settings.enable_autotrader:
            from services.autotrader_service import AutoTraderService
            autotrader_service = AutoTraderService()
            await autotrader_service.start()
            services_started["autotrader"] = True

        # Start admin bot in the same process (for /tri chart support)
        if settings.mgmt_bot_token:
            from admin_bot import create_admin_dispatcher
            admin_bot_task = asyncio.create_task(
                create_admin_dispatcher(),
                name="admin_bot_polling",
            )
            logger.info("Admin bot polling started alongside scheduler")

        await stop_event.wait()
    except asyncio.CancelledError:
        logger.info("Shutdown requested (cancelled)")
    finally:
        logger.info("Stopping standalone gain alert service")
        if admin_bot_task:
            admin_bot_task.cancel()
            with suppress(asyncio.CancelledError):
                await admin_bot_task
        if services_started.get("snapshot") and snapshot_scheduler:
            await snapshot_scheduler.stop()
        if services_started.get("autotrader") and autotrader_service:
            await autotrader_service.stop()
        if services_started["dex"] and dex_service:
            await dex_service.stop()
        if services_started["cmd_fwd"] and cmd_fwd_service:
            await cmd_fwd_service.stop()
        if services_started["stats"] and stats_service:
            await stats_service.stop()
        if management_bot:
            await management_bot.close()
        if manager:
            await manager.stop_all_workers()
        await db.disconnect()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
