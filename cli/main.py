#!/usr/bin/env python3
"""
WhatsApp & Telegram Auto Messenger
Script utama untuk mengirim pesan otomatis ke WhatsApp dan Telegram.
"""

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot.telegram_bot import send_telegram_message_sync
from bot.whatsapp_bot import send_whatsapp_message


def main():
    parser = argparse.ArgumentParser(
        description="Auto Messenger - Kirim pesan otomatis ke WhatsApp & Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:

  # Kirim ke WhatsApp
  python main.py --wa 6281234567890 --message "Halo, reminder!"

  # Kirim ke Telegram
  python main.py --tg @username --message "Halo dari bot!"

  # Kirim ke WA + Telegram sekaligus
  python main.py --wa 6281234567890 --tg @username --message "Broadcast!"
        """,
    )

    parser.add_argument(
        "--wa",
        type=str,
        help="Nomor WhatsApp tujuan (format internasional tanpa '+', contoh: 6281234567890)",
    )
    parser.add_argument(
        "--tg",
        type=str,
        help="Chat ID Telegram tujuan (username @user atau numeric ID)",
    )
    parser.add_argument(
        "--message", "-m",
        type=str,
        required=True,
        help="Isi pesan yang akan dikirim",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=15,
        help="Waktu tunggu (detik) untuk loading WhatsApp Web (default: 15)",
    )

    args = parser.parse_args()

    if not args.wa and not args.tg:
        parser.error("Minimal satu tujuan harus diisi: --wa atau --tg")

    results: dict[str, Any] = {"whatsapp": None, "telegram": None}

    if args.wa:
        print(f"\nMengirim WhatsApp ke {args.wa}...")
        try:
            result = send_whatsapp_message(args.wa, args.message, wait_time=args.wait)

            results["whatsapp"] = result
            if result["status"] == "success":
                print("  WA: Terkirim")
            else:
                print(f"  WA: Gagal - {result.get('error', 'Unknown')}")
        except (ValueError, OSError, RuntimeError):
            print("  WA Exception: terjadi kesalahan saat mengirim (detail disembunyikan)")
            results["whatsapp"] = {"status": "error", "error": "WA send exception"}

    if args.tg:
        print(f"\nMengirim Telegram ke {args.tg}...")
        try:
            result = send_telegram_message_sync(args.tg, args.message)
            results["telegram"] = result
            print("  TG: Terkirim!")
            print(f"  Chat ID: {result['chat_id']}")
            print(f"  Message ID: {result['message_id']}")
        except (ValueError, OSError, RuntimeError):
            print("  TG Exception: terjadi kesalahan saat mengirim (detail disembunyikan)")
            results["telegram"] = {"status": "error", "error": "TG send exception"}

    print("\n" + "=" * 50)
    print("RINGKASAN:")
    if args.wa:
        status = "Berhasil" if (results["whatsapp"] and results["whatsapp"]["status"] == "success") else "Gagal"
        print(f"  WhatsApp : {status}")
    if args.tg:
        status = "Berhasil" if results["telegram"] and "message_id" in results["telegram"] else "Gagal"
        print(f"  Telegram : {status}")
    print("=" * 50)

    wa_failed = results["whatsapp"] and results["whatsapp"]["status"] != "success"
    tg_failed = results["telegram"] and "message_id" not in results["telegram"]
    if wa_failed or tg_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
