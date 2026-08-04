#!/usr/bin/env python3
"""
Checker Script - Verifikasi nomor terdaftar di WhatsApp dan Telegram.
Metode:
- WhatsApp: Menggunakan helper dari bot/whatsapp_bot.py
- Telegram: Telethon MTProto (ImportContactsRequest)
"""

import asyncio
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv
from selenium.common.exceptions import WebDriverException
from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError
from telethon.sync import TelegramClient
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

load_dotenv()

# ── Telegram Check Config ──
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
# Session khusus checker — TERPISAH dari runtime/tg_checker_session milik send.py/telegram_bot.py
# supaya tidak saling lock saat checker & pengiriman berjalan bergantian.
SESSION_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime", "checker_session")


def check_whatsapp_single(driver, phone: str, delay: float = 3.0) -> bool:
    """
    Cek satu nomor WhatsApp dengan membuka URL send.
    Return True jika nomor terdaftar di WA.
    """
    from bot.whatsapp_bot import detect_invalid_number, wait_for_chat_or_invalid
    
    url = f"https://web.whatsapp.com/send?phone={phone}"
    driver.get(url)

    wait_for_chat_or_invalid(driver, timeout=15)
    time.sleep(delay)

    return not detect_invalid_number(driver)


def check_whatsapp_batch(numbers: list[str], progress_cb=None, skip_interactive: bool = False) -> dict[str, bool]:
    """
    Cek WhatsApp availability via Selenium.
    Buka satu browser session, iterasi nomor via URL.
    Return {nomor_normalized: True/False}.
    Optional progress_cb(current, total) dipanggil setelah setiap nomor dicek.
    """
    from bot.whatsapp_bot import (
        create_wa_driver,
        release_wa_profile_lock,
        wait_for_wa_ready,
    )
    
    results: dict[str, bool] = {}

    print("  WA: Starting Chrome...")
    driver = create_wa_driver()

    try:
        # Navigasi ke WhatsApp Web dulu
        driver.get("https://web.whatsapp.com")

        if not wait_for_wa_ready(driver, timeout=30):
            if skip_interactive:
                print("  ❌ WhatsApp Web belum login. Skipping (non-interactive mode).")
                return {n: False for n in numbers}
            
            print("\n  ⚠ WhatsApp Web belum login!")
            print("  Silakan scan QR code lalu tekan Enter...")
            input()
            if not wait_for_wa_ready(driver, timeout=10):
                print("  ❌ Tetap gagal login. Pastikan WhatsApp Web sudah login.")
                return {n: False for n in numbers}

        print(f"  WA: Connected. Checking {len(numbers)} numbers...")

        for i, phone in enumerate(numbers, 1):
            try:
                has_wa = check_whatsapp_single(driver, phone, delay=2.0)
                results[phone] = has_wa
                status = "YES" if has_wa else "NO"
                print(f"  WA: [{i}/{len(numbers)}] {phone} → {status}")
            except (WebDriverException, ValueError, OSError) as e:
                print(f"  WA: [{i}/{len(numbers)}] {phone} → ERROR: {e}")
                results[phone] = False

            if progress_cb:
                progress_cb(i, len(numbers))

            # Jeda antar cek
            if i < len(numbers):
                time.sleep(1.5)

    finally:
        driver.quit()
        release_wa_profile_lock()
        print("  WA: Browser closed.")

    return results


