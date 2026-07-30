#!/usr/bin/env python3
"""
Telegram Bot - Kirim pesan otomatis ke user/chat Telegram tertentu.
Menggunakan Telegram Bot API (python-telegram-bot) dan Telethon (user account).
"""

import os
import asyncio
from telegram import Bot
from dotenv import load_dotenv

load_dotenv()


async def send_telegram_message(chat_id: str, message: str) -> dict:
    """Kirim via Bot API — hanya bisa ke user yang sudah pernah chat ke bot."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN belum di-set di file .env")

    bot = Bot(token=bot_token)
    sent_message = await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
    )

    return {
        "message_id": sent_message.message_id,
        "chat_id": sent_message.chat.id,
        "date": sent_message.date.isoformat(),
        "text": sent_message.text,
    }


async def send_telegram_user(chat_id: int, message: str) -> dict:
    """Kirim via Telethon user account — bisa DM siapa saja tanpa batasan bot."""
    from telethon import TelegramClient

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")

    if not api_id or not api_hash:
        raise ValueError("TELEGRAM_API_ID/HASH belum di-set di .env")

    session_path = os.path.join(os.path.dirname(__file__), "..", "runtime", "checker_session")
    client = TelegramClient(session_path, int(api_id), api_hash)
    await client.start(phone=phone or None)
    try:
        sent = await client.send_message(chat_id, message)
        return {
            "message_id": sent.id,
            "chat_id": sent.chat_id,
            "date": sent.date.isoformat(),
            "text": sent.message,
        }
    finally:
        await client.disconnect()


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
        print(f"Pesan terkirim ke Telegram!")
        print(f"  Chat ID: {result['chat_id']}")
        print(f"  Message ID: {result['message_id']}")
    except Exception as e:
        print(f"Gagal mengirim pesan: {e}")
        sys.exit(1)
