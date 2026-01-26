"""
OKX Market API Service - Fetches token data from OKX Web3 market endpoint.
Provides market cap, price, liquidity, and ticker data (Solana only).
"""

import asyncio
import aiohttp
import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class OKXMarketAPIService:
    BASE_URL = "https://web3.okx.com/priapi/v1/dx/market/v2/latest/info"
    REQUEST_TIMEOUT = 10
    CACHE_TTL = 20

    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}

    async def start(self) -> None:
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"})
            logger.info("OKX Market API service started")

    async def stop(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("OKX Market API service stopped")

    async def get_token_data(
        self,
        token_address: str,
        chain_id: str = "501",
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        token_address = token_address.strip()
        cache_key = f"{chain_id}:{token_address}"

        if use_cache and cache_key in self._cache:
            cache_age = datetime.utcnow() - self._cache_timestamps.get(cache_key, datetime.min)
            if cache_age < timedelta(seconds=self.CACHE_TTL):
                logger.debug("[OKX] Cache hit for %s (age=%ss)", token_address[:8], cache_age.seconds)
                return self._cache[cache_key]

        if not self.session:
            await self.start()

        url = f"{self.BASE_URL}?tokenContractAddress={token_address}&chainId={chain_id}"

        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict) and data.get("code") == 0:
                        payload = data.get("data") or {}
                        if payload:
                            self._cache[cache_key] = payload
                            self._cache_timestamps[cache_key] = datetime.utcnow()
                            return payload
                        logger.warning("[OKX] Empty data for %s", token_address)
                        return None

                    logger.warning("[OKX] Unexpected response body for %s", token_address)
                    return None

                if response.status == 404:
                    logger.info("[OKX] Token %s not found (404)", token_address)
                    return None

                if response.status == 429:
                    logger.error("[OKX] Rate limited (429) for %s", token_address)
                    return None

                text = await response.text()
                logger.error("[OKX] Unexpected status %s for %s: %s", response.status, token_address, text[:200])
                return None
        except asyncio.TimeoutError:
            logger.error("[OKX] Timeout fetching %s", token_address)
        except aiohttp.ClientError as exc:
            logger.error("[OKX] Client error for %s: %s", token_address, exc)
        except Exception as exc:
            logger.error("[OKX] Unexpected error for %s: %s", token_address, exc, exc_info=True)

        return None

    def get_market_cap(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        mcap = token_data.get("marketCap") or token_data.get("market_cap")
        if mcap is None or mcap <= 0:
            return None
        try:
            return Decimal(str(mcap))
        except Exception as exc:
            logger.error("[OKX] Error parsing market cap '%s': %s", mcap, exc)
            return None

    def get_price(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        price = token_data.get("price")
        if price is None or price <= 0:
            return None
        try:
            return Decimal(str(price))
        except Exception as exc:
            logger.error("[OKX] Error parsing price '%s': %s", price, exc)
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
            logger.error("[OKX] Error parsing liquidity '%s': %s", liquidity, exc)
            return None

    def get_ticker(self, token_data: Optional[Dict[str, Any]]) -> Optional[str]:
        if not token_data:
            return None
        return token_data.get("tokenSymbol")


_okx_service_instance: Optional[OKXMarketAPIService] = None


def get_okx_service() -> OKXMarketAPIService:
    global _okx_service_instance
    if _okx_service_instance is None:
        _okx_service_instance = OKXMarketAPIService()
    return _okx_service_instance

