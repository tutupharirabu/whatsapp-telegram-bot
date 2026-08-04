#!/usr/bin/env python3
"""
Telegram Bot - Kirim pesan otomatis ke user/chat Telegram tertentu.
Menggunakan Telegram Bot API (python-telegram-bot) dan Telethon (user account).
"""

import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

_client = None
_client_lock = None  # dibuat lazy di get_telegram_client (kompatibel Python 3.9 tanpa event loop aktif)


async def get_telegram_client():
    """Ambil client Telethon shared (satu session runtime/tg_checker_session, dipakai ulang)."""
    global _client, _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    if _client is None:
        async with _client_lock:
            if _client is None:
                from telethon import TelegramClient

                api_id = os.getenv("TELEGRAM_API_ID")
                api_hash = os.getenv("TELEGRAM_API_HASH")
                phone = os.getenv("TELEGRAM_PHONE")

                if not api_id or not api_hash:
                    raise ValueError("TELEGRAM_API_ID/HASH belum di-set di .env")

                session_path = os.path.join(os.path.dirname(__file__), "..", "runtime", "tg_checker_session")
                _client = TelegramClient(session_path, int(api_id), api_hash)
                # type: ignore — stub telethon tidak meng-annotate start() sebagai coroutine
                await _client.start(phone=phone or None)  # type: ignore
    return _client


async def close_telegram_client() -> None:
    """Putuskan koneksi client Telethon shared."""
    global _client
    if _client is not None:
        await _client.disconnect()  # type: ignore
        _client = None


async def send_telegram_message(chat_id: str, message: str) -> dict:
    """Kirim via Bot API — hanya bisa ke user yang sudah pernah chat ke bot."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN belum di-set di file .env")

    bot = Bot(token=bot_token)
    sent_message = await bot.send_message(chat_id=chat_id, text=message)

    return {
        "message_id": sent_message.message_id,
        "chat_id": sent_message.chat.id,
        "date": sent_message.date.isoformat(),
        "text": sent_message.text,
    }


async def send_telegram_user(chat_id: int, message: str) -> dict:
    """Kirim via Telethon user account — bisa DM siapa saja tanpa batasan bot."""
    from telethon.errors import RPCError

    client = await get_telegram_client()
    try:
        sent = await client.send_message(chat_id, message)
    except (ValueError, OSError, RPCError) as e:
        return {"message_id": None, "error": str(e)}
    return {
        "message_id": sent.id,
        "chat_id": getattr(getattr(sent, "chat", None), "id", None),
        "date": sent.date.isoformat() if sent.date else "",
        "text": sent.message,
    }


def send_telegram_message_sync(chat_id: str, message: str) -> dict:
    return asyncio.run(send_telegram_message(chat_id, message))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python telegram_bot.py <chat_id> <message>")
        print("Example: python telegram_bot.py @username 'Halo, ini pesan otomatis!'")
        sys.exit(1)

    chat_id = sys.argv[1]
    message = sys.argv[2]

    try:
        result = send_telegram_message_sync(chat_id, message)
        print("Pesan terkirim ke Telegram!")
        print(f"  Chat ID: {result['chat_id']}")
        print(f"  Message ID: {result['message_id']}")
    except (ValueError, OSError) as e:
        print(f"Gagal mengirim pesan: {e}")
        sys.exit(1)
