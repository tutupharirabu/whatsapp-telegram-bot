#!/usr/bin/env python3
"""
Send WhatsApp & Telegram Messages - Kirim pesan ke GCAF 2026 players.

Alur:
1. Baca CSV source/
2. Cek WA & TG availability (via checker.py)
3. Kirim pesan ke platform yang available
4. Jeda antar pengiriman (anti-spam)

Usage:
    python cli/send.py source/players.csv -m "Halo GCAF 2026!"
    python cli/send.py source/players.csv -m "..." --wa-only
    python cli/send.py source/players.csv -m "..." --tg-only
    python cli/send.py source/players.csv -m "..." --delay 3
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot.db import get_sent_set, insert_send_log, msg_fingerprint
from bot.telegram_bot import send_telegram_user
from bot.utils import TEMPLATES, normalize_phone, personalize_message, read_csv
from bot.whatsapp_bot import close_wa_driver, send_whatsapp_message
from cli.checker import check_all

load_dotenv()

FASIL_PHONE = normalize_phone(os.getenv("TELEGRAM_PHONE", ""))

LOGS_DIR = Path(__file__).resolve().parent.parent / "runtime" / "logs"


def _load_json(path: str) -> dict:
    """Load JSON file (sync; dijalankan via asyncio.to_thread)."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


