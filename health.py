from __future__ import annotations

import logging
from typing import Any, Dict

from db import db

logger = logging.getLogger(__name__)


async def run_health_checks() -> Dict[str, Any]:
    report: Dict[str, Any] = {"status": "ok", "checks": {}}

    try:
        db_ok = await db.fetchval("SELECT 1")
        report["checks"]["db"] = {"status": "ok" if db_ok == 1 else "error"}
    except Exception as exc:
        report["checks"]["db"] = {"status": "error", "error": str(exc)}
        report["status"] = "error"

    try:
        row = await db.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM bots WHERE kind = 'userbot') AS userbots,
                (SELECT COUNT(*) FROM monitored_sources) AS monitored_sources,
                (SELECT COUNT(*) FROM tokens_tracked WHERE status = 'active') AS active_tokens
            """
        )
        if row:
            report["checks"]["counts"] = dict(row)
        else:
            report["checks"]["counts"] = {"status": "error", "error": "counts unavailable"}
            report["status"] = "error"
    except Exception as exc:
        report["checks"]["counts"] = {"status": "error", "error": str(exc)}
        report["status"] = "error"

    return report
