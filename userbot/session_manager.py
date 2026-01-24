from __future__ import annotations

import logging
from typing import Optional, Dict, Any

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import AuthKeyError, AuthKeyUnregisteredError, FloodWaitError, UnauthorizedError

from config import settings

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, userbot_id: int, session_string: str) -> None:
        self.userbot_id = userbot_id
        self.session_string = session_string
        self.client: Optional[TelegramClient] = None
        self.connected = False
        self.userbot_username: Optional[str] = None
        self.userbot_user_id: Optional[int] = None

    async def initialize_client(self) -> bool:
        logger.debug(
            "[SessionManager] Initializing userbot %s (session length=%s)",
            self.userbot_id,
            len(self.session_string) if self.session_string else 0,
        )
        try:
            self.client = TelegramClient(
                StringSession(self.session_string),
                settings.api_id,
                settings.api_hash,
            )
            await self.client.start()
            self.connected = True

            me = await self.client.get_me()
            self.userbot_user_id = me.id
            self.userbot_username = me.username

            logger.info(
                "[SessionManager] Session initialized for userbot %s (id=%s, username=%s)",
                self.userbot_id,
                self.userbot_user_id,
                self.userbot_username,
            )
            return True
        except (AuthKeyError, AuthKeyUnregisteredError, UnauthorizedError) as exc:
            logger.error("[SessionManager] Auth error for userbot %s: %s", self.userbot_id, exc)
        except FloodWaitError as exc:
            logger.error("[SessionManager] Flood wait for userbot %s: %s", self.userbot_id, exc)
        except Exception as exc:
            logger.error("[SessionManager] Failed to initialize userbot %s: %s", self.userbot_id, exc)
        self.connected = False
        return False

    async def disconnect_client(self) -> None:
        if self.client:
            await self.client.disconnect()
            self.client = None
            self.connected = False
            logger.info("[SessionManager] Session disconnected for userbot %s", self.userbot_id)

    def is_connected(self) -> bool:
        return self.connected and self.client is not None and self.client.is_connected()

    def get_client(self) -> Optional[TelegramClient]:
        return self.client if self.is_connected() else None

    def get_user_info(self) -> Dict[str, Any]:
        return {
            "user_id": self.userbot_user_id,
            "username": self.userbot_username,
            "connected": self.is_connected(),
        }

    async def get_me(self):
        if not self.client:
            raise RuntimeError("Client not initialized")
        return await self.client.get_me()
