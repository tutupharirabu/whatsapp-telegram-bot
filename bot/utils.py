import csv
import json
import re
from pathlib import Path
from typing import Any

_TEMPLATES_JSON = Path(__file__).resolve().parent.parent / "runtime" / "templates.json"

def _load_templates() -> dict[str, str]:
    if _TEMPLATES_JSON.exists():
        try:
            return json.loads(_TEMPLATES_JSON.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}

_DEFAULT_TEMPLATES = {
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
    "join-full": (
        "Halo, {nama}! 👋\n\n"
        "Perkenalkan, saya Irfan Zharauri, fasilitator kamu di "
        "Program Google Skills Arcade Fasilitator 2026 dengan kode fasil GCAF26-ID-9MJ-EP6. 😊\n\n"
        "Biar komunikasi dan koordinasi kita lancar, ada 3 hal yang perlu kamu selesaikan:\n\n"
        "1️⃣ Join grup Telegram koordinasi kita di:\n"
        "👉 https://t.me/+wXiMsFTC-jsyODhl\n\n"
        "2️⃣ Redeem kode akses kamu.\n"
        "⚠️ Kalau belum redeem sampai 7 Agustus 2026, "
        "token kredit kamu akan di-assign ke registrant lain lho!\n\n"
        "3️⃣ Dapetin Lencana Digital GEAR (Gemini Enterprise Agent Ready) di:\n"
        "👉 dicoding.id/Arcade26-GearBadge\n\n"
        "Kalau ada kendala di salah satu langkah di atas, langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "Semangat, sampai jumpa di grup! 🚀"
    ),
    "join-redeem": (
        "Halo, {nama}! 👋\n\n"
        "Perkenalkan, saya Irfan Zharauri, fasilitator kamu di "
        "Program Google Skills Arcade Fasilitator 2026 dengan kode fasil GCAF26-ID-9MJ-EP6. 😊\n\n"
        "Biar komunikasi dan koordinasi kita lancar, ada 2 hal yang perlu kamu selesaikan:\n\n"
        "1️⃣ Join grup Telegram koordinasi kita di:\n"
        "👉 https://t.me/+wXiMsFTC-jsyODhl\n\n"
        "2️⃣ Redeem kode akses kamu.\n"
        "⚠️ Kalau belum redeem sampai 7 Agustus 2026, "
        "token kredit kamu akan di-assign ke registrant lain lho!\n\n"
        "Kalau ada kendala di salah satu langkah di atas, langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "Semangat, sampai jumpa di grup! 🚀"
    ),
    "join-gear": (
        "Halo, {nama}! 👋\n\n"
        "Perkenalkan, saya Irfan Zharauri, fasilitator kamu di "
        "Program Google Skills Arcade Fasilitator 2026 dengan kode fasil GCAF26-ID-9MJ-EP6. 😊\n\n"
        "Biar komunikasi dan koordinasi kita lancar, ada 2 hal yang perlu kamu selesaikan:\n\n"
        "1️⃣ Join grup Telegram koordinasi kita di:\n"
        "👉 https://t.me/+wXiMsFTC-jsyODhl\n\n"
        "2️⃣ Dapetin Lencana Digital GEAR (Gemini Enterprise Agent Ready) di:\n"
        "👉 dicoding.id/Arcade26-GearBadge\n\n"
        "Kalau ada kendala di salah satu langkah di atas, langsung kabari aku atau email ke:\n"
        "📧 arcade@dicoding.com, ya.\n\n"
        "Semangat, sampai jumpa di grup! 🚀"
    ),
}

# Merge default + kustomisasi tersimpan: semua key default (mis. join-full) SELALU ada
# walau templates.json lama belum punya key tersebut; isi kustomisasi tetap menang.
TEMPLATES = {**_DEFAULT_TEMPLATES, **_load_templates()}


