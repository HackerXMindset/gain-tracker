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

from config import settings

from db import db
from models.api_metrics import ApiMetricsModel
from models.token import TokenModel
from models.api_call_log import ApiCallLogModel

logger = logging.getLogger(__name__)


class JupiterAPIService:
    BASE_URL = "https://api.jup.ag/tokens/v2"
    REQUEST_TIMEOUT = 10
    CACHE_TTL = 30

    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._metrics = ApiMetricsModel(db)
        self._token_model = TokenModel(db)
        self._api_call_log = ApiCallLogModel(db)
        self._last_error: Dict[str, str] = {}
        self._api_keys = self._load_api_keys()
        self._key_index = 0

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

    def _load_api_keys(self) -> list[str]:
        if settings.jup_api_keys_list:
            return settings.jup_api_keys_list
        if settings.jup_api_key:
            return [settings.jup_api_key]
        return []

    async def start(self) -> None:
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            headers = {"Accept": "application/json"}
            if not self._api_keys:
                logger.warning("[JUPITER] Missing JUP_API_KEY(S); requests may fail after Jan 31, 2026")
            self.session = aiohttp.ClientSession(timeout=timeout, headers=headers)
            logger.info("Jupiter API service started")

    async def stop(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("Jupiter API service stopped")

    async def get_token_data(
        self,
        token_address: str,
        use_cache: bool = True,
        token_id: Optional[int] = None,
        phase: str = "poll",
    ) -> Optional[Dict[str, Any]]:
        if use_cache and token_address in self._cache:
            cache_age = datetime.utcnow() - self._cache_timestamps.get(token_address, datetime.min)
            if cache_age < timedelta(seconds=self.CACHE_TTL):
                logger.debug("[JUPITER] Cache hit for %s (age=%ss)", token_address[:8], cache_age.seconds)
                return self._cache[token_address]

        if not self.session:
            await self.start()

        url = f"{self.BASE_URL}/search?query={token_address}"
        result: Optional[Dict[str, Any]] = None
        keys = self._api_keys or [None]
        if self._api_keys:
            start_index = self._key_index % len(keys)
            self._key_index = (self._key_index + 1) % len(keys)
        else:
            start_index = 0

        for offset in range(len(keys)):
            key = keys[(start_index + offset) % len(keys)]
            headers = {"x-api-key": key} if key else None
            try:
                start_ts = datetime.utcnow()
                async with self.session.get(url, headers=headers) as response:
                    latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)

                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, list) and data:
                            token_data = next((entry for entry in data if entry.get("id") == token_address), None)
                            if token_data:
                                self._cache[token_address] = token_data
                                self._cache_timestamps[token_address] = datetime.utcnow()
                                result = token_data
                                await self._metrics.record_check("jupiter", True)
                                await self._api_call_log.record("jupiter", phase, 200, None, latency, token_id)
                                await self._token_model.update_last_api_error(token_address, None, None, None)
                                return result
                            # data returned but no matching id
                            logger.warning("[JUPITER] Token ID mismatch for %s", token_address)
                            self._set_last_error(token_address, 200, "id_mismatch")
                            await self._token_model.update_last_api_error(token_address, "jupiter", 200, "id_mismatch")
                            await self._api_call_log.record("jupiter", phase, 200, "id_mismatch", latency, token_id)
                            await self._metrics.record_check("jupiter", False)
                            return None

                        logger.warning("[JUPITER] No data returned for %s", token_address)
                        self._set_last_error(token_address, 200, "empty")
                        await self._token_model.update_last_api_error(token_address, "jupiter", 200, "empty")
                        await self._api_call_log.record("jupiter", phase, 200, "empty", latency, token_id)
                        await self._metrics.record_check("jupiter", False)
                        return None

                    if response.status == 404:
                        logger.info("[JUPITER] Token %s not found (404)", token_address)
                        self._set_last_error(token_address, 404, "not_found")
                        await self._token_model.update_last_api_error(token_address, "jupiter", 404, "not_found")
                        await self._api_call_log.record("jupiter", phase, 404, "not_found", latency, token_id)
                        await self._metrics.record_check("jupiter", False)
                        return None

                    if response.status in {401, 429}:
                        logger.warning(
                            "[JUPITER] Key failed (%s) for %s, trying next key",
                            response.status,
                            token_address,
                        )
                        self._set_last_error(token_address, response.status, "auth_or_rate_limit")
                        await self._token_model.update_last_api_error(
                            token_address, "jupiter", response.status, "auth_or_rate_limit"
                        )
                        await self._api_call_log.record("jupiter", phase, response.status, "auth_or_rate_limit", latency, token_id)
                        await self._metrics.record_check("jupiter", False)
                        continue

                    text = await response.text()
                    logger.error("[JUPITER] Unexpected status %s for %s: %s", response.status, token_address, text[:200])
                    self._set_last_error(token_address, response.status, "unexpected_status")
                    await self._token_model.update_last_api_error(
                        token_address, "jupiter", response.status, "unexpected_status"
                    )
                    await self._api_call_log.record("jupiter", phase, response.status, "unexpected_status", latency, token_id)
                    await self._metrics.record_check("jupiter", False)
                    return None
            except asyncio.TimeoutError:
                logger.error("[JUPITER] Timeout fetching %s", token_address)
                self._set_last_error(token_address, None, "timeout")
                await self._token_model.update_last_api_error(token_address, "jupiter", None, "timeout")
                await self._api_call_log.record("jupiter", phase, None, "timeout", None, token_id)
                await self._metrics.record_check("jupiter", False)
            except aiohttp.ClientError as exc:
                logger.error("[JUPITER] Client error for %s: %s", token_address, exc)
                self._set_last_error(token_address, None, f"client_error:{exc.__class__.__name__}")
                await self._token_model.update_last_api_error(
                    token_address, "jupiter", None, f"client_error:{exc.__class__.__name__}"
                )
                await self._api_call_log.record("jupiter", phase, None, f"client_error:{exc.__class__.__name__}", None, token_id)
                await self._metrics.record_check("jupiter", False)
            except Exception as exc:
                logger.error("[JUPITER] Unexpected error for %s: %s", token_address, exc, exc_info=True)
                self._set_last_error(token_address, None, f"exception:{exc.__class__.__name__}")
                await self._token_model.update_last_api_error(
                    token_address, "jupiter", None, f"exception:{exc.__class__.__name__}"
                )
                await self._api_call_log.record("jupiter", phase, None, f"exception:{exc.__class__.__name__}", None, token_id)
                await self._metrics.record_check("jupiter", False)

        return result

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
