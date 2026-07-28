#!/usr/bin/env python3
"""
Bulk Messenger - Kirim pesan massal ke GCAF 2026 players.

Alur:
1. Baca CSV source/
2. Cek WA & TG availability (via checker.py)
3. Kirim pesan ke platform yang available
4. Jeda antar pengiriman (anti-spam)

Usage:
    python bulk.py source/players.csv -m "Halo GCAF 2026!"
    python bulk.py source/players.csv -m "..." --wa-only
    python bulk.py source/players.csv -m "..." --tg-only
    python bulk.py source/players.csv -m "..." --delay 3
"""

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv

from checker import check_all, normalize_phone, read_csv
from telegram_bot import send_telegram_user
from whatsapp_bot import send_whatsapp_message

load_dotenv()

FASIL_PHONE = normalize_phone(os.getenv("TELEGRAM_PHONE", ""))


TEMPLATES = {
    "formal": (
        "Halo, Kak {nama}! 👋\n"
        "Selamat pagi/siang/sore.\n\n"
        "Perkenalkan, saya Irfan Zharauri, salah satu fasilitator dari "
        "Program Google Skills Arcade Fasilitator 2026 dengan kode fasil GCAF26-ID-9MJ-EP6. 😊\n\n"
        "Betul ini dengan Kak {nama}?\n\n"
        "Jika benar, mohon segera bergabung ke grup Telegram koordinasi kita melalui link berikut ya, Kak:\n"
        "👉 https://t.me/+wXiMsFTC-jsyODhl\n\n"
        "Kalau ada kendala saat masuk grup, silakan infokan ke saya atau via email ke:\n"
        "📧 arcade@dicoding.com.\n\n"
        "Terima kasih banyak, Kak! ✨"
    ),
    "kasual": (
        "Halo, {nama}! 👋\n\n"
        "Apa kabar? Semoga sehat selalu, ya!\n\n"
        "Kenalin, aku Irfan Zharauri, fasilitator kamu di "
        "Google Skills Arcade Fasilitator 2026 dengan kode fasil GCAF26-ID-9MJ-EP6. 🍵🎮\n\n"
        "Beneran ini dengan {nama}, kan? 🤞\n\n"
        "Biar kita bisa langsung komunikasi dan koordinasi, yuk langsung join "
        "ke grup Telegram kelompok kita di sini:\n"
        "👉 https://t.me/+wXiMsFTC-jsyODhl\n\n"
        "Kalau kamu ada kendala pas mau masuk grupnya, langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "See you in the group! 🚀"
    ),
    "remind-redeem": (
        "Halo, {nama}! 👋\n\n"
        "Cuma mau ngingetin nih, kamu belum redeem kode akses buat "
        "program Google Skills Arcade Fasilitator 2026.\n\n"
        "⚠️ Kalau belum redeem sampai 7 Agustus 2026, "
        "token kredit kamu akan di-assign ke registrant lain lho!\n\n"
        "Yuk segera redeem kode aksesnya! Kalau ada kendala, "
        "langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "Semangat! 🚀"
    ),
    "remind-gear": (
        "Halo, {nama}! 👋\n\n"
        "Cuma mau ngingetin nih, kamu belum dapet Lencana Digital GEAR "
        "(Gemini Enterprise Agent Ready) buat program Google Skills Arcade Fasilitator 2026.\n\n"
        "Yuk segera akses & selesaikan di:\n"
        "👉 dicoding.id/Arcade26-GearBadge\n\n"
        "Kalau ada kendala, langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "Semangat! 🚀"
    ),
    "remind-both": (
        "Halo, {nama}! 👋\n\n"
        "Cuma mau ngingetin nih, kamu masih ada PR buat "
        "program Google Skills Arcade Fasilitator 2026:\n\n"
        "1. Redeem kode akses\n"
        "   ⚠️ Kalau belum redeem sampai 7 Agustus 2026, "
        "token kredit akan di-assign ke registrant lain!\n"
        "2. Lencana Digital GEAR → dicoding.id/Arcade26-GearBadge\n\n"
        "Yuk segera diselesaikan ya! Kalau ada kendala, "
        "langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "Semangat! 🚀"
    ),
}


def personalize_message(template: str, player: Dict, fasil_name: str = "", fasil_kode: str = "") -> str:
    """Ganti placeholder {nama}, {nama_fasil}, {kode_fasil} di template pesan."""
    msg = template.replace("{nama}", player.get("nama", "Player"))
    msg = msg.replace("{nama_fasil}", fasil_name)
    msg = msg.replace("{kode_fasil}", fasil_kode)
    return msg