async def check_telegram_batch(numbers_or_players) -> dict[str, bool]:
    """
    Cek Telegram availability batch menggunakan Telethon (ImportContactsRequest).
    Sangat cepat, karena kirim semua nomor sekaligus ke server.
    Return {nomor_normalized: True/False}.
    """
    if not API_ID or not API_HASH:
        print("  TG: ❌ TELEGRAM_API_ID / TELEGRAM_API_HASH tidak diatur di .env")
        # Extract numbers to return a default dict
        default_results = {}
        for idx, item in enumerate(numbers_or_players):
            phone = item.get("nomor_normalized") if isinstance(item, dict) else str(item)
            default_results[phone] = None
        return default_results

    # Extract numbers and names
    contacts_to_import = []
    numbers = []
    for idx, item in enumerate(numbers_or_players):
        if isinstance(item, dict):
            phone = item.get("nomor_normalized") or item.get("nomor_hp")
            name = item.get("nama") or f"Check_{idx}"
        elif isinstance(item, (tuple, list)):
            phone = item[0]
            name = item[1] if len(item) > 1 else f"Check_{idx}"
        else:
            phone = str(item)
            name = f"Check_{idx}"
            
        clean_phone = (phone or "").replace("+", "").replace(" ", "").replace("-", "").strip()
        numbers.append(phone or "")
        contacts_to_import.append(
            InputPhoneContact(
                client_id=idx,
                phone=f"+{clean_phone}",
                first_name=name,
                last_name=""
            )
        )

    results: dict[str, Any] = {n: None for n in numbers}

    print("  TG: Starting Telethon client...")
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

    try:
        await client.start()  # type: ignore — stub telethon tidak meng-annotate start() sebagai coroutine
        print("  TG: Connected. Synchronizing contacts...")

        # Kirim request import
        result = await client(ImportContactsRequest(contacts=contacts_to_import))

        # result.users isinya user yang match dengan kontak yang dikirim
        matched_users = {}
        for user in result.users:  # type: ignore[attr-defined] — tipe respon RPC tidak ada di stub
            if user.phone:
                clean_user_phone = user.phone.replace("+", "").replace(" ", "").strip()
                matched_users[clean_user_phone] = user.id

        # Map back to results
        for phone in numbers:
            clean_phone = (phone or "").replace("+", "").replace(" ", "").strip()
            if clean_phone in matched_users:
                results[phone] = matched_users[clean_phone]
                print(f"  TG: {phone} → YES (ID: {matched_users[clean_phone]})")
            else:
                results[phone] = None
                print(f"  TG: {phone} → NO")

    except FloodWaitError as e:
        print(f"  TG: ⚠ FloodWait — kena rate limit, tunggu {e.seconds} detik sebelum coba lagi. Hasil parsial dikembalikan.")
    except SessionPasswordNeededError:
        print("  TG: ⚠ 2FA password diperlukan, login dulu via interaktif.")
    except RPCError as e:
        print(f"  TG: ❌ RPC Error: {e}")
    except (ValueError, TypeError, OSError) as e:
        print(f"  TG: ❌ Error: {e}")
    finally:
        await client.disconnect()  # type: ignore
        print("  TG: Client disconnected.")

    return results


async def check_all(numbers_or_players) -> dict[str, dict[str, Any]]:
    """
    Kombinasi cek WA dan TG.
    Return format: { "628xxx": {"wa": True, "tg": False} }
    """
    clean_nums = []
    for item in numbers_or_players:
        if isinstance(item, dict):
            num = item.get("nomor_normalized") or item.get("nomor_hp")
        else:
            num = str(item)
        clean_nums.append((num or "").replace("+", "").replace(" ", "").replace("-", "").strip())
        
    final_res: dict[str, dict[str, Any]] = {n: {"wa": False, "tg": False} for n in clean_nums}

    print(f"Memulai pengecekan untuk {len(clean_nums)} nomor.")
    print(f"{'='*60}")

    # ── WhatsApp check (Selenium) ──
    print("\n[WA] Checking via Selenium + Chrome...")
    wa_results = check_whatsapp_batch(clean_nums)
    wa_count = sum(1 for v in wa_results.values() if v)

    # ── Telegram check (Telethon) ──
    print("\n[TG] Checking via Telethon MTProto...")
    tg_results = await check_telegram_batch(numbers_or_players)
    tg_count = sum(1 for v in tg_results.values() if v is not None and v is not False)

    print(f"\n{'='*60}")
    print("HASIL AKHIR:")
    for n in clean_nums:
        # Find results for this number
        # Note: tg_results has the original phone format from input
        # So we look it up using both clean_phone and original phone
        tg_val = None
        for key, val in tg_results.items():
            if key.replace("+", "").replace(" ", "").replace("-", "").strip() == n:
                tg_val = val
                break
                
        final_res[n]["wa"] = wa_results.get(n, False)
        final_res[n]["tg"] = tg_val

        st_wa = "✅" if final_res[n]["wa"] else "❌"
        st_tg = "✅" if final_res[n]["tg"] else "❌"
        print(f"  {n:15} | WA: {st_wa} | TG: {st_tg}")

    print("\nSummary:")
    print(f"Total: {len(clean_nums)} numbers")
    print(f"WA Available: {wa_count}")
    print(f"TG Available: {tg_count}")

    return final_res


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python cli/checker.py <number1> [<number2> ...]")
        sys.exit(1)

    nums_to_check = sys.argv[1:]
    asyncio.run(check_all(nums_to_check))
