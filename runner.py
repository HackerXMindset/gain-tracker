#!/usr/bin/env python3
"""
Standalone gain alert runner.
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from main import run
from admin_bot import run_admin_bot

logger = logging.getLogger(__name__)


async def run_with_signal_handling(coro) -> None:
    """Run a coroutine with proper signal handling for graceful shutdown."""
    task = asyncio.create_task(coro)
    shutdown_requested = False

    def _handle_signal(sig: int) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("Second signal received, forcing exit")
            os._exit(1)
        shutdown_requested = True
        logger.info("Received signal %s, shutting down (Ctrl+C again to force quit)", sig)
        task.cancel()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal, sig)

    try:
        await task
    except asyncio.CancelledError:
        logger.info("Task cancelled, exiting")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].lower() == "admin":
        # Launch the admin bot (Telegram UI)
        asyncio.run(run_with_signal_handling(run_admin_bot()))
        return

    # Default: start the gain-alert service (has its own signal handling)
    asyncio.run(run())


if __name__ == "__main__":
    main()
