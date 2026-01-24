from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List, Optional

import asyncpg
from asyncpg import Pool

from config import settings

logger = logging.getLogger(__name__)


class Database:
    def __init__(self) -> None:
        self.pool: Optional[Pool] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if self.pool is not None:
                return

            base_min = max(1, settings.db_pool_min)
            base_max = max(base_min, settings.db_pool_max)

            fallback_sizes = []
            for candidate in (base_max, 8, 6, 4, 3, 2, 1):
                if candidate >= 1 and candidate not in fallback_sizes:
                    fallback_sizes.append(candidate)

            last_exc: Optional[Exception] = None
            for max_size in fallback_sizes:
                min_size = min(base_min, max_size)
                try:
                    self.pool = await asyncpg.create_pool(
                        settings.db_url,
                        min_size=min_size,
                        max_size=max_size,
                        command_timeout=60,
                    )
                except (asyncio.TimeoutError, asyncpg.PostgresError) as exc:
                    message = str(exc)
                    if isinstance(exc, asyncio.TimeoutError) or "MaxClientsInSessionMode" in message:
                        logger.warning(
                            "Database pool creation failed for max_size=%s (min_size=%s): %s",
                            max_size,
                            min_size,
                            message,
                        )
                        last_exc = exc
                        continue
                    raise
                except Exception:
                    raise
                else:
                    if max_size != base_max:
                        logger.warning(
                            "Database pool max_size reduced from %s to %s due to connection limits",
                            base_max,
                            max_size,
                        )
                    logger.info("Database pool created (min_size=%s, max_size=%s)", min_size, max_size)
                    await self.run_migrations()
                    return

            if last_exc:
                raise last_exc
            raise RuntimeError("Failed to create database pool for unknown reasons")

    async def disconnect(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None
            logger.info("Database pool closed")

    @asynccontextmanager
    async def acquire(self):
        if not self.pool:
            await self.connect()

        try:
            async with self.pool.acquire() as conn:
                yield conn
        except asyncpg.exceptions.InterfaceError as exc:
            if "pool is closing" in str(exc):
                logger.warning("Database pool is closing, skipping operation")
                yield None
            else:
                raise

    async def execute(self, query: str, *args) -> str:
        async with self.acquire() as conn:
            if conn is None:
                logger.debug("Skipping execute during shutdown")
                return "SKIPPED"
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> List[asyncpg.Record]:
        async with self.acquire() as conn:
            if conn is None:
                logger.debug("Skipping fetch during shutdown")
                return []
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> Optional[asyncpg.Record]:
        async with self.acquire() as conn:
            if conn is None:
                logger.debug("Skipping fetchrow during shutdown")
                return None
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args) -> Any:
        async with self.acquire() as conn:
            if conn is None:
                logger.debug("Skipping fetchval during shutdown")
                return None
            return await conn.fetchval(query, *args)

    async def run_migrations(self) -> None:
        migrations_dir = Path(__file__).resolve().parents[1] / "migrations"
        if not migrations_dir.exists():
            logger.warning("Migrations directory missing: %s", migrations_dir)
            return

        migration_files = sorted(migrations_dir.glob("*.sql"))
        if not migration_files:
            logger.info("No migrations found in %s", migrations_dir)
            return

        async with self.acquire() as conn:
            if conn is None:
                logger.debug("Skipping migrations during shutdown")
                return

            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'migrations'
                )
                """
            )

            if not exists:
                await conn.execute(
                    """
                    CREATE TABLE migrations (
                        id SERIAL PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL,
                        applied_at TIMESTAMPTZ DEFAULT NOW()
                    )
                    """
                )
                logger.info("Created migrations table.")

            for migration_file in migration_files:
                migration_name = migration_file.stem
                applied = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM migrations WHERE name = $1)",
                    migration_name,
                )

                if applied:
                    logger.debug("Migration %s already applied.", migration_name)
                    continue

                logger.info("Running migration: %s", migration_name)
                await conn.execute(migration_file.read_text())
                await conn.execute(
                    "INSERT INTO migrations (name) VALUES ($1)",
                    migration_name,
                )
                logger.info("Migration %s completed", migration_name)


db = Database()
