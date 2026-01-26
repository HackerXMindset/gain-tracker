from __future__ import annotations

import asyncio
import os
import re
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import MessageEntityTextUrl, MessageEntityUrl, KeyboardButtonUrl


def _extract_value(url: str) -> Optional[str]:
    # Matches ...SOLANA=-=VALUE... from the button URL
    match = re.search(r"SOLANA=-=([A-Za-z0-9]+)", url)
    return match.group(1) if match else None


async def main() -> None:
    api_id = os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError(
            "Set TELEGRAM_API_ID/TELEGRAM_API_HASH or API_ID/API_HASH in your environment."
        )

    target_chat = os.getenv("TARGET_CHAT", "alpha_web3_bot")
    limit = int(os.getenv("SCAN_LIMIT", "50"))

    client = TelegramClient("session_name", int(api_id), api_hash)
    await client.start()

    async for msg in client.iter_messages(target_chat, limit=limit):
        urls: list[str] = []

        # URLs inside message text entities
        if msg.entities:
            for ent in msg.entities:
                if isinstance(ent, MessageEntityTextUrl):
                    urls.append(ent.url)
                elif isinstance(ent, MessageEntityUrl):
                    urls.append(msg.raw_text[ent.offset : ent.offset + ent.length])

        # URLs inside inline buttons
        if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonUrl):
                        urls.append(btn.url)

        for url in urls:
            value = _extract_value(url)
            if value:
                print(value)
                print(url)
                await client.disconnect()
                return

    print("No matching value found.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