async def send_to_player(
    player: Dict,
    message: str,
    wa_only: bool = False,
    tg_only: bool = False,
    wait_time: int = 15,
    fasil_name: str = "",
    fasil_kode: str = "",
) -> Dict:
    """
    Kirim pesan ke satu player via platform yang available.
    Return dict status pengiriman.
    """
    name = player["nama"]
    num = player["nomor_normalized"]
    msg = personalize_message(message, player, fasil_name, fasil_kode)
    result = {
        "nama": name,
        "nomor_hp": player["nomor_hp"],
        "wa_available": player["wa_available"],
        "tg_available": player["tg_available"],
        "wa_sent": False,
        "tg_sent": False,
        "wa_error": None,
        "tg_error": None,
    }

    # ── WhatsApp ──
    if not tg_only and player["wa_available"]:
        try:
            wa_result = send_whatsapp_message(num, msg, wait_time=wait_time)
            if wa_result["status"] == "success":
                result["wa_sent"] = True
            else:
                result["wa_error"] = wa_result.get("error", "Unknown")
        except Exception as e:
            result["wa_error"] = str(e)

    # ── Telegram ──
    if not wa_only and player["tg_available"] and player.get("tg_user_id"):
        try:
            tg_result = await send_telegram_user(int(player["tg_user_id"]), msg)
            if tg_result.get("message_id"):
                result["tg_sent"] = True
            else:
                result["tg_error"] = "No message_id returned"
        except Exception as e:
            result["tg_error"] = str(e)

    return result


