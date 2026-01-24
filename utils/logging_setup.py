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
