"""
DexPaprika API Service - Fetches token data from DexPaprika.
Provides market cap (fdv), price, liquidity, and symbol/name.
"""

import asyncio
import aiohttp
import logging
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import datetime, timedelta

from db import db
from models.api_metrics import ApiMetricsModel
from models.token import TokenModel
from models.api_call_log import ApiCallLogModel

logger = logging.getLogger(__name__)


class DexPaprikaAPIService:
    BASE_URL = "https://api.dexpaprika.com/networks"
    REQUEST_TIMEOUT = 10
    CACHE_TTL = 20

    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._metrics = ApiMetricsModel(db)
        self._token_model = TokenModel(db)
        self._api_call_log = ApiCallLogModel(db)
        self._last_error: Dict[str, str] = {}

    def _set_last_error(
        self,
        token_address: str,
        status_code: Optional[int],
        message: str,
    ) -> None:
        token_address = token_address.strip()
        if not token_address:
            return
        self._last_error[token_address] = f"{status_code}:{message}" if status_code else message

    def get_last_error(self, token_address: str) -> Optional[str]:
        return self._last_error.get(token_address.strip())

    async def start(self) -> None:
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"})
            logger.info("DexPaprika API service started")

    async def stop(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("DexPaprika API service stopped")

    async def get_token_data(
        self,
        token_address: str,
        network: str = "solana",
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        token_address = token_address.strip()
        cache_key = f"{network}:{token_address}"

        if use_cache and cache_key in self._cache:
            cache_age = datetime.utcnow() - self._cache_timestamps.get(cache_key, datetime.min)
            if cache_age < timedelta(seconds=self.CACHE_TTL):
                logger.debug("[DEXPAPRIKA] Cache hit for %s (age=%ss)", token_address[:8], cache_age.seconds)
                return self._cache[cache_key]

        if not self.session:
            await self.start()

        url = f"{self.BASE_URL}/{network}/tokens/{token_address}"
        result: Optional[Dict[str, Any]] = None
        start_ts = None

        try:
            async with self.session.get(url) as response:
                start_ts = datetime.utcnow()
                if response.status == 200:
                    data = await response.json()
                    latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
                    if isinstance(data, dict) and data:
                        self._cache[cache_key] = data
                        self._cache_timestamps[cache_key] = datetime.utcnow()
                        result = data
                        await self._api_call_log.record("dexpaprika", "poll", response.status, None, latency)
                        await self._token_model.update_last_api_error(token_address, None, None, None)
                        return result
                    logger.warning("[DEXPAPRIKA] Empty data for %s", token_address)
                    self._set_last_error(token_address, 200, "empty")
                    await self._token_model.update_last_api_error(token_address, "dexpaprika", 200, "empty")
                    await self._api_call_log.record("dexpaprika", "poll", 200, "empty", latency)
                    result = None
                    return result

                if response.status == 404:
                    logger.info("[DEXPAPRIKA] Token %s not found (404)", token_address)
                    self._set_last_error(token_address, 404, "not_found")
                    await self._token_model.update_last_api_error(token_address, "dexpaprika", 404, "not_found")
                    latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000) if start_ts else None
                    await self._api_call_log.record("dexpaprika", "poll", 404, "not_found", latency)
                    result = None
                    return result

                if response.status == 429:
                    logger.error("[DEXPAPRIKA] Rate limited (429) for %s", token_address)
                    self._set_last_error(token_address, 429, "rate_limited")
                    await self._token_model.update_last_api_error(token_address, "dexpaprika", 429, "rate_limited")
                    latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000) if start_ts else None
                    await self._api_call_log.record("dexpaprika", "poll", 429, "rate_limited", latency)
                    result = None
                    return result

                text = await response.text()
                logger.error("[DEXPAPRIKA] Unexpected status %s for %s: %s", response.status, token_address, text[:200])
                self._set_last_error(token_address, response.status, "unexpected_status")
                await self._token_model.update_last_api_error(
                    token_address, "dexpaprika", response.status, "unexpected_status"
                )
                latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000) if start_ts else None
                await self._api_call_log.record("dexpaprika", "poll", response.status, "unexpected_status", latency)
                result = None
                return result
        except asyncio.TimeoutError:
            logger.error("[DEXPAPRIKA] Timeout fetching %s", token_address)
            self._set_last_error(token_address, None, "timeout")
            await self._token_model.update_last_api_error(token_address, "dexpaprika", None, "timeout")
            await self._api_call_log.record("dexpaprika", "poll", None, "timeout", None)
        except aiohttp.ClientError as exc:
            logger.error("[DEXPAPRIKA] Client error for %s: %s", token_address, exc)
            self._set_last_error(token_address, None, f"client_error:{exc.__class__.__name__}")
            await self._token_model.update_last_api_error(
                token_address, "dexpaprika", None, f"client_error:{exc.__class__.__name__}"
            )
            await self._api_call_log.record("dexpaprika", "poll", None, f"client_error:{exc.__class__.__name__}", None)
        except Exception as exc:
            logger.error("[DEXPAPRIKA] Unexpected error for %s: %s", token_address, exc, exc_info=True)
            self._set_last_error(token_address, None, f"exception:{exc.__class__.__name__}")
            await self._token_model.update_last_api_error(
                token_address, "dexpaprika", None, f"exception:{exc.__class__.__name__}"
            )
            await self._api_call_log.record("dexpaprika", "poll", None, f"exception:{exc.__class__.__name__}", None)
        finally:
            await self._metrics.record_check("dexpaprika", result is not None)

        return result

    def get_market_cap(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        summary = token_data.get("summary") or {}
        fdv = summary.get("fdv")
        if fdv is None or fdv <= 0:
            return None
        try:
            return Decimal(str(fdv))
        except Exception as exc:
            logger.error("[DEXPAPRIKA] Error parsing fdv '%s': %s", fdv, exc)
            return None

    def get_price(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        summary = token_data.get("summary") or {}
        price = summary.get("price_usd")
        if price is None or price <= 0:
            return None
        try:
            return Decimal(str(price))
        except Exception as exc:
            logger.error("[DEXPAPRIKA] Error parsing price '%s': %s", price, exc)
            return None

    def get_liquidity(self, token_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not token_data:
            return None
        summary = token_data.get("summary") or {}
        liquidity = summary.get("liquidity_usd")
        if liquidity is None or liquidity < 0:
            return None
        try:
            return Decimal(str(liquidity))
        except Exception as exc:
            logger.error("[DEXPAPRIKA] Error parsing liquidity '%s': %s", liquidity, exc)
            return None

    def get_ticker(self, token_data: Optional[Dict[str, Any]]) -> Optional[str]:
        if not token_data:
            return None
        return token_data.get("symbol")


_dexpaprika_service_instance: Optional[DexPaprikaAPIService] = None


def get_dexpaprika_service() -> DexPaprikaAPIService:
    global _dexpaprika_service_instance
    if _dexpaprika_service_instance is None:
        _dexpaprika_service_instance = DexPaprikaAPIService()
    return _dexpaprika_service_instance
