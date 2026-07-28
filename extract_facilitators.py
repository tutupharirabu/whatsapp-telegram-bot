#!/usr/bin/env python3
"""
Extract data fasilitator dari Arcade Facilitator Daily Report CSV
ke format players.csv (nama, nomor_hp) untuk checker.py / bulk.py.

Taruh file daily report (*.csv) di folder source/ ini, lalu jalankan:

    python source/extract_facilitators.py "Arcade Facilitator Daily Report Jul 25.csv"
    python source/extract_facilitators.py "report.csv" --names "Irfan" "Nafila" -o source/hasil.csv
"""

import argparse
import csv
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Default: cari di folder source/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(SCRIPT_DIR, "source")

# Baca dari .env, fallback ke default
_raw = os.getenv("FASIL_NAMES", "Irfan Zharauri,Nafila Alfirahma")
FASIL_NAMES = [n.strip() for n in _raw.split(",") if n.strip()]


def matches(name: str, targets: list) -> bool:
    """Cek apakah nama peserta mengandung salah satu target."""
    lower = name.lower()
    return any(t.lower() in lower for t in targets)


def extract(report_path: str, output_path: str, targets: list) -> None:
    if not os.path.exists(report_path):
        print(f"File report tidak ditemukan: {report_path}")
        sys.exit(1)

    results = []
    with open(report_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nama = row.get("Nama Peserta", "").strip()
            hp = row.get("Nomor HP Peserta", "").strip()
            if matches(nama, targets):
                results.append({"nama": nama, "nomor_hp": hp})
                print(f"  ✓ {nama} — {hp}")

    if not results:
        print("Tidak ada fasilitator ditemukan.")
        sys.exit(1)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["nama", "nomor_hp"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n{len(results)} fasilitator disimpan ke: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract data fasilitator dari Arcade Daily Report CSV"
    )
    parser.add_argument("report", nargs="?", default=None,
                        help="Nama file daily report di folder source/")
    parser.add_argument("--output", "-o",
                        default=os.path.join(SOURCE_DIR, "fasilitators.csv"),
                        help="Output CSV path (default: source/fasilitators.csv)")
    parser.add_argument("--names", nargs="*", default=FASIL_NAMES,
                        help="Nama fasilitator yang dicari")
    args = parser.parse_args()

    if args.report:
        report_path = os.path.join(SOURCE_DIR, args.report)
    else:
        # Cari otomatis file daily report di source/
        csv_files = [f for f in os.listdir(SOURCE_DIR)
                     if f.endswith(".csv") and "facilitator" in f.lower()]
        if not csv_files:
            print("File daily report tidak ditemukan di source/.")
            print("Taruh file Arcade Facilitator Daily Report di folder source/.")
            print("Atau: python extract_facilitators.py nama_file.csv")
            sys.exit(1)
        report_path = os.path.join(SOURCE_DIR, csv_files[0])
        print(f"Auto-detected: {csv_files[0]}")

    extract(report_path, args.output, args.names)
