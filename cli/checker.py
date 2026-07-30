#!/usr/bin/env python3
"""
Checker Script - Verifikasi nomor terdaftar di WhatsApp dan Telegram.
Metode:
- WhatsApp: Menggunakan helper dari bot/whatsapp_bot.py
- Telegram: Telethon MTProto (ImportContactsRequest)
"""

import asyncio
import os
import time
from typing import List, Dict

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError, RPCError
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact

load_dotenv()

# ── Telegram Check Config ──
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime", "checker_session")


def check_whatsapp_single(driver, phone: str, delay: float = 3.0) -> bool:
    """
    Cek satu nomor WhatsApp dengan membuka URL send.
    Return True jika nomor terdaftar di WA.
    """
    from bot.whatsapp_bot import wait_for_chat_or_invalid, detect_invalid_number
    
    url = f"https://web.whatsapp.com/send?phone={phone}"
    driver.get(url)

    wait_for_chat_or_invalid(driver, timeout=15)
    time.sleep(delay)

    return not detect_invalid_number(driver)


def check_whatsapp_batch(numbers: List[str], progress_cb=None) -> Dict[str, bool]:
    """
    Cek WhatsApp availability via Selenium.
    Buka satu browser session, iterasi nomor via URL.
    Return {nomor_normalized: True/False}.
    Optional progress_cb(current, total) dipanggil setelah setiap nomor dicek.
    """
    from bot.whatsapp_bot import create_wa_driver, wait_for_wa_ready
    
    results: Dict[str, bool] = {}

    print("  WA: Starting Chrome...")
    driver = create_wa_driver()

    try:
        # Navigasi ke WhatsApp Web dulu
        driver.get("https://web.whatsapp.com")

        if not wait_for_wa_ready(driver, timeout=30):
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
            except Exception as e:
                print(f"  WA: [{i}/{len(numbers)}] {phone} → ERROR: {e}")
                results[phone] = False

            if progress_cb:
                progress_cb(i, len(numbers))

            # Jeda antar cek
            if i < len(numbers):
                time.sleep(1.5)

    finally:
        driver.quit()
        print("  WA: Browser closed.")

    return results


def check_telegram_batch(numbers: List[str]) -> Dict[str, bool]:
    """
    Cek Telegram availability batch menggunakan Telethon (ImportContactsRequest).
    Sangat cepat, karena kirim semua nomor sekaligus ke server.
    Return {nomor_normalized: True/False}.
    """
    if not API_ID or not API_HASH:
        print("  TG: ❌ TELEGRAM_API_ID / TELEGRAM_API_HASH tidak diatur di .env")
        return {n: False for n in numbers}

    results = {n: False for n in numbers}

    print("  TG: Starting Telethon client...")
    client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)

    try:
        client.start()
        print("  TG: Connected. Synchronizing contacts...")

        # Siapkan batch contacts
        contacts_to_import = []
        for idx, phone in enumerate(numbers):
            clean_phone = phone.replace("+", "").replace(" ", "").strip()
            # Telethon butuh ID unik, kita pakai index
            contacts_to_import.append(
                InputPhoneContact(
                    client_id=idx,
                    phone=f"+{clean_phone}",
                    first_name=f"Check_{idx}",
                    last_name=""
                )
            )

        # Kirim request import
        result = client(ImportContactsRequest(contacts=contacts_to_import))

        # result.users isinya user yang match dengan kontak yang dikirim
        matched_phones = set()
        for user in result.users:
            if user.phone:
                matched_phones.add(user.phone)

        # Map back to results
        for phone in numbers:
            clean_phone = phone.replace("+", "").replace(" ", "").strip()
            if clean_phone in matched_phones:
                results[phone] = True
                print(f"  TG: {phone} → YES")
            else:
                results[phone] = False
                print(f"  TG: {phone} → NO")

    except SessionPasswordNeededError:
        print("  TG: ⚠ 2FA password diperlukan, login dulu via interaktif.")
    except RPCError as e:
        print(f"  TG: ❌ RPC Error: {e}")
    except Exception as e:
        print(f"  TG: ❌ Error: {e}")
    finally:
        client.disconnect()
        print("  TG: Client disconnected.")

    return results


def check_all(numbers: List[str]) -> Dict[str, Dict[str, bool]]:
    """
    Kombinasi cek WA dan TG.
    Return format: { "628xxx": {"wa": True, "tg": False} }
    """
    clean_nums = [n.replace("+", "").replace(" ", "").strip() for n in numbers]
    final_res = {n: {"wa": False, "tg": False} for n in clean_nums}

    print(f"Memulai pengecekan untuk {len(clean_nums)} nomor.")
    print(f"{'='*60}")

    # ── WhatsApp check (Selenium) ──
    print(f"\n[WA] Checking via Selenium + Chrome...")
    wa_results = check_whatsapp_batch(clean_nums)
    wa_count = sum(1 for v in wa_results.values() if v)

    # ── Telegram check (Telethon) ──
    print(f"\n[TG] Checking via Telethon MTProto...")
    tg_results = check_telegram_batch(clean_nums)
    tg_count = sum(1 for v in tg_results.values() if v)

    print(f"\n{'='*60}")
    print("HASIL AKHIR:")
    for n in clean_nums:
        final_res[n]["wa"] = wa_results.get(n, False)
        final_res[n]["tg"] = tg_results.get(n, False)

        st_wa = "✅" if final_res[n]["wa"] else "❌"
        st_tg = "✅" if final_res[n]["tg"] else "❌"
        print(f"  {n:15} | WA: {st_wa} | TG: {st_tg}")

    print(f"\nSummary:")
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
    check_all(nums_to_check)
