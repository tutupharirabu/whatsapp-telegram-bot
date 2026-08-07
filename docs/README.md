# Wiki GCAF Auto Messenger

Halaman ini adalah sumber dokumentasi untuk repositori **whatsapp-telegram-bot** (GCAF 2026 Auto Messenger) — sistem pengiriman pesan otomatis untuk WhatsApp dan Telegram, dibangun untuk menangani bulk messaging dan verifikasi nomor peserta program Google Skills Arcade Fasilitator 2026.

Dokumentasi ini berisi detail teknis yang tidak tercakup di `README.md` repositori (ringkasan dan panduan penggunaan umum ada di sana). Setiap halaman ditulis berdasarkan kode yang sebenarnya ada di repositori.

## Ringkasan Proyek

Proyek terbagi menjadi tiga komponen utama:

| Komponen | Lokasi | Fungsi |
|---|---|---|
| Core Bot / Database | `bot/` | Logika inti: akses SQLite (`db.py`), integrasi WhatsApp via Selenium (`whatsapp_bot.py`), integrasi Telegram via Telethon/Bot API (`telegram_bot.py`), helper dan template pesan (`utils.py`) |
| Command-Line Interface | `cli/` | Alat baris perintah: pengiriman massal (`send.py`), verifikasi nomor (`checker.py`), skrip pendukung reminder & ekstraksi fasilitator |
| Dashboard Web (GUI) | `gui/` | Server FastAPI + HTMX: dashboard, upload laporan harian, daftar peserta, pengiriman manual, manajemen template, log, dan widget pengecekan nomor |

Data runtime (database SQLite `gcaf.db`, session Telegram, profil Chrome WhatsApp Web, status pengecekan) disimpan di `runtime/` yang di-*gitignore*.

## Fitur Utama

- **Dashboard web** (FastAPI + Jinja2 + HTMX, Tailwind CSS) dengan statistik peserta, log terbaru, dan widget status pengecekan.
- **Upload laporan harian CSV** — import data peserta dengan *onboarding flow* bila belum ada peserta; support nama kolom ber-alias dan format export Google Sheets.
- **Daftar peserta** dengan pencarian, pagination, dan partial HTMX; status WA/TG per peserta beserta kolom laporan (redeem, GEAR, milestone, verifikasi AI Agent).
- **Toggle status join grup Telegram** per peserta (`/players/toggle-tg/{nomor}`).
- **Pengecekan nomor massal di latar belakang** — worker `multiprocessing.Process` terpisah menjalankan cek WhatsApp (Selenium) + Telegram (Telethon), dengan protokol status file (`runtime/check_status.json`), deteksi worker mati/stale, dan lock berbasis `flock`.
- **Pengiriman pesan instan** per peserta: WhatsApp via Selenium (`send_whatsapp_instant`) dan Telegram via Telethon (`send_telegram_user`).
- **Template pesan** yang dapat diedit dari web, dipersist ke `runtime/templates.json`, dan di-hot-reload tanpa restart server.
- **Log pengiriman** (halaman `/logs` + preview di dashboard).
- **Keamanan**: token dashboard (Bearer header / cookie / query), CSRF origin check, rate limiting per IP pada endpoint kirim, dan bind lokal `127.0.0.1` bila token tidak diset.

## Persyaratan Sistem

- Python 3.9+ (venv disarankan)
- Google Chrome + ChromeDriver (dikelola otomatis oleh `webdriver-manager`)
- Akun Telegram (API ID & API hash dari my.telegram.org)
- Akun WhatsApp (login via QR WhatsApp Web; session disimpan di `runtime/wa_chrome_profile/`)

## Daftar Halaman Wiki

