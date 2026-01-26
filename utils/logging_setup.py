from __future__ import annotations

import logging
import os
import sys
from typing import Optional


def configure_logging(level: Optional[str] = None) -> None:
    env_level = os.getenv("LOG_LEVEL")
    log_level = level or env_level or "INFO"
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )
    _install_default_filters()


class _TelethonDebugFilter(logging.Filter):
    _NOISY_PREFIXES = (
        "telethon.network",
        "telethon.extensions",
        "telethon.client.updates",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.DEBUG and record.name.startswith(self._NOISY_PREFIXES):
            return False
        return True


def _install_default_filters() -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        return
    for handler in root_logger.handlers:
        handler.addFilter(_TelethonDebugFilter())
