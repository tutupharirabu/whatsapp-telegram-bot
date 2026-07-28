#!/usr/bin/env python3
"""
Check availability WhatsApp & Telegram untuk daftar nomor HP dari CSV.

Metode:
- WhatsApp: Selenium + Chrome (buka web.whatsapp.com/send?phone=..., deteksi invalid page)
- Telegram: Telethon MTProto (ImportContactsRequest)

Usage:
    python checker.py source/players.csv
    python checker.py source/players.csv --output results.json
"""

import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

load_dotenv()

# ── WhatsApp Check Config ──
WA_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "runtime", "wa_chrome_profile")

# ── Telegram Check Config ──
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")


def normalize_phone(raw: str) -> str:
    """Normalisasi nomor HP ke format internasional tanpa '+'."""
    num = raw.replace("+", "").replace(" ", "").replace("-", "").strip()
    # Anggap prefix 62 Indonesia kalau cuma 10-12 digit tanpa kode negara
    if num.startswith("0"):
        num = "62" + num[1:]
    elif not num.startswith("62") and len(num) <= 12:
        num = "62" + num
    return num


def read_csv(filepath: str) -> List[Dict[str, str]]:
    """Baca CSV, return list of {nama, nomor_hp, nomor_normalized}."""
    players = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nama = row.get("nama", "").strip()
            hp = row.get("nomor_hp", "").strip()
            if not hp:
                continue
            players.append({
                "nama": nama,
                "nomor_hp": hp,
                "nomor_normalized": normalize_phone(hp),
            })
    return players


# ═══════════════════════════════════════════════════════════════
# WHATSAPP CHECK (Selenium + Chrome)
# ═══════════════════════════════════════════════════════════════

def _create_wa_driver() -> webdriver.Chrome:
    """Buat Chrome driver dengan WhatsApp Web session persistent."""
    options = Options()

    # Pakai user-data-dir untuk menyimpan session WhatsApp Web login
    options.add_argument(f"--user-data-dir={WA_PROFILE_DIR}")

    # Opsional: headless (lebih cepat, tanpa UI)
    headless = os.getenv("WA_HEADLESS", "").lower() in ("1", "true", "yes")
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=800,600")

    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(5)
    return driver


def _wait_for_wa_ready(driver: webdriver.Chrome, timeout: int = 30) -> bool:
    """
    Tunggu hingga WhatsApp Web siap (login selesai).
    Return True jika sudah login, False jika belum.
    """
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "canvas[aria-label='Scan me!'], div#app"))
        )
    except TimeoutException:
        return False

    # Cek apakah masih di halaman QR scan
    try:
        driver.find_element(By.CSS_SELECTOR, "canvas[aria-label='Scan me!']")
        return False  # Belum login, masih QR scan
    except:
        return True  # QR tidak ada = sudah login


def check_whatsapp_single(driver: webdriver.Chrome, phone: str, delay: float = 3.0) -> bool:
    """
    Cek satu nomor WhatsApp dengan membuka URL send.
    Return True jika nomor terdaftar di WA.
    """
    url = f"https://web.whatsapp.com/send?phone={phone}"
    driver.get(url)

    try:
        # Tunggu hingga halaman load: muncul chat box ATAU invalid page
        WebDriverWait(driver, 15).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#main")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-animate-modal-popup]")),
            )
        )
    except TimeoutException:
        pass

    time.sleep(delay)

    # Deteksi: jika muncul teks "invalid" atau "Phone number" di body, berarti tidak terdaftar
    page_source = driver.page_source.lower()
    is_invalid = "phone number shared via url is invalid" in page_source
    is_no_account = "this phone number isn't" in page_source or "doesn't have whatsapp" in page_source

    return not (is_invalid or is_no_account)


def check_whatsapp_batch(numbers: List[str]) -> Dict[str, bool]:
    """
    Cek WhatsApp availability via Selenium.
    Buka satu browser session, iterasi nomor via URL.
    Return {nomor_normalized: True/False}.
    """
    results: Dict[str, bool] = {}

    print("  WA: Starting Chrome...")
    driver = _create_wa_driver()

    try:
        # Navigasi ke WhatsApp Web dulu
        driver.get("https://web.whatsapp.com")

        if not _wait_for_wa_ready(driver, timeout=30):
            print("\n  ⚠ WhatsApp Web belum login!")
            print("  Silakan scan QR code lalu tekan Enter...")
            input()
            if not _wait_for_wa_ready(driver, timeout=10):
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

            # Jeda antar cek
            if i < len(numbers):
                time.sleep(1.5)

    finally:
        driver.quit()
        print("  WA: Browser closed.")

    return results


# ═══════════════════════════════════════════════════════════════
# TELEGRAM CHECK (Telethon)
# ═══════════════════════════════════════════════════════════════

