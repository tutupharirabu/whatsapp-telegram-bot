import csv
from typing import Dict, List


def normalize_phone(raw: str) -> str:
    """Normalisasi nomor HP ke format internasional tanpa '+'."""
    if not raw:
        return ""
    num = str(raw).replace("+", "").replace(" ", "").replace("-", "").strip()
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
