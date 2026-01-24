from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

from alerts.management_bot import ManagementBot
from config import settings
from db import db
from scheduler import get_dex_service
from userbot import UserbotManager
from utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def run() -> None:
    configure_logging()
    logger.info("Starting standalone gain alert service")

    await db.connect()
    manager = UserbotManager()
    await manager.start_all_workers()

    dex_service = get_dex_service()
    dex_service.set_userbot_manager(manager)

    management_bot = None
    if settings.mgmt_bot_token:
        management_bot = ManagementBot(settings.mgmt_bot_token)
        dex_service.set_management_bot(management_bot)

    await dex_service.start()

    # Start admin bot in the same process (for /tri chart support)
    admin_bot_task = None
    if settings.mgmt_bot_token:
        from admin_bot import create_admin_dispatcher
        admin_bot_task = asyncio.create_task(
            create_admin_dispatcher(),
            name="admin_bot_polling",
        )
        logger.info("Admin bot polling started alongside scheduler")

    stop_event = asyncio.Event()

    def _handle_signal(sig: Optional[int]) -> None:
        logger.info("Received signal %s, shutting down", sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    await stop_event.wait()

    logger.info("Stopping standalone gain alert service")
    if admin_bot_task:
        admin_bot_task.cancel()
        try:
            await admin_bot_task
        except asyncio.CancelledError:
            pass
    await dex_service.stop()
    if management_bot:
        await management_bot.close()
    await manager.stop_all_workers()
    await db.disconnect()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
