from __future__ import annotations

from typing import Optional, Tuple
from decimal import Decimal

from services import get_dexpaprika_service, get_jupiter_service


class GainAlertAPI:
    """Encapsulates API order for alert pre-checks."""

    def __init__(self):
        self.dp = get_dexpaprika_service()
        self.jup = get_jupiter_service()

    async def fetch_alert_mc(self, address: str) -> Tuple[Optional[Decimal], Optional[str]]:
        # Order: DexPaprika -> Jupiter
        mc = None
        ticker = None

        data = await self.dp.get_token_data(address, use_cache=False)
        mc = self.dp.get_market_cap(data) if data else None
        ticker = self.dp.get_ticker(data) if data else None
        if mc:
            return mc, ticker

        data = await self.jup.get_token_data(address, use_cache=False)
        mc = self.jup.get_market_cap(data) if data else None
        ticker = self.jup.get_ticker(data) if data else None
        return mc, ticker

