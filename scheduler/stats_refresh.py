from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from models import AnalyticsModel, MonitoredSourceModel
from db import db

logger = logging.getLogger(__name__)


class StatsRefreshService:
    """Background service to refresh cached source statistics."""

    def __init__(self) -> None:
        self.analytics_model = AnalyticsModel()
        self.source_model = MonitoredSourceModel(db)
        self.running = False
        self._refresh_task = None

    async def start(self) -> None:
        """Start the stats refresh service."""
        if self.running:
            return

        self.running = True
        self._refresh_task = asyncio.create_task(self._run_refresh_loop())
        logger.info("[STATS_REFRESH] Service started")

    async def stop(self) -> None:
        """Stop the stats refresh service."""
        self.running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        logger.info("[STATS_REFRESH] Service stopped")

    async def _run_refresh_loop(self) -> None:
        """Main refresh loop - runs every hour."""
        while self.running:
            try:
                await self._refresh_all_sources()
                # Wait 1 hour between refreshes
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[STATS_REFRESH] Error in refresh loop: %s", exc, exc_info=True)
                # Wait 5 minutes before retrying on error
                await asyncio.sleep(300)

    async def _refresh_all_sources(self) -> None:
        """Refresh stats for all enabled sources."""
        try:
            # Get all enabled monitored sources
            sources = await self.source_model.get_all()

            if not sources:
                logger.debug("[STATS_REFRESH] No sources to refresh")
                return

            logger.info("[STATS_REFRESH] Refreshing stats for %d sources", len(sources))

            # Refresh stats for each source
            for source in sources:
                source_id = source["id"]
                source_chat_id = source["chat_id"]
                display_name = source.get("display_name", f"Source {source_id}")

                try:
                    # Refresh 24h stats (every hour)
                    await self.analytics_model.refresh_stats_cache(
                        source_id, source_chat_id, "24h"
                    )

                    # Refresh 7d stats (every hour is fine)
                    await self.analytics_model.refresh_stats_cache(
                        source_id, source_chat_id, "7d"
                    )

                    # Refresh 30d stats (every hour is fine)
                    await self.analytics_model.refresh_stats_cache(
                        source_id, source_chat_id, "30d"
                    )

                    logger.debug(
                        "[STATS_REFRESH] Refreshed stats for source %s (%s)",
                        source_id,
                        display_name,
                    )

                except Exception as exc:
                    logger.error(
                        "[STATS_REFRESH] Error refreshing source %s: %s",
                        source_id,
                        exc,
                        exc_info=True,
                    )

            logger.info("[STATS_REFRESH] Completed refresh for %d sources", len(sources))

        except Exception as exc:
            logger.error("[STATS_REFRESH] Error getting sources: %s", exc, exc_info=True)

    async def refresh_source_now(self, source_id: int, source_chat_id: int) -> None:
        """Manually trigger refresh for a specific source."""
        try:
            await self.analytics_model.refresh_stats_cache(source_id, source_chat_id, "24h")
            await self.analytics_model.refresh_stats_cache(source_id, source_chat_id, "7d")
            await self.analytics_model.refresh_stats_cache(source_id, source_chat_id, "30d")
            logger.info("[STATS_REFRESH] Manual refresh completed for source %s", source_id)
        except Exception as exc:
            logger.error(
                "[STATS_REFRESH] Error in manual refresh for source %s: %s",
                source_id,
                exc,
                exc_info=True,
            )


# Global instance
_stats_refresh_service = None


def get_stats_refresh_service() -> StatsRefreshService:
    """Get the global stats refresh service instance."""
    global _stats_refresh_service
    if _stats_refresh_service is None:
        _stats_refresh_service = StatsRefreshService()
    return _stats_refresh_service
