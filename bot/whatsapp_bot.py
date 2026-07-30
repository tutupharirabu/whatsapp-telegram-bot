#!/usr/bin/env python3
"""
WhatsApp Bot - Kirim pesan otomatis ke nomor WhatsApp tertentu.
Selenium + Chrome: satu driver persisten dipakai ulang untuk semua pengiriman
dalam satu batch, supaya browser WA cuma buka satu tab dan tidak berpindah-pindah window.
"""

import os
import random
import sys
import time
import urllib.parse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# ── WhatsApp Check Config ──
WA_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runtime", "wa_chrome_profile")

def create_wa_driver() -> webdriver.Chrome:
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


def wait_for_wa_ready(driver: webdriver.Chrome, timeout: int = 30) -> bool:
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


def wait_for_chat_or_invalid(driver: webdriver.Chrome, timeout: int = 15) -> None:
    """Tunggu hingga chat box ATAU modal invalid muncul (tidak raise kalau timeout)."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#main")),
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-animate-modal-popup]")),
            )
        )
    except TimeoutException:
        pass


def detect_invalid_number(driver: webdriver.Chrome) -> bool:
    """True jika halaman WA Web menunjukkan nomor tidak terdaftar/invalid."""
    page_source = driver.page_source.lower()
    is_invalid = "phone number shared via url is invalid" in page_source
    is_no_account = "this phone number isn't" in page_source or "doesn't have whatsapp" in page_source
    return is_invalid or is_no_account


def detect_wa_suspended(driver: webdriver.Chrome) -> bool:
    """True jika akun WA kena ban/restrict atau ke-logout (QR muncul lagi) mid-session."""
    ps = driver.page_source.lower()
    banned = (
        "your phone number is banned from using whatsapp" in ps
        or "account was banned" in ps
        or "you're temporarily banned" in ps
        or "you are temporarily banned" in ps
    )
    # QR / link-device muncul lagi = sesi mati / ke-logout
    logged_out = (
        "scan the qr" in ps
        or "scan qr code" in ps
        or "to log in by phone number" in ps
        or "link a device" in ps
    )
    return banned or logged_out


_driver = None


def _get_driver():
    """Ambil driver WhatsApp Web yang persisten; buka & login kalau belum ada."""
    global _driver
    if _driver is None:
        print("  WA: Starting Chrome (Background)...")
        _driver = create_wa_driver()
        _driver.get("https://web.whatsapp.com")

        if not wait_for_wa_ready(_driver, timeout=30):
            print("\n  ⚠ WhatsApp Web belum login!")
            print("  Silakan scan QR code lalu tekan Enter...")
            input()
            if not wait_for_wa_ready(_driver, timeout=10):
                print("  ❌ Tetap gagal login. Menghentikan proses batch.")
                _driver.quit()
                _driver = None
                return None

    return _driver


def close_wa_driver() -> None:
    """Tutup driver WhatsApp Web. Panggil sekali setelah satu batch pengiriman selesai."""
    global _driver
    if _driver is not None:
        _driver.quit()
        _driver = None
        print("  WA: Browser closed.")


def send_whatsapp_message(phone_number: str, message: str, wait_time: int = 15) -> dict:
    clean_number = phone_number.replace("+", "").replace(" ", "").strip()
    if not clean_number or not message:
        raise ValueError("Nomor HP dan pesan tidak boleh kosong")

    try:
        driver = _get_driver()
        if not driver:
            return {"status": "error", "phone": clean_number, "error": "WA_NOT_LOGGED_IN"}

        url = f"https://web.whatsapp.com/send?phone={clean_number}"
        driver.get(url)
        wait_for_chat_or_invalid(driver, timeout=15)
        time.sleep(2.0)

        if detect_wa_suspended(driver):
            return {"status": "suspended", "phone": clean_number, "error": "WA_BANNED_OR_LOGGED_OUT"}

        if detect_invalid_number(driver):
            return {"status": "error", "phone": clean_number, "error": "nomor_tidak_terdaftar"}

        box = WebDriverWait(driver, wait_time).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "footer div[contenteditable='true']"))
        )
        box.click()
        time.sleep(random.uniform(1.2, 3.0))  # jeda acak: waktu WA isi teks + anti-pola-robot
        
        # Split message lines to send properly via Selenium without firing too early
        for line in message.split("\n"):
            box.send_keys(line)
            box.send_keys(Keys.SHIFT, Keys.ENTER)
            
        box.send_keys(Keys.ENTER)

        return {
            "status": "success",
            "phone": clean_number,
            "message_preview": message[:50] + ("..." if len(message) > 50 else ""),
        }
    except Exception as e:
        return {"status": "error", "phone": clean_number, "error": str(e)}


send_whatsapp_instant = send_whatsapp_message  # alias kompatibilitas


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python bot/whatsapp_bot.py <phone_number> <message>")
        print("Example: python bot/whatsapp_bot.py 6281234567890 'Halo!'")
        sys.exit(1)

    phone = sys.argv[1]
    message = sys.argv[2]

    result = send_whatsapp_message(phone, message)
    close_wa_driver()
    if result["status"] == "success":
        print(f"Pesan WhatsApp terkirim ke {result['phone']}!")
    else:
        print(f"Gagal: {result.get('error')}")
        sys.exit(1)