async def check_telegram_batch(
    numbers: List[str],
    batch_size: int = 10,
    batch_delay: float = 3.0,
) -> Dict[str, Dict]:
    """
    Cek Telegram registration via Telethon.
    Return {nomor_normalized: {registered: bool, user_id: int|null}}.
    """
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        print("  ⚠ TELEGRAM_API_ID/HASH tidak di-set, skip TG check")
        return {n: {"registered": False, "user_id": None} for n in numbers}

    from telethon import TelegramClient, functions, types
    from telethon.errors import FloodWaitError, RPCError

    client = TelegramClient("runtime/checker_session", int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    client.flood_sleep_threshold = 30

    results: Dict[str, Dict] = {n: {"registered": False, "user_id": None} for n in numbers}

    await client.start(phone=TELEGRAM_PHONE or None)
    try:
        me = await client.get_me()
        print(f"  TG: Logged in as {me.first_name} (@{me.username})")

        total = len(numbers)
        for batch_start in range(0, total, batch_size):
            batch = numbers[batch_start:batch_start + batch_size]
            batch_num = batch_start // batch_size + 1
            total_batches = (total + batch_size - 1) // batch_size

            print(f"  TG: Batch {batch_num}/{total_batches} ({len(batch)} numbers)...")

            contacts = []
            for phone in batch:
                contacts.append(types.InputPhoneContact(
                    client_id=random.randrange(-(2**63), 2**63),
                    phone=f"+{phone}",
                    first_name="check",
                    last_name="",
                ))

            try:
                result = await client(
                    functions.contacts.ImportContactsRequest(contacts=contacts)
                )

                # Map phone → user
                phone_to_user = {}
                for user in result.users:
                    if user.phone:
                        clean = user.phone.replace("+", "")
                        phone_to_user[clean] = user

                for phone in batch:
                    if phone in phone_to_user:
                        results[phone] = {
                            "registered": True,
                            "user_id": phone_to_user[phone].id,
                        }

                # Cleanup: delete imported contacts
                if result.users:
                    await client(functions.contacts.DeleteContactsRequest(
                        id=list(result.users)
                    ))

            except FloodWaitError as e:
                print(f"  TG: FloodWait {e.seconds}s, skip batch ini")
            except RPCError as e:
                print(f"  TG: RPC error: {e}")

            if batch_start + batch_size < total:
                print(f"  TG: delay {batch_delay}s...")
                await asyncio.sleep(batch_delay)

    finally:
        await client.disconnect()

    return results


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

async def check_all(players: List[Dict]) -> List[Dict]:
    """
    Cek WA + TG untuk semua player.
    Return list player dengan field: wa_available, tg_available, tg_user_id.
    """
    numbers = [p["nomor_normalized"] for p in players]

    print(f"\n{'='*60}")
    print(f"CHECKING {len(players)} PLAYERS")
    print(f"{'='*60}")

    # ── WhatsApp check (Selenium) ──
    print(f"\n[WA] Checking via Selenium + Chrome...")
    wa_results = check_whatsapp_batch(numbers)
    wa_count = sum(1 for v in wa_results.values() if v)
    print(f"  WA: {wa_count}/{len(numbers)} registered")

    # ── Telegram check (batch via Telethon) ──
    print(f"\n[TG] Checking via Telethon...")
    tg_results = await check_telegram_batch(numbers)
    tg_count = sum(1 for v in tg_results.values() if v["registered"])
    print(f"  TG: {tg_count}/{len(numbers)} registered")

    # ── Gabungkan hasil ──
    for player in players:
        num = player["nomor_normalized"]
        player["wa_available"] = wa_results.get(num, False)
        player["tg_available"] = tg_results.get(num, {}).get("registered", False)
        player["tg_user_id"] = tg_results.get(num, {}).get("user_id")

    return players


def print_summary(players: List[Dict]) -> None:
    """Print tabel ringkasan."""
    print(f"\n{'='*80}")
    print(f"{'NAMA':<25} {'NOMOR':<18} {'WA':<6} {'TG':<6} {'TG_ID'}")
    print(f"{'='*80}")

    wa_yes = 0
    tg_yes = 0
    both_yes = 0
    none_yes = 0

    for p in players:
        wa = "YA" if p["wa_available"] else "TIDAK"
        tg = "YA" if p["tg_available"] else "TIDAK"
        tg_id = p.get("tg_user_id", "") or "-"

        if p["wa_available"]:
            wa_yes += 1
        if p["tg_available"]:
            tg_yes += 1
        if p["wa_available"] and p["tg_available"]:
            both_yes += 1
        if not p["wa_available"] and not p["tg_available"]:
            none_yes += 1

        nama = p["nama"][:24]
        print(f"{nama:<25} {p['nomor_hp']:<18} {wa:<6} {tg:<6} {tg_id}")

    print(f"{'='*80}")
    print(f"Total: {len(players)} players")
    print(f"  WA saja  : {wa_yes}")
    print(f"  TG saja  : {tg_yes}")
    print(f"  Keduanya : {both_yes}")
    print(f"  Tidak ada: {none_yes}")


def save_results(players: List[Dict], filepath: str) -> None:
    """Simpan hasil check ke JSON atau CSV."""
    if filepath.endswith(".json"):
        with open(filepath, "w") as f:
            json.dump(players, f, indent=2, ensure_ascii=False, default=str)
    else:
        fieldnames = ["nama", "nomor_hp", "nomor_normalized", "wa_available", "tg_available", "tg_user_id"]
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(players)
    print(f"\nHasil disimpan ke: {filepath}")


async def main():
    parser = argparse.ArgumentParser(description="Cek WhatsApp & Telegram availability dari CSV")
    parser.add_argument("csv", help="Path ke file CSV (kolom: nama, nomor_hp)")
    parser.add_argument("--output", "-o", help="Simpan hasil ke file (JSON atau CSV)")
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"File tidak ditemukan: {args.csv}")
        sys.exit(1)

    players = read_csv(args.csv)
    if not players:
        print("Tidak ada data player di CSV")
        sys.exit(1)

    players = await check_all(players)
    print_summary(players)

    if args.output:
        save_results(players, args.output)


if __name__ == "__main__":
    asyncio.run(main())
