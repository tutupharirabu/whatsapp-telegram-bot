#!/usr/bin/env python3
"""
Scan Arcade Daily Report untuk pemain yang butuh reminder:
- Status Redeem Kode Akses = "No" → reminder redeem
- Lencana Digital GEAR = "No Badge" → reminder badge

Output: CSV dengan format nama,nomor_hp,reminder_type
Lalu bisa dipakai bulk.py untuk kirim pesan pengingat.

Usage:
    python source/check_reminders.py
    python source/check_reminders.py "report.csv"
"""

import argparse
import csv
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(SCRIPT_DIR, "source")


def scan_reminders(report_path: str) -> list:
    """Scan daily report, return list pemain yang butuh reminder."""
    if not os.path.exists(report_path):
        print(f"File report tidak ditemukan: {report_path}")
        sys.exit(1)

    reminders = []
    total = 0
    redeem_no = 0
    gear_no = 0

    with open(report_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nama = row.get("Nama Peserta", "").strip()
            hp = row.get("Nomor HP Peserta", "").strip()
            redeem = row.get("Status Redeem Kode Akses", "").strip()
            gear = row.get("Lencana Digital GEAR yang diraih", "").strip()

            if not hp:
                continue
            total += 1

            reminder_types = []

            if redeem.lower() == "no":
                reminder_types.append("redeem")
                redeem_no += 1

            gear_lower = gear.lower()
            if gear_lower in ("no badge", "", "none"):
                reminder_types.append("gear")
                gear_no += 1

            if reminder_types:
                reminders.append({
                    "nama": nama,
                    "nomor_hp": hp,
                    "reminder_type": ",".join(reminder_types),
                })

    print(f"Total pemain       : {total}")
    print(f"Belum redeem       : {redeem_no}")
    print(f"Belum dapat GEAR   : {gear_no}")
    print(f"Butuh reminder     : {len(reminders)}")

    return reminders


def save_reminders(reminders: list, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["nama", "nomor_hp", "reminder_type"])
        writer.writeheader()
        writer.writerows(reminders)
    print(f"\nReminder list disimpan ke: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan daily report untuk pemain yang butuh reminder redeem/GEAR"
    )
    parser.add_argument("report", nargs="?", default=None,
                        help="Nama file daily report di folder source/")
    parser.add_argument("--output", "-o",
                        default=os.path.join(SOURCE_DIR, "reminders.csv"),
                        help="Output CSV path (default: source/reminders.csv)")
    args = parser.parse_args()

    if args.report:
        report_path = os.path.join(SOURCE_DIR, args.report)
    else:
        csv_files = [f for f in os.listdir(SOURCE_DIR)
                     if f.endswith(".csv") and "facilitator" in f.lower()]
        if not csv_files:
            print("File daily report tidak ditemukan di source/.")
            print("Taruh file Arcade Facilitator Daily Report di folder source/.")
            sys.exit(1)
        report_path = os.path.join(SOURCE_DIR, csv_files[0])
        print(f"Auto-detected: {csv_files[0]}\n")

    reminders = scan_reminders(report_path)
    save_reminders(reminders, args.output)
