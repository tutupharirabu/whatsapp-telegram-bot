# WhatsApp & Telegram Auto Messenger

Script Python untuk mengirim pesan otomatis ke WhatsApp dan Telegram via CLI.
Mendukung pengiriman ke satu target (`main.py`) maupun massal dari CSV (`bulk.py`).
Dirancang untuk koordinasi GCAF 2026.

## Fitur

- Kirim pesan ke nomor WhatsApp & Telegram
- **Cek otomatis** apakah nomor HP terdaftar di WhatsApp & Telegram
- **Bulk messaging** dari file CSV — cocok untuk broadcast ke banyak player
- **Template siap pakai** — formal, kasual, dan reminder (redeem kode akses, GEAR badge)
- **Scan reminder otomatis** — deteksi player yang belum redeem atau belum dapat GEAR badge
- **Extract fasilitator** dari Arcade Daily Report CSV
- **Auto-detect OS** — AppleScript di macOS, pyautogui di Windows/Linux
- **Anti-spam** — jeda otomatis antar pengiriman

## Prasyarat

- Python 3.8+
- **Google Chrome** terinstal (untuk cek WA via Selenium)
- WhatsApp Web sudah login di browser (untuk kirim WA via pywhatkit)
- **Telegram User Account** — buat cek & kirim pesan Telegram (dari [my.telegram.org](https://my.telegram.org)), wajib user biasa bukan bot

## Instalasi

```bash
cd whatsapp-telegram-bot
pip install -r requirements.txt
cp .env.example .env   # lalu edit isinya — semua nilai di .env.example adalah contoh/dummy
```

Edit file `.env`:

| Variable | Untuk | Cara Dapat |
|----------|-------|-----------|
| `TELEGRAM_API_ID` | Cek & kirim TG (Telethon) | [my.telegram.org](https://my.telegram.org) → API Development |
| `TELEGRAM_API_HASH` | Cek & kirim TG (Telethon) | [my.telegram.org](https://my.telegram.org) → API Development |
| `TELEGRAM_PHONE` | Login Telethon | Nomor HP user Telegram kamu (bukan bot!) |
| `WA_HEADLESS` | Mode background (opsional) | Set `1` untuk tanpa browser window |
| `WA_BROWSER_APP` | Browser untuk WA automation | Nama aplikasi browser (default: `Arc` di macOS, kosong di Windows) |

---

## Single Target (`main.py`)

```bash
# Kirim ke WhatsApp
python main.py --wa 6281234567890 -m "Halo, reminder!"

# Kirim ke Telegram
python main.py --tg @username -m "Halo dari bot!"

# Kirim ke WA + Telegram
python main.py --wa 6281234567890 --tg @username -m "Broadcast!"
```

---

## Bulk Messaging (`bulk.py`)

Ada dua jalur, tergantung datamu:

### Jalur A: Sudah punya CSV format `nama,nomor_hp`

Kalau kamu sudah punya CSV dengan format yang benar, langsung ke langkah **Cek ketersediaan** di bawah. Lihat `source/example.csv` sebagai referensi (berisi data real).

### Jalur B: Data masih dalam Arcade Daily Report CSV

Kalau datamu masih format daily report (banyak kolom), extract dulu:

**B1. Taruh daily report di `source/`**

Download dari Google Sheet, taruh file di folder `source/`:

```
source/
├── example.csv                                     ← contoh output final (referensi)
├── Arcade Facilitator Daily Report Jul 25.csv      ← taruh daily report di sini
├── fasilitators.csv                                ← hasil extract (gitignored)
└── reminders.csv                                   ← hasil scan reminder (gitignored)
```

**B2. Jalankan extract**

```bash
# Auto-detect file daily report di source/
python extract_facilitators.py

# Atau sebutkan nama file
python extract_facilitators.py "Arcade Facilitator Daily Report Jul 25.csv"

# Custom nama yang dicari & output
python extract_facilitators.py --names "Irfan" "Nafila" -o source/hasil.csv
```

Output: `source/fasilitators.csv` dengan format `nama,nomor_hp`.

### Cek ketersediaan

```bash
# Cek siapa yang punya WA & Telegram
python checker.py source/example.csv

# Simpan hasil cek (biar bisa dipakai ulang)
python checker.py source/example.csv -o hasil_cek.json
```

### Kirim massal

**Dengan template bawaan:**

```bash
# Mode formal
python bulk.py source/example.csv --mode formal

# Mode kasual, WhatsApp only
python bulk.py source/example.csv --mode kasual --wa-only

# Dry-run dulu sebelum kirim beneran
python bulk.py source/example.csv --mode formal --dry-run
```

**Dengan pesan custom:**

```bash
# Placeholder: {nama}, {nama_fasil}, {kode_fasil}
python bulk.py source/example.csv -m "Halo {nama}!" --wa-only

# Dengan nama & kode fasil
python bulk.py source/example.csv -m "Dari {nama_fasil} ({kode_fasil})" \
    --fasil-name "Budi" --fasil-kode "ABC123" --wa-only
```

**Opsi tambahan:**

```bash
# Hanya WhatsApp / hanya Telegram
python bulk.py source/example.csv --mode kasual --wa-only
python bulk.py source/example.csv --mode kasual --tg-only

# Jeda lebih cepat (3 detik)
python bulk.py source/example.csv --mode formal --delay 3

# Pakai hasil cek sebelumnya (skip cek ulang)
python bulk.py source/example.csv --mode formal --check-file hasil_cek.json
```

### Kirim Reminder

Untuk player yang belum redeem atau belum dapat GEAR badge:

```bash
# 1. Scan daily report untuk reminder
python check_reminders.py

# 2. Kirim reminder redeem saja
python bulk.py source/reminders.csv --mode remind-redeem --wa-only

# 3. Kirim reminder GEAR saja
python bulk.py source/reminders.csv --mode remind-gear --wa-only

# 4. Atau pakai mode remind-both untuk keduanya
python bulk.py source/reminders.csv --mode remind-both --wa-only
```

### Alur Lengkap

```
Jalur A (sudah punya CSV):
  source/example.csv → checker.py → bulk.py → runtime/logs/bulk_results.csv

Jalur B (dari daily report):
  source/Arcade Facilitator Daily Report Jul 25.csv
    → extract_facilitators.py → source/fasilitators.csv → checker.py → bulk.py

Jalur C (reminder):
  source/Arcade Facilitator Daily Report Jul 25.csv
    → check_reminders.py → source/reminders.csv → bulk.py --mode remind-redeem
```

---

## Catatan Penting

- **WhatsApp**: Browser harus login ke WhatsApp Web. Nomor akan dinormalisasi otomatis.
- **WA Automation**: Auto-detect OS. macOS pakai AppleScript (perlu izin **Accessibility** di System Settings), Windows/Linux pakai `pyautogui`. Browser bisa dikustom via `WA_BROWSER_APP` di `.env`.
- **WA Check (Selenium)**: Saat pertama kali, WhatsApp Web akan minta scan QR. Browser akan terbuka, kamu scan, lalu session disimpan di `runtime/wa_chrome_profile/`. Setelah itu bisa pakai mode headless (`WA_HEADLESS=1` di `.env`).
- **Telegram Cek**: WAJIB pakai **user account Telegram** (bukan bot!). Bot tidak bisa cek nomor. Set `TELEGRAM_PHONE` di `.env` agar tidak ditanya-tanya lagi. Risk flag jika terlalu agresif, batasi ~100 cek/hari.
- **Jeda**: Default 5 detik antar pemain. Bisa dikurangi tapi jangan terlalu cepat (risiko spam detection).
- **Template**: Nama & kode fasil sudah hardcoded di template `formal`/`kasual`. Untuk custom, pakai `-m` + `--fasil-name` + `--fasil-kode`.
- **Log**: Semua log & session disimpan di folder `runtime/`. Folder ini di-gitignore.

## Struktur File

```
├── main.py                            CLI single-target
├── bulk.py                            Bulk messenger dari CSV
├── checker.py                         Cek WA & TG availability
├── extract_facilitators.py            Extract data dari daily report
├── check_reminders.py                 Scan daily report untuk reminder
├── telegram_bot.py                    Modul pengirim Telegram
├── whatsapp_bot.py                    Modul pengirim WhatsApp
├── requirements.txt                   Dependencies
├── .env.example                       Template config
├── source/
│   ├── example.csv                    Contoh data player (nama,nomor_hp)
│   ├── Arcade Facilitator Daily Report Jul 25.csv   Taruh daily report di sini
│   ├── fasilitators.csv               Output extract (gitignored)
│   └── reminders.csv                  Output reminder (gitignored)
└── runtime/
    ├── wa_chrome_profile/              Chrome session WA (gitignored)
    ├── checker_session.session         Telethon session (gitignored)
    └── logs/
        └── bulk_results.csv           Log hasil pengiriman (gitignored)
```