def personalize_message(template: str, player: dict, fasil_name: str = "", fasil_kode: str = "") -> str:
    """Ganti placeholder {nama}, {nama_fasil}, {kode_fasil} di template pesan."""
    msg = template.replace("{nama}", player.get("nama", "Player"))
    msg = msg.replace("{nama_fasil}", fasil_name)
    msg = msg.replace("{kode_fasil}", fasil_kode)
    return msg


def normalize_phone(raw: str) -> str:
    """Normalisasi nomor HP ke format internasional tanpa '+'. Nomor asing dibiarkan apa adanya."""
    if not raw:
        return ""
    raw = str(raw).strip()
    explicit = raw.startswith("+")
    num = re.sub(r"[^\d]", "", raw)
    if not explicit:
        if num.startswith("0"):
            num = "62" + num[1:]
        elif num.startswith("8") and 8 <= len(num) <= 13:
            num = "62" + num
    if not 8 <= len(num) <= 15:
        return ""
    return num


COLUMN_ALIASES = {
    "nama": ("Nama Peserta", "nama"),
    "hp": ("Nomor HP Peserta", "nomor_hp"),
    "email": ("Email Peserta", "email"),
    "status_redeem": ("Status Redeem Kode Akses", "status_redeem"),
    "lencana_gear": ("Lencana Digital GEAR yang diraih", "lencana_gear"),
    "milestone": ("Milestone yang diraih", "milestone"),
    "bonus_milestone": ("Bonus Milestone yang diraih", "bonus_milestone"),
    "status_verifikasi_ai_agent": ("Status Verifikasi AI Agent", "status_verifikasi_ai_agent"),
    "jumlah_lencana": ("Jumlah Lencana Keahlian yang diselesaikan", "jumlah_lencana"),
    "jumlah_arcade_game": ("Jumlah Arcade Game yang diselesaikan", "jumlah_arcade_game"),
    "nama_lencana": ("Nama Lencana Keahlian yang diselesaikan", "nama_lencana"),
    "nama_arcade_game": ("Nama Arcade Game yang diselesaikan", "nama_arcade_game"),
}


def get_col(row: dict, key: str) -> str:
    """Ambil nilai kolom dari dict baris CSV via alias nama kolom (COLUMN_ALIASES)."""
    for alias in COLUMN_ALIASES.get(key, ()):
        val = row.get(alias)
        if val:
            return val
    return row.get(key, "")


def read_csv(filepath: str) -> list[dict[str, Any]]:
    """Baca CSV, return list of {nama, nomor_hp, nomor_normalized}."""
    players = []
    for row_dict in read_csv_rows(filepath):
        nama = (get_col(row_dict, "nama") or "").strip()
        hp = (get_col(row_dict, "hp") or "").strip()
        if not hp:
            continue
        players.append({
            "nama": nama,
            "nomor_hp": hp,
            "nomor_normalized": normalize_phone(hp),
        })
    return players


def read_csv_rows(filepath: str) -> list[dict[str, str]]:
    """
    Baca CSV baris-per-baris, tahan format export Google Sheets yang membungkus
    seluruh baris dengan satu lapis quote tambahan (tiap quote internal jadi "").
    csv.DictReader/reader standar hanya membaca 1 kolom raksasa untuk baris seperti itu.
    Return list of dict {header: value}.
    """
    rows: list[dict[str, str]] = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    if not lines:
        return rows

    header = next(csv.reader([lines[0]]), [])
    n_cols = len(header)

    for raw_line in lines[1:]:
        if not raw_line.strip():
            continue
        row = next(csv.reader([raw_line]), [])
        if len(row) != n_cols:
            stripped = raw_line.strip()
            if stripped.startswith('"') and stripped.endswith('"'):
                inner = stripped[1:-1].replace('""', '"')
                row = next(csv.reader([inner]), [])
        if len(row) != n_cols:
            continue
        rows.append(dict(zip(header, row)))
    return rows
