# GCAF 2026 Auto Messenger

Sistem pengiriman pesan otomatis untuk WhatsApp dan Telegram, dibangun untuk menangani bulk messaging dan verifikasi nomor peserta. Proyek ini dipisah menjadi tiga komponen utama: Core Bot/Database (`bot/`), Command-Line Interface (`cli/`), dan Dashboard Web (`gui/`).

## Struktur Direktori

```
whatsapp-telegram-bot/
├── bot/                # Core logic & integrasi platform
│   ├── db.py           # SQLite operations & query (runtime/gcaf.db)
│   ├── telegram_bot.py # Telethon/Bot API untuk Telegram
│   ├── whatsapp_bot.py # Selenium bot untuk WhatsApp Web
│   └── utils.py        # Helper functions (normalize_phone, baca CSV)
│
├── cli/                # Command-Line Tools
│   ├── bulk.py         # Kirim pesan massal (WA & TG)
│   ├── checker.py      # Verifikasi nomor WA & akun TG
│   ├── check_reminders.py
│   ├── extract_facilitators.py
│   └── main.py         # Entry point CLI lama (opsional)
│
├── gui/                # Dashboard Web (FastAPI + HTMX)
│   ├── app.py          # FastAPI server routes
│   ├── static/         # CSS & JS assets
│   └── templates/      # Jinja2 + HTMX HTML templates
│
└── runtime/            # Data otomatis (Git ignored)
    ├── gcaf.db         # Database SQLite lokal
    ├── wa_profile/     # Session Chrome/Selenium WhatsApp Web
    └── tg_checker_session # Session Telethon Telegram
```

## Persyaratan Sistem

- **Python 3.9+** (Disarankan environment `conda` / `venv`)
- **Google Chrome** & **ChromeDriver** (Harus cocok versinya)
- Akun Telegram (API ID & Hash)
- Akun WhatsApp (Login via QR WA Web)

### Instalasi

1. Clone repositori:
   ```bash
   git clone <url-repo> whatsapp-telegram-bot
   cd whatsapp-telegram-bot
   ```

2. Buat dan aktifkan virtual environment, lalu install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Setup environment variables:
   Copy `.env.example` ke `.env` dan lengkapi datanya:
   ```env
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=abcdef123456
   TELEGRAM_PHONE=+628123456789
   TELEGRAM_BOT_TOKEN=123:ABC...
   ```

## Penggunaan

### 1. Memulai Dashboard (GUI)

Aplikasi GUI memudahkan pemantauan dan pengiriman manual melalui antarmuka web.

```bash
python gui/app.py
```
Akses di browser: `http://localhost:8000`

> **Note:** Pada jalankan pertama kali, buka tab WhatsApp di browser Selenium yang muncul dan scan QR code.

### 2. Pengecekan Nomor Massal (CLI)

Gunakan `cli/checker.py` untuk memverifikasi file CSV peserta (apakah nomor terdaftar WA & TG):

```bash
python cli/checker.py
```

### 3. Pengiriman Pesan Massal (CLI)

Gunakan `cli/bulk.py` untuk blast pesan ke semua kontak atau kontak tertentu berdasarkan CSV.

```bash
python cli/bulk.py --file data_peserta.csv
```

## Troubleshooting & Tips

- **Session WhatsApp Hilang:** Jika WA terus-menerus minta login QR, pastikan direktori `runtime/wa_profile/` tidak terhapus dan memiliki permission yang benar.
- **`TypeError: unhashable type: 'dict'` di Dashboard:** Ini masalah kompabilitas Jinja2Templates di FastAPI/Starlette terbaru. Pastikan call route di `gui/app.py` menggunakan signature `TemplateResponse(request, "name.html", context)`.
- **Error CSV DictReader:** Pastikan file export dari Google Sheets format kolomnya konsisten (contoh: tidak ada double quote `"..."` ekstra yang tidak di-*escape*).
