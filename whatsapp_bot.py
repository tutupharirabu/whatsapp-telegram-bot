#!/usr/bin/env python3
"""
WhatsApp Bot - Kirim pesan otomatis ke nomor WhatsApp tertentu.
Auto-detect OS: AppleScript di macOS, pyautogui di Windows/Linux.
"""

import os
import sys
import subprocess
import time
from dotenv import load_dotenv

load_dotenv()

IS_MACOS = sys.platform == "darwin"
CTRL = "command" if IS_MACOS else "ctrl"


# ═══════════════════════════════════════════════════════════════
# macOS: AppleScript (pure, no pyautogui)
# ═══════════════════════════════════════════════════════════════

def _send_wa_macos(phone: str, message: str, browser: str, wait_time: int, close_tab: bool) -> dict:
    import pyperclip

    wa_url = f"https://web.whatsapp.com/send?phone={phone}"
    pyperclip.copy(message)

    scpt = f'''
    tell application "{browser}"
        activate
        open location "{wa_url}"
    end tell

    delay {wait_time}

    tell application "System Events"
        tell process "{browser}"
            keystroke "v" using command down
            delay 0.5
            key code 36
        end tell
    end tell
    '''

    if close_tab:
        scpt += f'''
    delay 2
    tell application "System Events"
        tell process "{browser}"
            keystroke "w" using command down
        end tell
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", scpt],
            capture_output=True,
            text=True,
            timeout=wait_time + 30,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            hint = ""
            if "not allowed" in err.lower() or "not authorized" in err.lower() or "-1743" in err or "-25211" in err:
                hint = (
                    "\n  ⚠️  macOS memblokir kontrol otomatis."
                    "\n  Perbaiki: System Settings → Privacy & Security → Accessibility"
                    "\n  → aktifkan Terminal/IDE kamu."
                )
            return {"status": "error", "error": err + hint}
        return {"status": "success"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "AppleScript timeout"}


# ═══════════════════════════════════════════════════════════════
# Windows / Linux: webbrowser + pyautogui
# ═══════════════════════════════════════════════════════════════

def _send_wa_other(phone: str, message: str, browser: str, wait_time: int, close_tab: bool) -> dict:
    import webbrowser
    import pyperclip
    import pyautogui

    wa_url = f"https://web.whatsapp.com/send?phone={phone}"

    if browser:
        try:
            wb = webbrowser.get(browser)
        except webbrowser.Error:
            wb = webbrowser
    else:
        wb = webbrowser

    wb.open(wa_url)
    time.sleep(wait_time)
    pyautogui.click()  # fokus ke window browser

    pyperclip.copy(message)
    pyautogui.hotkey(CTRL, "v")
    time.sleep(0.5)
    pyautogui.press("enter")

    if close_tab:
        time.sleep(2)
        pyautogui.hotkey(CTRL, "w")

    return {"status": "success"}


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def send_whatsapp_message(
    phone_number: str,
    message: str,
    wait_time: int = 15,
    close_tab: bool = True,
    browser: str = None,
) -> dict:
    clean_number = phone_number.replace("+", "").replace(" ", "").strip()
    if not clean_number or not message:
        raise ValueError("Nomor HP dan pesan tidak boleh kosong")

    try:
        if IS_MACOS:
            browser = browser or os.getenv("WA_BROWSER_APP", "Arc")
            result = _send_wa_macos(clean_number, message, browser, wait_time, close_tab)
        else:
            browser = browser or os.getenv("WA_BROWSER_APP", "")
            result = _send_wa_other(clean_number, message, browser, wait_time, close_tab)

        return {
            **result,
            "phone": clean_number,
            "message_preview": message[:50] + ("..." if len(message) > 50 else ""),
        }
    except Exception as e:
        return {"status": "error", "phone": clean_number, "error": str(e)}


send_whatsapp_instant = send_whatsapp_message  # alias kompatibilitas


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python whatsapp_bot.py <phone_number> <message>")
        print("Example: python whatsapp_bot.py 6281234567890 'Halo!'")
        sys.exit(1)

    phone = sys.argv[1]
    message = sys.argv[2]

    result = send_whatsapp_message(phone, message)
    if result["status"] == "success":
        print(f"Pesan WhatsApp terkirim ke {result['phone']}!")
    else:
        print(f"Gagal: {result['error']}")
        sys.exit(1)
