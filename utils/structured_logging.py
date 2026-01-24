from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event}
    payload.update(fields)
    logger.info(json.dumps(payload, sort_keys=True))
