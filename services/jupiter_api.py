"""
Jupiter API Service - Direct integration with Jupiter Token API v2
Provides market cap and token data for Solana tokens.
"""

import asyncio
import aiohttp
import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class JupiterAPIService:
    BASE_URL = "https://lite-api.jup.ag/tokens/v2"
    REQUEST_TIMEOUT = 10
    CACHE_TTL = 30

    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}

    async def start(self) -> None:
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"})
            logger.info("Jupiter API service started")

    async def stop(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("Jupiter API service stopped")

    async def get_token_data(self, token_address: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        if use_cache and token_address in self._cache:
            cache_age = datetime.utcnow() - self._cache_timestamps.get(token_address, datetime.min)
            if cache_age < timedelta(seconds=self.CACHE_TTL):
                logger.debug("[JUPITER] Cache hit for %s (age=%ss)", token_address[:8], cache_age.seconds)
                return self._cache[token_address]

        if not self.session:
            await self.start()

        url = f"{self.BASE_URL}/search?query={token_address}"

        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list) and data:
                        token_data = next((entry for entry in data if entry.get("id") == token_address), None)
                        if token_data:
                            self._cache[token_address] = token_data
                            self._cache_timestamps[token_address] = datetime.utcnow()
                            return token_data
                        logger.warning("[JUPITER] Token ID mismatch for %s", token_address)
                        return None
                    logger.warning("[JUPITER] No data returned for %s", token_address)
                    return None

                if response.status == 404:
                    logger.info("[JUPITER] Token %s not found (404)", token_address)
                    return None

                if response.status == 429:
                    logger.error("[JUPITER] Rate limited (429) for %s", token_address)
                    return None

                text = await response.text()
                logger.error("[JUPITER] Unexpected status %s for %s: %s", response.status, token_address, text[:200])
                return None
        except asyncio.TimeoutError:
            logger.error("[JUPITER] Timeout fetching %s", token_address)
        except aiohttp.ClientError as exc:
            logger.error("[JUPITER] Client error for %s: %s", token_address, exc)
        except Exception as exc:
            logger.error("[JUPITER] Unexpected error for %s: %s", token_address, exc, exc_info=True)

        return None

    def get_market_cap(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        mcap = token_data.get("mcap")
        if mcap is None or mcap <= 0:
            return None
        try:
            return Decimal(str(mcap))
        except Exception as exc:
            logger.error("[JUPITER] Error parsing mcap '%s': %s", mcap, exc)
            return None

    def get_price(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        price = token_data.get("usdPrice")
        if price is None or price <= 0:
            return None
        try:
            return Decimal(str(price))
        except Exception as exc:
            logger.error("[JUPITER] Error parsing price '%s': %s", price, exc)
            return None

    def get_liquidity(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        liquidity = token_data.get("liquidity")
        if liquidity is None or liquidity < 0:
            return None
        try:
            return Decimal(str(liquidity))
        except Exception as exc:
            logger.error("[JUPITER] Error parsing liquidity '%s': %s", liquidity, exc)
            return None

    def get_ticker(self, token_data: Optional[Dict[str, Any]]) -> Optional[str]:
        if not token_data:
            return None
        return token_data.get("symbol")


_jupiter_service_instance: Optional[JupiterAPIService] = None


def get_jupiter_service() -> JupiterAPIService:
    global _jupiter_service_instance
    if _jupiter_service_instance is None:
        _jupiter_service_instance = JupiterAPIService()
    return _jupiter_service_instance