def save_log(results: List[Dict], filepath: str = "runtime/logs/bulk_results.csv") -> None:
    """Simpan log pengiriman ke CSV."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    fieldnames = [
        "nama", "nomor_hp",
        "wa_available", "tg_available",
        "wa_sent", "tg_sent",
        "wa_error", "tg_error",
        "timestamp",
    ]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    print(f"\nLog disimpan ke: {filepath}")


def print_progress(current: int, total: int, player: Dict, result: Dict) -> None:
    """Print progress pengiriman per player."""
    name = player["nama"]
    wa_status = "WA✅" if result["wa_sent"] else ("WA❌" if player["wa_available"] else "WA—")
    tg_status = "TG✅" if result["tg_sent"] else ("TG❌" if player["tg_available"] else "TG—")
    print(f"  [{current}/{total}] {name:<25} {wa_status}  {tg_status}")


async def main():
    parser = argparse.ArgumentParser(
        description="Bulk Messenger - Kirim pesan massal ke GCAF 2026 players",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python bulk.py source/example.csv --mode formal
  python bulk.py source/example.csv --mode kasual --wa-only
  python bulk.py source/reminders.csv --mode remind-redeem --wa-only
  python bulk.py source/reminders.csv --mode remind-gear --wa-only
  python bulk.py source/example.csv -m "Halo {nama}!" --wa-only
  python bulk.py source/example.csv --mode formal --delay 3 --dry-run
        """,
    )
    parser.add_argument("csv", help="Path ke file CSV (kolom: nama, nomor_hp)")
    parser.add_argument("-m", "--message", help="Isi pesan custom (gunakan {nama}, {nama_fasil}, {kode_fasil} untuk placeholder)")
    parser.add_argument("--mode", choices=["formal", "kasual", "remind-redeem", "remind-gear", "remind-both"], help="Gunakan template bawaan")
    parser.add_argument("--fasil-name", default="", help="Nama fasilitator")
    parser.add_argument("--fasil-kode", default="", help="Kode fasilitator")
    parser.add_argument("--wa-only", action="store_true", help="Hanya kirim WhatsApp")
    parser.add_argument("--tg-only", action="store_true", help="Hanya kirim Telegram")
    parser.add_argument("--delay", type=int, default=5, help="Jeda antar pengiriman dalam detik (default: 5)")
    parser.add_argument("--wait-wa", type=int, default=15, help="Wait time WA Web loading (default: 15)")
    parser.add_argument("--dry-run", action="store_true", help="Hanya cek & tampilkan, tidak kirim")
    parser.add_argument("--skip-check", action="store_true", help="Gunakan hasil cek sebelumnya (dari JSON)")
    parser.add_argument("--check-file", type=str, help="File JSON hasil checker.py sebelumnya")

    args = parser.parse_args()

    if not args.message and not args.mode:
        parser.error("Harus pakai --message (-m) atau --mode (formal/kasual)")

    # ── Tentukan pesan ──
    if args.mode:
        message = TEMPLATES[args.mode]
    else:
        message = args.message

    if not os.path.exists(args.csv):
        print(f"File tidak ditemukan: {args.csv}")
        sys.exit(1)

    # ── Load player data ──
    if args.check_file:
        import json
        with open(args.check_file, "r") as f:
            players = json.load(f)
        print(f"Loaded {len(players)} players dari {args.check_file} (skip cek)")
    else:
        players = read_csv(args.csv)
        if not players:
            print("Tidak ada data player di CSV")
            sys.exit(1)

        if args.skip_check:
            # Force send — WA bisa langsung, TG butuh user_id dari cek
            for p in players:
                p["wa_available"] = True
                p["tg_available"] = False
                p["tg_user_id"] = None
            print("Skip cek — asumsikan semua nomor available (WA saja, TG perlu cek dulu)")
        else:
            players = await check_all(players)
            print(f"\nCek selesai. Memulai pengiriman...")

    # ── Skip nomor fasilitator sendiri ──
    if FASIL_PHONE:
        original_count = len(players)
        players = [p for p in players if p["nomor_normalized"] != FASIL_PHONE]
        skipped_self = original_count - len(players)
        if skipped_self:
            print(f"  ⏭ Skip {skipped_self} player (nomor sendiri: {FASIL_PHONE})")

    # ── Filter player yang punya platform sesuai mode ──
    if args.wa_only:
        eligible = [p for p in players if p["wa_available"]]
        mode = "WhatsApp only"
    elif args.tg_only:
        eligible = [p for p in players if p["tg_available"]]
        mode = "Telegram only"
    else:
        eligible = [p for p in players if p["wa_available"] or p["tg_available"]]
        mode = "WA + Telegram"

    skipped = len(players) - len(eligible)
    print(f"\n{'='*60}")
    print(f"BULK SEND: {len(eligible)} players ({mode})")
    if skipped:
        print(f"  ({skipped} diskip — tidak punya platform)")
    if args.dry_run:
        print(f"  🔍 DRY RUN — tidak benar-benar kirim")
    print(f"{'='*60}")

    # ── Kirim ke setiap player ──
    results = []
    total = len(eligible)
    wa_success = 0
    tg_success = 0

    for i, player in enumerate(eligible, 1):
        name = player["nama"]

        if args.dry_run:
            result = {
                "nama": name,
                "nomor_hp": player["nomor_hp"],
                "wa_available": player["wa_available"],
                "tg_available": player["tg_available"],
                "wa_sent": False,
                "tg_sent": False,
                "wa_error": None,
                "tg_error": None,
                "timestamp": datetime.now().isoformat(),
            }
        else:
            result = await send_to_player(
                player,
                message,
                wa_only=args.wa_only,
                tg_only=args.tg_only,
                wait_time=args.wait_wa,
                fasil_name=args.fasil_name,
                fasil_kode=args.fasil_kode,
            )
            result["timestamp"] = datetime.now().isoformat()

            if result["wa_sent"]:
                wa_success += 1
            if result["tg_sent"]:
                tg_success += 1

        results.append(result)
        print_progress(i, total, player, result)

        # ── Jeda antar pemain (anti-spam) ──
        if i < total and not args.dry_run:
            time.sleep(args.delay)

    # ── Ringkasan ──
    print(f"\n{'='*60}")
    print(f"PENGIRIMAN SELESAI")
    print(f"{'='*60}")
    print(f"  Total player : {len(players)}")
    print(f"  Eligible     : {len(eligible)}")
    if not args.dry_run:
        print(f"  WA berhasil  : {wa_success}")
        print(f"  TG berhasil  : {tg_success}")
    print(f"\n  Log: runtime/logs/bulk_results.csv")
    save_log(results)

    # ── Tampilkan yang gagal ──
    if not args.dry_run:
        failed = [r for r in results if (r["wa_error"] or r["tg_error"])]
        if failed:
            print(f"\n⚠️  Ada {len(failed)} pengiriman dengan error:")
            for r in failed:
                name = r["nama"]
                if r["wa_error"]:
                    print(f"  - {name} (WA): {r['wa_error']}")
                if r["tg_error"]:
                    print(f"  - {name} (TG): {r['tg_error']}")


if __name__ == "__main__":
    asyncio.run(main())