async def send_to_player(
    player: dict,
    message: str,
    wa_only: bool = False,
    tg_only: bool = False,
    wait_time: int = 15,
    fasil_name: str = "",
    fasil_kode: str = "",
    skip_wa: bool = False,
    skip_tg: bool = False,
) -> dict[str, Any]:
    """
    Kirim pesan ke satu player via platform yang available.
    Return dict status pengiriman.
    """
    name = player["nama"]
    num = player["nomor_normalized"]
    msg = personalize_message(message, player, fasil_name, fasil_kode)
    result: dict[str, Any] = {
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
        if skip_wa:
            result["wa_error"] = "skip:duplikat"
        else:
            try:
                wa_result = send_whatsapp_message(num, msg, wait_time=wait_time)
                if wa_result["status"] == "success":
                    result["wa_sent"] = True
                else:
                    result["wa_error"] = wa_result.get("error", "Unknown")
            except (ValueError, OSError, RuntimeError) as e:
                result["wa_error"] = str(e)

    # ── Telegram ──
    if not wa_only and player["tg_available"] and player.get("tg_user_id"):
        if skip_tg:
            result["tg_error"] = "skip:duplikat"
        else:
            try:
                tg_result = await send_telegram_user(int(player["tg_user_id"]), msg)
                if tg_result.get("message_id"):
                    result["tg_sent"] = True
                else:
                    result["tg_error"] = "No message_id returned"
            except (ValueError, OSError, RuntimeError) as e:
                result["tg_error"] = str(e)

    return result


def save_log(results: list[dict[str, Any]], filepath: str) -> None:
    """Simpan log pengiriman ke CSV (append; header hanya kalau file baru)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    fieldnames = [
        "nama", "nomor_hp",
        "wa_available", "tg_available",
        "wa_sent", "tg_sent",
        "wa_error", "tg_error",
        "mode", "msg_hash", "batch_id",
        "timestamp",
    ]
    is_new = not os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerows(results)
    print(f"\nLog disimpan ke: {filepath}")


def print_progress(current: int, total: int, player: dict[str, Any], result: dict[str, Any]) -> None:
    """Print progress pengiriman per player."""
    name = player["nama"]
    wa_status = "WA✅" if result["wa_sent"] else ("WA❌" if player["wa_available"] else "WA—")
    tg_status = "TG✅" if result["tg_sent"] else ("TG❌" if player["tg_available"] else "TG—")
    print(f"  [{current}/{total}] {name:<25} {wa_status}  {tg_status}")


async def main():
    parser = argparse.ArgumentParser(
        description="Send WhatsApp & Telegram Messages - Kirim pesan ke GCAF 2026 players",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python cli/send.py source/example.csv --mode formal
  python cli/send.py source/example.csv --mode kasual --wa-only
  python cli/send.py source/reminders.csv --mode remind-redeem --wa-only
  python cli/send.py source/reminders.csv --mode remind-both --wa-only
  python cli/send.py source/peserta.csv --mode join-full --wa-only
  python cli/send.py source/peserta.csv --mode join-redeem --wa-only
  python cli/send.py source/peserta.csv --mode join-gear --wa-only
  python cli/send.py source/example.csv -m "Halo {nama}!" --wa-only
  python cli/send.py source/example.csv --mode formal --delay 3 --dry-run
        """,
    )
    parser.add_argument("csv", help="Path ke file CSV (kolom: nama, nomor_hp)")
    parser.add_argument("-m", "--message", help="Isi pesan custom (gunakan {nama}, {nama_fasil}, {kode_fasil} untuk placeholder)")
    parser.add_argument("--mode", choices=["formal", "kasual", "remind-redeem", "remind-gear", "remind-both", "join-redeem", "join-gear", "join-full"], help="Gunakan template bawaan")
    parser.add_argument("--fasil-name", default="", help="Nama fasilitator")
    parser.add_argument("--fasil-kode", default="", help="Kode fasilitator")
    parser.add_argument("--wa-only", action="store_true", help="Hanya kirim WhatsApp")
    parser.add_argument("--tg-only", action="store_true", help="Hanya kirim Telegram")
    parser.add_argument("--delay", type=int, default=5, help="Jeda antar pengiriman dalam detik (default: 5)")
    parser.add_argument("--wait-wa", type=int, default=15, help="Wait time WA Web loading (default: 15)")
    parser.add_argument("--dry-run", action="store_true", help="Hanya cek & tampilkan, tidak kirim")
    parser.add_argument("--skip-check", action="store_true", help="Gunakan hasil cek sebelumnya (dari JSON)")
    parser.add_argument("--check-file", type=str, help="File JSON hasil checker.py sebelumnya")
    parser.add_argument("--force", action="store_true", help="Lewati dedup (tetap catat log)")

    args = parser.parse_args()

    if not args.message and not args.mode:
        parser.error("Harus pakai --message (-m) atau --mode (formal/kasual/remind-*/join-full)")

    # Pastikan skema DB ada (tabel send_logs dll) sebelum dipakai dedup & logging
    from bot import db as _db
    _db.init_db()

    # ── Tentukan pesan ──
    if args.mode:
        message = TEMPLATES[args.mode]
    else:
        message = args.message

    msg_hash = msg_fingerprint(message)
    batch_id = uuid.uuid4().hex[:8]
    mode_log = args.mode or "custom"

    if not os.path.exists(args.csv):
        print(f"File tidak ditemukan: {args.csv}")
        sys.exit(1)

    # ── Load player data ──
    if args.check_file:
        # Format check_all: {nomor_normalized: {"wa": bool, "tg": bool|user_id}}
        check_results = await asyncio.to_thread(_load_json, args.check_file)
        players = read_csv(args.csv)
        if not players:
            print("Tidak ada data player di CSV")
            sys.exit(1)
        for p in players:
            res = check_results.get(p["nomor_normalized"], {})
            p["wa_available"] = res.get("wa", False)
            tg_val = res.get("tg")
            p["tg_available"] = tg_val is not None and tg_val is not False
            p["tg_user_id"] = tg_val if (tg_val and not isinstance(tg_val, bool)) else None
        print(f"Loaded hasil cek {len(players)} players dari {args.check_file} (skip cek)")
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
            check_results = await check_all(players)
            for p in players:
                num = p["nomor_normalized"]
                res = check_results.get(num, {})
                p["wa_available"] = res.get("wa", False)
                tg_val = res.get("tg")
                p["tg_available"] = tg_val is not None and tg_val is not False
                p["tg_user_id"] = tg_val if (tg_val and not isinstance(tg_val, bool)) else None
            print("\nCek selesai. Memulai pengiriman...")

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
        print("  🔍 DRY RUN — tidak benar-benar kirim")
    print(f"{'='*60}")

    # ── Dedup: jangan kirim ulang yang sudah sukses untuk kampanye (msg_hash) ini ──
    sent_wa = set()
    sent_tg = set()
    if not args.force:
        sent_wa = get_sent_set("wa", msg_hash)
        sent_tg = get_sent_set("tg", msg_hash)
        if sent_wa or sent_tg:
            print(f"  Dedup: {len(sent_wa)} sudah terkirim WA, {len(sent_tg)} sudah terkirim TG (msg_hash={msg_hash})")

    # ── Kirim ke setiap player ──
    results = []
    total = len(eligible)
    wa_success = 0
    tg_success = 0
    skipped_duplicate = 0

    try:
        for i, player in enumerate(eligible, 1):
            name = player["nama"]
            num = player.get("nomor_normalized", "")

            skip_wa = num in sent_wa
            skip_tg = num in sent_tg

            if args.dry_run:
                result: dict[str, Any] = {
                    "nama": name,
                    "nomor_hp": player["nomor_hp"],
                    "wa_available": player["wa_available"],
                    "tg_available": player["tg_available"],
                    "wa_sent": False,
                    "tg_sent": False,
                    "wa_error": None,
                    "tg_error": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
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
                    skip_wa=skip_wa,
                    skip_tg=skip_tg,
                )
                result["timestamp"] = datetime.now(timezone.utc).isoformat()
                result["mode"] = mode_log
                result["msg_hash"] = msg_hash
                result["batch_id"] = batch_id

                if result["wa_sent"]:
                    wa_success += 1
                if result["tg_sent"]:
                    tg_success += 1

                insert_send_log(
                    {
                        "nama": result["nama"],
                        "nomor_hp": result["nomor_hp"],
                        "wa_available": result["wa_available"],
                        "tg_available": result["tg_available"],
                        "wa_sent": result["wa_sent"],
                        "tg_sent": result["tg_sent"],
                        "wa_error": result["wa_error"],
                        "tg_error": result["tg_error"],
                        "mode": mode_log,
                        "msg_hash": msg_hash,
                        "batch_id": batch_id,
                        "timestamp": result["timestamp"],
                    },
                    batch_id,
                )

            if skip_wa or skip_tg:
                skipped_duplicate += 1

            results.append(result)
            print_progress(i, total, player, result)

            # ── Jeda antar pemain (anti-spam) ──
            if i < total and not args.dry_run:
                await asyncio.sleep(args.delay)
    finally:
        close_wa_driver()

    # ── Ringkasan ──
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    if args.dry_run:
        log_path = LOGS_DIR / f"bulk_results_dryrun_{ts}.csv"
    else:
        log_path = LOGS_DIR / f"bulk_results_{ts}.csv"

    print(f"\n{'='*60}")
    print("PENGIRIMAN SELESAI")
    print(f"{'='*60}")
    print(f"  Total player : {len(players)}")
    print(f"  Eligible     : {len(eligible)}")
    if not args.dry_run:
        print(f"  WA berhasil  : {wa_success}")
        print(f"  TG berhasil  : {tg_success}")
    if skipped_duplicate:
        print(f"  ⏭ Skip duplikat: {skipped_duplicate}")
    print(f"\n  Log: {log_path}")
    save_log(results, str(log_path))

    # ── Tampilkan yang gagal (skip:… bukan error nyata) ──
    if not args.dry_run:
        failed = [
            r for r in results
            if (r["wa_error"] and not str(r["wa_error"]).startswith("skip:"))
            or (r["tg_error"] and not str(r["tg_error"]).startswith("skip:"))
        ]
        if failed:
            print(f"\n⚠️  Ada {len(failed)} pengiriman dengan error:")
            for r in failed:
                name = r["nama"]
                if r["wa_error"] and not str(r["wa_error"]).startswith("skip:"):
                    print(f"  - {name} (WA): {r['wa_error']}")
                if r["tg_error"] and not str(r["tg_error"]).startswith("skip:"):
                    print(f"  - {name} (TG): {r['tg_error']}")


if __name__ == "__main__":
    asyncio.run(main())