| Halaman | Isi |
|---|---|
| [Arsitektur](./ARCHITECTURE.md) | Komponen sistem, alur data (upload → import → worker cek → DB → dashboard), model proses, rantai middleware |
| [Setup & Menjalankan](./SETUP.md) | Virtual environment, instalasi dependensi, konfigurasi `.env`, menjalankan GUI & CLI, masalah umum |
| [Referensi HTTP API](./API.md) | Semua route di `gui/app.py`: method, path, parameter, tipe respons, auth, rate limit |
| [Model Data](./DATA_MODEL.md) | Skema tabel SQLite, fungsi kunci `bot/db.py`, alur import laporan harian |
| [Pipeline Pengecekan Nomor](./CHECK_PIPELINE.md) | Alur lengkap check: lock → spawn worker → batch WA → batch TG → upsert → protokol status file, statuses, deteksi stale, perilaku stop |
| [Model Keamanan](./SECURITY.md) | Token dashboard, CSRF, rate limiting, bind lokal, CodeQL & Dependabot |

## Struktur Direktori

```
whatsapp-telegram-bot/
├── bot/                # Core logic & integrasi platform
│   ├── db.py           # SQLite operations & query (runtime/gcaf.db)
│   ├── telegram_bot.py # Telethon/Bot API untuk Telegram
│   ├── whatsapp_bot.py # Selenium bot untuk WhatsApp Web
│   └── utils.py        # Helper (normalize_phone, baca CSV, template pesan)
│
├── cli/                # Command-Line Tools
│   ├── send.py         # Kirim pesan massal (WA & TG)
│   ├── checker.py      # Verifikasi nomor WA & akun TG
│   ├── check_reminders.py
│   ├── extract_facilitators.py
│   └── main.py         # Entry point CLI lama (opsional)
│
├── gui/                # Dashboard Web (FastAPI + HTMX)
│   ├── app.py          # FastAPI server routes
│   ├── checker_async.py# Wrapper check: worker multiprocessing + status file
│   ├── static/         # CSS & JS assets (tokens.css, vendor/)
│   └── templates/      # Jinja2 + HTMX HTML templates
│
├── scripts/            # Utilitas ops
│   └── backup_runtime.sh  # Backup DB + session + profil WA
├── .github/            # CI & keamanan
│   ├── workflows/codeql.yml
│   ├── codeql/codeql-config.yml
│   └── dependabot.yml
├── .env.example        # Contoh konfigurasi environment
└── runtime/            # Data otomatis (Git ignored)
    ├── gcaf.db         # Database SQLite lokal
    ├── check_status.json   # Status worker pengecekan (protokol)
    ├── check.lock          # flock start-lock pengecekan
    ├── templates.json      # Kustomisasi template pesan
    ├── wa_chrome_profile/  # Session Chrome/Selenium WhatsApp Web
    ├── wa_profile.lock     # flock lock profil WA (satu proses saja)
    ├── tg_checker_session  # Session Telethon (pengiriman TG)
    └── checker_session     # Session Telethon (checker nomor, terpisah)
```

## Halaman Cepat

- Mulai dari [Setup & Menjalankan](./SETUP.md).
- Pahami alur pengecekan nomor di [Pipeline Pengecekan Nomor](./CHECK_PIPELINE.md).
- Lihat semua endpoint HTTP di [Referensi HTTP API](./API.md).
- Pelajari model keamanan sebelum membuka dashboard ke jaringan di [Model Keamanan](./SECURITY.md).

---

## Saran Sidebar Wiki GitHub

GitHub Wiki menggunakan file `_Sidebar.md` untuk menampilkan navigasi. Berikut isi `_Sidebar.md` yang disarankan (mengacu ke nama halaman wiki yang akan dibuat dari file-file di folder `docs/` ini):

```markdown
**GCAF Auto Messenger**

- [Home](Home)
- [Arsitektur](ARCHITECTURE)
- [Setup & Menjalankan](SETUP)
- [Referensi HTTP API](API)
- [Model Data](DATA_MODEL)
- [Pipeline Pengecekan Nomor](CHECK_PIPELINE)
- [Model Keamanan](SECURITY)
```
