from __future__ import annotations

import argparse
import asyncio
import json
import sys

from db import db
from health import run_health_checks
from main import run as run_service
from utils.logging_setup import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone gain alert service")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("run", help="Run the gain alert service")
    subparsers.add_parser("health", help="Run health checks and exit")
    return parser


async def _run_health() -> int:
    configure_logging()
    await db.connect()
    report = await run_health_checks()
    await db.disconnect()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("status") == "ok" else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "run"):
        asyncio.run(run_service())
        return

    if args.command == "health":
        exit_code = asyncio.run(_run_health())
        raise SystemExit(exit_code)

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
