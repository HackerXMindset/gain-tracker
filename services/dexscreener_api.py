"""
DexScreener API Client - Fetches token data from DexScreener REST API.
Provides market cap, price, liquidity data for ongoing monitoring.
"""

import asyncio
import aiohttp
import logging
import time
from collections import deque
from typing import Dict, Any, Optional, Deque, List
from decimal import Decimal
from datetime import datetime, timedelta

from db import db
from models.api_metrics import ApiMetricsModel
from models.token import TokenModel
from models.api_call_log import ApiCallLogModel

logger = logging.getLogger(__name__)


class DexScreenerAPIClient:
    TOKENS_URL = "https://api.dexscreener.com/tokens/v1"
    TOKEN_PAIRS_URL = "https://api.dexscreener.com/token-pairs/v1"
    LATEST_TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens"
    REQUEST_TIMEOUT = 10
    CACHE_TTL = 60
    MAX_RETRIES = 3
    BACKOFF_BASE = 2
    MAX_REQUESTS_PER_SECOND = 4

    def __init__(self) -> None:
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Optional[List[Dict[str, Any]]]] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._rate_limit_lock = asyncio.Lock()
        self._request_times: Deque[float] = deque()
        self._metrics = ApiMetricsModel(db)
        self._token_model = TokenModel(db)
        self._api_call_log = ApiCallLogModel(db)
        self._last_error: Dict[str, str] = {}

    def _set_last_error(
        self,
        address: str,
        status_code: Optional[int],
        message: str,
    ) -> None:
        address = address.strip()
        if not address:
            return
        self._last_error[address] = f"{status_code}:{message}" if status_code else message

    def get_last_error(self, address: str) -> Optional[str]:
        return self._last_error.get(address.strip())

    async def start(self) -> None:
        if not self.session:
            timeout = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
            self.session = aiohttp.ClientSession(timeout=timeout, headers={"Accept": "application/json"})
            logger.info("DexScreener API client started")

    async def stop(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("DexScreener API client stopped")

    async def _apply_rate_limit(self) -> None:
        async with self._rate_limit_lock:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] >= 1:
                self._request_times.popleft()

            if len(self._request_times) >= self.MAX_REQUESTS_PER_SECOND:
                sleep_for = 1 - (now - self._request_times[0])
                sleep_for = max(sleep_for, 0)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                now = time.monotonic()
                while self._request_times and now - self._request_times[0] >= 1:
                    self._request_times.popleft()

            self._request_times.append(now)

    async def fetch_token(
        self,
        address: str,
        chain_id: str = "solana",
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        pairs = await self.fetch_token_pairs(address, chain_id=chain_id, use_cache=use_cache)
        if not pairs:
            return None
        best_pair = self._select_preferred_pair(pairs)

        fdv_val = self._safe_float(best_pair.get("fdv") or best_pair.get("marketCap"))
        price_val = self._safe_float(best_pair.get("priceUsd"))
        logger.debug(
            "[DEXSCREENER] %s:%s MC: $%s Price: $%s",
            chain_id,
            address.strip()[:8],
            f"{fdv_val:,.2f}",
            f"{price_val:.8f}",
        )
        return best_pair

    async def fetch_token_pairs(
        self,
        address: str,
        chain_id: str = "solana",
        use_cache: bool = True,
    ) -> Optional[List[Dict[str, Any]]]:
        address = address.strip()
        normalized_chain = (chain_id or "solana").lower()
        cache_key = f"{normalized_chain}:{address}"

        if use_cache and cache_key in self._cache:
            cache_age = datetime.utcnow() - self._cache_timestamps.get(cache_key, datetime.min)
            if cache_age < timedelta(seconds=self.CACHE_TTL):
                logger.debug(
                    "[DEXSCREENER] Cache hit for %s:%s (age=%ss)",
                    chain_id,
                    address[:8],
                    cache_age.seconds,
                )
                return self._cache[cache_key]

        if not self.session:
            await self.start()

        result: Optional[List[Dict[str, Any]]] = None

        endpoints = [
            ("tokens_v1", f"{self.TOKENS_URL}/{normalized_chain}/{address}"),
            ("token_pairs_v1", f"{self.TOKEN_PAIRS_URL}/{normalized_chain}/{address}"),
            ("latest_tokens", f"{self.LATEST_TOKENS_URL}/{address}"),
        ]

        combined_empty_payloads: Dict[str, Any] = {}
        last_status: Optional[int] = None
        last_message: Optional[str] = None

        try:
            for attempt in range(self.MAX_RETRIES):
                retry_due_to_backoff = False
                empty_payloads = {}

                try:
                    for endpoint_name, url in endpoints:
                        await self._apply_rate_limit()
                        logger.debug(
                            "[DEXSCREENER] Fetching %s:%s via %s (attempt %s/%s)",
                            chain_id,
                            address[:8],
                            endpoint_name,
                            attempt + 1,
                            self.MAX_RETRIES,
                        )

                        async with self.session.get(url) as response:
                            start_ts = datetime.utcnow()
                            if response.status == 200:
                                data = await response.json()
                                pairs = self._extract_pairs(data)

                                if pairs:
                                    self._cache[cache_key] = pairs
                                    self._cache_timestamps[cache_key] = datetime.utcnow()
                                    result = pairs
                                    latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
                                    await self._api_call_log.record("dexscreener", "poll", response.status, None, latency)
                                    await self._token_model.update_last_api_error(address, None, None, None)
                                    return result

                                empty_payloads[endpoint_name] = data
                                combined_empty_payloads[endpoint_name] = data
                                latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
                                await self._api_call_log.record("dexscreener", "poll", response.status, "empty", latency)
                                continue

                            if response.status == 404:
                                empty_payloads[endpoint_name] = {"status": 404}
                                combined_empty_payloads[endpoint_name] = {"status": 404}
                                last_status = 404
                                last_message = "not_found"
                                latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
                                await self._api_call_log.record("dexscreener", "poll", 404, "not_found", latency)
                                continue

                            if response.status == 429:
                                backoff_time = self.BACKOFF_BASE ** (attempt + 1)
                                logger.warning(
                                    "[DEXSCREENER] Rate limited for %s:%s via %s, backoff %ss",
                                    chain_id,
                                    address[:8],
                                    endpoint_name,
                                    backoff_time,
                                )
                                last_status = 429
                                last_message = "rate_limited"
                                latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
                                await self._api_call_log.record("dexscreener", "poll", 429, "rate_limited", latency)
                                if attempt < self.MAX_RETRIES - 1:
                                    await asyncio.sleep(backoff_time)
                                    retry_due_to_backoff = True
                                    break
                                logger.error("[DEXSCREENER] Max retries exceeded for %s:%s", chain_id, address[:8])
                                result = None
                                return result

                            text = await response.text()
                            logger.error(
                                "[DEXSCREENER] Unexpected status %s for %s:%s via %s: %s",
                                response.status,
                                chain_id,
                                address[:8],
                                endpoint_name,
                                text[:200],
                            )
                            last_status = response.status
                            last_message = "unexpected_status"
                            latency = int((datetime.utcnow() - start_ts).total_seconds() * 1000)
                            await self._api_call_log.record("dexscreener", "poll", response.status, "unexpected_status", latency)

                            if 500 <= response.status < 600 and attempt < self.MAX_RETRIES - 1:
                                backoff_time = self.BACKOFF_BASE ** attempt
                                await asyncio.sleep(backoff_time)
                                retry_due_to_backoff = True
                                break

                    if retry_due_to_backoff:
                        continue

                except asyncio.TimeoutError:
                    logger.error("[DEXSCREENER] Timeout fetching %s:%s", chain_id, address[:8])
                    last_status = None
                    last_message = "timeout"
                    await self._api_call_log.record("dexscreener", "poll", None, "timeout", None)
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(self.BACKOFF_BASE ** attempt)
                        continue
                    result = None
                    return result
                except aiohttp.ClientError as exc:
                    logger.error("[DEXSCREENER] Client error for %s:%s: %s", chain_id, address[:8], exc)
                    last_status = None
                    last_message = f"client_error:{exc.__class__.__name__}"
                    await self._api_call_log.record("dexscreener", "poll", None, last_message, None)
                    if attempt < self.MAX_RETRIES - 1:
                        await asyncio.sleep(self.BACKOFF_BASE ** attempt)
                        continue
                    result = None
                    return result
                except Exception as exc:
                    logger.error(
                        "[DEXSCREENER] Unexpected error for %s:%s: %s",
                        chain_id,
                        address[:8],
                        exc,
                        exc_info=True,
                    )
                    last_status = None
                    last_message = f"exception:{exc.__class__.__name__}"
                    await self._api_call_log.record("dexscreener", "poll", None, last_message, None)
                    result = None
                    return result

            if combined_empty_payloads:
                self._cache[cache_key] = []
                self._cache_timestamps[cache_key] = datetime.utcnow()
                result = []
                return result

            result = None
            return result
        finally:
            if result is None and last_message:
                self._set_last_error(address, last_status, last_message)
                await self._token_model.update_last_api_error(address, "dexscreener", last_status, last_message)
            await self._metrics.record_check("dexscreener", result is not None)

    @staticmethod
    def _select_preferred_pair(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        return pairs[0]

    @staticmethod
    def _extract_pairs(data: Any) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            pairs = data.get("pairs")
            return pairs or []
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_decimal(value: Any) -> Optional[Decimal]:
        try:
            if value is None:
                return None
            return Decimal(str(value))
        except Exception:
            return None

    def get_market_cap(self, pair_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not pair_data:
            return None
        fdv = pair_data.get("fdv") or pair_data.get("marketCap")
        fdv_dec = self._to_decimal(fdv)
        if fdv_dec is None or fdv_dec <= 0:
            return None
        return fdv_dec

    def get_price(self, pair_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not pair_data:
            return None
        price = pair_data.get("priceUsd")
        price_dec = self._to_decimal(price)
        if price_dec is None or price_dec <= 0:
            return None
        return price_dec

    def get_liquidity(self, pair_data: Optional[Dict[str, Any]]) -> Optional[Decimal]:
        if not pair_data:
            return None
        liquidity_data = pair_data.get("liquidity", {})
        if isinstance(liquidity_data, dict):
            liquidity = liquidity_data.get("usd")
        else:
            liquidity = liquidity_data
        liquidity_dec = self._to_decimal(liquidity)
        if liquidity_dec is None or liquidity_dec < 0:
            return None
        return liquidity_dec

    def get_ticker(self, pair_data: Optional[Dict[str, Any]]) -> Optional[str]:
        if not pair_data:
            return None
        base_token = pair_data.get("baseToken", {})
        return base_token.get("symbol")

    def clear_cache(self, address: Optional[str] = None) -> None:
        if address:
            removed = False
            for key in list(self._cache.keys()):
                if key.endswith(f":{address}"):
                    self._cache.pop(key, None)
                    self._cache_timestamps.pop(key, None)
                    removed = True
            if removed:
                logger.debug("[DEXSCREENER] Cache cleared for %s", address[:8])
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
            logger.debug("[DEXSCREENER] All cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        now = datetime.utcnow()
        fresh_count = sum(
            1 for ts in self._cache_timestamps.values()
            if now - ts < timedelta(seconds=self.CACHE_TTL)
        )
        return {
            "total_cached": len(self._cache),
            "fresh_cached": fresh_count,
            "stale_cached": len(self._cache) - fresh_count,
            "cache_ttl_seconds": self.CACHE_TTL,
        }


_dexscreener_client_instance: Optional[DexScreenerAPIClient] = None


def get_dexscreener_client() -> DexScreenerAPIClient:
    global _dexscreener_client_instance
    if _dexscreener_client_instance is None:
        _dexscreener_client_instance = DexScreenerAPIClient()
    return _dexscreener_client_instance
