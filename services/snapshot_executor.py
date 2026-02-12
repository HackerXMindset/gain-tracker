from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from config import settings
from models.snapshot_tasks import SnapshotTasksModel
from models.analytics import AnalyticsModel
from models.token import TokenModel
from services import get_jupiter_service, get_dexpaprika_service, get_dexscreener_client

logger = logging.getLogger(__name__)


class SnapshotExecutor:
    """Performs a single snapshot task with API order and logging."""

    def __init__(self) -> None:
        self.snapshot_model = SnapshotTasksModel()
        self.analytics_model = AnalyticsModel()
        self.token_model = TokenModel()
        self.jupiter = get_jupiter_service()
        self.dexpaprika = get_dexpaprika_service()
        self.dex = get_dexscreener_client()
        self.tolerance_minutes = settings.snapshot_tolerance_minutes
        self.late_grace_minutes = settings.snapshot_late_grace_minutes

    async def execute(self, task_id: int) -> None:
        task = await self.snapshot_model.db.fetchrow("SELECT * FROM snapshot_tasks WHERE id = $1", task_id)
        if not task:
            return

        token_id = task["token_id"]
        target_time = task["target_time"]
        if target_time and target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)

        token = await self.token_model.get_by_id(token_id)
        if not token:
            await self.snapshot_model.mark_result(task_id, "failed", last_error_message="token_missing")
            return
        address = token["address"]

        late_deadline = target_time + timedelta(minutes=self.late_grace_minutes)
        if now > late_deadline:
            await self.snapshot_model.mark_result(task_id, "failed", last_error_message="missed_grace")
            return

        # API order: DexPaprika -> Jupiter -> DexScreener
        snapshot_errors = []
        source = None
        mc: Optional[Decimal] = None

        data = await self.dexpaprika.get_token_data(address, use_cache=False)
        mc = self.dexpaprika.get_market_cap(data)
        if mc:
            source = "dexpaprika"
        else:
            snapshot_errors.append(self.dexpaprika.get_last_error(address) or "dexpaprika:no_data")
            data = await self.jupiter.get_token_data(address, use_cache=False, token_id=token_id, phase="snapshot")
            mc = self.jupiter.get_market_cap(data) if data else None
            if mc:
                source = "jupiter"
            else:
                snapshot_errors.append(self.jupiter.get_last_error(address) or "jupiter:no_data")
                pair_data = await self.dex.fetch_token(address, chain_id="solana", use_cache=False)
                mc = self.dex.get_market_cap(pair_data)
                if mc:
                    source = "dexscreener"
                else:
                    snapshot_errors.append(self.dex.get_last_error(address) or "dexscreener:no_data")

        if mc:
            await self.analytics_model.record_mc_history(token_id, mc)
            await self.snapshot_model.mark_result(
                task_id,
                status="success" if now <= target_time + timedelta(minutes=self.tolerance_minutes) else "late",
                recorded_mc=float(mc),
                recorded_source=source,
                last_error_api=None,
                last_error_code=None,
                last_error_message=None,
            )
        else:
            err = ";".join(snapshot_errors) if snapshot_errors else "no_data"
            status_to_set = "due"
            if now >= late_deadline:
                status_to_set = "failed"
            await self.snapshot_model.mark_result(
                task_id,
                status=status_to_set,
                recorded_mc=None,
                recorded_source=None,
                last_error_api=None,
                last_error_code=None,
                last_error_message=err,
            )
