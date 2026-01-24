from __future__ import annotations

import logging
import re
from typing import List, Tuple

from config import settings

logger = logging.getLogger(__name__)


class UserbotUtils:
    def __init__(self) -> None:
        self.solana_pattern = re.compile(settings.solana_pattern)
        self.bnb_pattern = re.compile(settings.bnb_pattern)

    def extract_solana_addresses(self, text: str) -> List[str]:
        if not text:
            return []
        return list(set(self.solana_pattern.findall(text)))

    def extract_bnb_addresses(self, text: str) -> List[str]:
        if not text:
            return []
        match = self.bnb_pattern.search(text)
        if match:
            return [match.group(0)]
        return []

    def extract_token_addresses(self, text: str) -> List[Tuple[str, str]]:
        if not text:
            return []
        sol_addresses = self.extract_solana_addresses(text)
        bnb_addresses = self.extract_bnb_addresses(text)

        tagged = [(addr, "SOL") for addr in sol_addresses]
        tagged.extend((addr, "BNB") for addr in bnb_addresses)
        return tagged

    def get_message_text(self, message) -> str:
        if hasattr(message, "text") and message.text:
            return str(message.text)
        return ""

    def get_chat_title(self, chat) -> str:
        if not chat:
            return "Unknown Chat"
        if hasattr(chat, "title") and chat.title:
            return chat.title
        if hasattr(chat, "first_name"):
            name = chat.first_name or ""
            if hasattr(chat, "last_name") and chat.last_name:
                name += f" {chat.last_name}"
            return name.strip() or f"Chat {getattr(chat, 'id', 'Unknown')}"
        if hasattr(chat, "username") and chat.username:
            return f"@{chat.username}"
        return f"Chat {getattr(chat, 'id', 'Unknown')}"
