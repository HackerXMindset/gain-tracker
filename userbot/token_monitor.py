"""
Token Monitor - Handles token detection and tracking from monitored messages.
"""

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

from config import MAX_VALID_MARKET_CAP, MIN_VALID_MARKET_CAP
from db import db
from scheduler.dex_service import get_dex_service
from services import get_dexscreener_client, get_jupiter_service, get_okx_service

logger = logging.getLogger(__name__)


class TokenMonitor:
    def __init__(self, userbot_id: int) -> None:
        self.userbot_id = userbot_id
        self.dex_client = get_dexscreener_client()
        self.okx_service = get_okx_service()

    async def _fetch_market_snapshot(
        self,
        address: str,
        blockchain: str,
    ) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[str]]:
        jupiter_service = get_jupiter_service()
        dex_client = self.dex_client
        market_cap: Optional[Decimal] = None
        price: Optional[Decimal] = None
        ticker: Optional[str] = None
        token_data = None

        if blockchain.upper() == "SOL":
            token_data = await jupiter_service.get_token_data(address, use_cache=False)
            if token_data:
                market_cap = self._normalize_decimal(jupiter_service.get_market_cap(token_data))
                price = self._normalize_decimal(jupiter_service.get_price(token_data))
                ticker = jupiter_service.get_ticker(token_data)

            if market_cap is None:
                okx_data = await self.okx_service.get_token_data(address, chain_id="501", use_cache=False)
                if okx_data:
                    market_cap = self._normalize_decimal(self.okx_service.get_market_cap(okx_data))

        if market_cap is None:
            normalized_chain = blockchain.strip().upper()
            if normalized_chain in ("SOL", "SOLANA"):
                chain_id = "solana"
            elif normalized_chain in ("BNB", "BSC", "BEP20", "BINANCE"):
                chain_id = "bsc"
            else:
                chain_id = blockchain.strip().lower() or "solana"

            pair_data = await dex_client.fetch_token(address, chain_id=chain_id, use_cache=False)
            if pair_data:
                market_cap = market_cap or self._normalize_decimal(dex_client.get_market_cap(pair_data))
                price = price or self._normalize_decimal(dex_client.get_price(pair_data))
                ticker = ticker or dex_client.get_ticker(pair_data)

        return market_cap, price, ticker

    async def _add_token_to_tracking(self, address: str, blockchain: str) -> Optional[int]:
        try:
            dex_service = get_dex_service()
            result = await dex_service.add_token(address)

            if not result.get("success"):
                logger.info("Skipping Dex registration for %s: %s", address, result.get("error"))
                return None

            market_cap, _, ticker = await self._fetch_market_snapshot(address, blockchain)

            if market_cap and market_cap > 0:
                if not (Decimal(MIN_VALID_MARKET_CAP) <= market_cap <= Decimal(MAX_VALID_MARKET_CAP)):
                    logger.warning(
                        "[SNAPSHOT] %s MC out of range: $%s (valid: $%s - $%s)",
                        address,
                        float(market_cap),
                        MIN_VALID_MARKET_CAP,
                        MAX_VALID_MARKET_CAP,
                    )
                    return None

                logger.info("[SNAPSHOT] %s MC: $%s, Ticker: %s", address, float(market_cap), ticker)

                token_record = await db.fetchrow(
                    """
                    UPDATE tokens_tracked
                    SET first_seen_mc = $2,
                        last_mc = $2,
                        ticker = COALESCE($3, ticker),
                        current_tier = 'tier_a',
                        next_poll_at = NOW() + INTERVAL '10 seconds',
                        last_checked_at = NOW()
                    WHERE address = $1
                    RETURNING id
                    """,
                    address,
                    market_cap,
                    ticker,
                )
            else:
                logger.warning("[SNAPSHOT] No market cap data for %s, scheduling Tier A retry", address)
                token_record = await db.fetchrow(
                    """
                    UPDATE tokens_tracked
                    SET current_tier = 'tier_a',
                        next_poll_at = NOW() + INTERVAL '10 seconds',
                        last_checked_at = NOW()
                    WHERE address = $1
                    RETURNING id
                    """,
                    address,
                )

            if token_record:
                token_id = token_record["id"]
                await dex_service.add_token_to_scheduler(token_id)
                return token_id

            logger.error("Token %s not found after add_token", address)
            return None
        except Exception as exc:
            logger.error("Error adding token to tracking: %s", exc)
            return None

    async def process_monitored_token(
        self,
        address: str,
        blockchain: str,
        chat_id: int,
        message_id: Optional[int],
        user_id: Optional[int],
        chat_type: Optional[str] = None,
    ) -> None:
        try:
            if message_id is None:
                logger.debug("[MONITOR] Missing message_id for %s in chat %s", address[:8], chat_id)
                return

            token = await db.fetchrow("SELECT id FROM tokens_tracked WHERE address = $1", address)
            if token:
                token_id = token["id"]
            else:
                token_id = await self._add_token_to_tracking(address, blockchain)
                if token_id is None:
                    logger.warning("[MONITOR] Unable to register %s for chat %s", address, chat_id)
                    return

            market_cap, _, _ = await self._fetch_market_snapshot(address, blockchain)
            if market_cap is None or market_cap <= 0:
                logger.warning("[MONITOR] Invalid market cap for %s: %s", address[:8], market_cap)
                return

            min_cap = Decimal(MIN_VALID_MARKET_CAP)
            max_cap = Decimal(MAX_VALID_MARKET_CAP)
            if not (min_cap <= market_cap <= max_cap):
                logger.warning(
                    "[MONITOR] Market cap for %s out of range: $%s (valid $%s - $%s)",
                    address[:8],
                    float(market_cap),
                    MIN_VALID_MARKET_CAP,
                    MAX_VALID_MARKET_CAP,
                )
                return

            result = await db.fetchrow(
                """
                INSERT INTO token_group_alerts
                (token_id, chat_id, first_seen_mc, original_message_id, original_user_id, first_seen_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (token_id, chat_id) DO NOTHING
                RETURNING id
                """,
                token_id,
                chat_id,
                market_cap,
                message_id,
                user_id,
                datetime.utcnow(),
            )

            if result:
                logger.info(
                    "[GROUP_ALERT_NEW] Token %s monitoring started for chat %s (type=%s) at $%s",
                    address[:8],
                    chat_id,
                    chat_type or "unknown",
                    float(market_cap),
                )
            else:
                desired_user_id = user_id

                if desired_user_id is None:
                    updated = await db.execute(
                        """
                        UPDATE token_group_alerts
                        SET original_user_id = NULL
                        WHERE token_id = $1
                          AND chat_id = $2
                          AND original_user_id IS NOT NULL
                        """,
                        token_id,
                        chat_id,
                    )
                    if updated != "UPDATE 0":
                        logger.info(
                            "[GROUP_ALERT_FIX] Cleared original_user_id for token %s chat %s",
                            address[:8],
                            chat_id,
                        )
                else:
                    updated = await db.execute(
                        """
                        UPDATE token_group_alerts
                        SET original_user_id = $3
                        WHERE token_id = $1
                          AND chat_id = $2
                          AND original_user_id IS DISTINCT FROM $3
                        """,
                        token_id,
                        chat_id,
                        desired_user_id,
                    )
                    if updated != "UPDATE 0":
                        logger.info(
                            "[GROUP_ALERT_FIX] Updated original_user_id for token %s chat %s to %s",
                            address[:8],
                            chat_id,
                            desired_user_id,
                        )

                logger.debug("[GROUP_ALERT_DUP] Chat %s already tracking token %s", chat_id, address[:8])

        except Exception as exc:
            logger.error(
                "[MONITOR] Error processing token %s for chat %s: %s",
                address[:8],
                chat_id,
                exc,
                exc_info=True,
            )

    @staticmethod
    def _normalize_decimal(value: Optional[Any]) -> Optional[Decimal]:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
