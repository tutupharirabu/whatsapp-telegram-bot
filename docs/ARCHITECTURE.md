# Arsitektur

Halaman ini menjelaskan arsitektur tingkat tinggi sistem **GCAF Auto Messenger**: komponen, alur data, model proses, dan rantai middleware pada server GUI.

Baca juga: [Setup](./SETUP.md) · [Referensi HTTP API](./API.md) · [Model Data](./DATA_MODEL.md) · [Pipeline Pengecekan](./CHECK_PIPELINE.md) · [Model Keamanan](./SECURITY.md).

## Komponen

```
┌────────────────────────────────────────────────────────────────────────┐
│                         whatsapp-telegram-bot/                         │
│                                                                        │
│  bot/  (core library — dipakai GUI & CLI)                              │
│   ├── db.py              SQLite (runtime/gcaf.db), semua persistent data
│   ├── whatsapp_bot.py    Selenium + Chrome, satu driver persisten
│   ├── telegram_bot.py    Telethon (user account) + Bot API (python-telegram-bot)
│   └── utils.py           normalize_phone, baca CSV, template pesan
│                                                                        │
│  cli/  (alat baris perintah)                                           │
│   ├── checker.py         check_whatsapp_batch / check_telegram_batch / check_all
│   ├── send.py            bulk send (WA & TG) dengan dedup + logging
│   ├── check_reminders.py scan report → daftar reminder (redeem/GEAR)
│   ├── extract_facilitators.py  ekstrak data fasilitator dari report CSV
│   └── main.py            CLI lama: kirim ke satu nomor (opsional)
│                                                                        │
│  gui/  (dashboard web FastAPI)                                         │
│   ├── app.py             routes + middleware + render Jinja2
│   ├── checker_async.py   spawn worker multiprocessing + protokol status
│   ├── templates/         Jinja2 + HTMX (dashboard, players, templates, logs)
│   └── static/            tokens.css + vendor/ (htmx.js, tailwindcss.js)
│                                                                        │
│  scripts/  backup_runtime.sh — backup DB + session + profil WA          │
│  source/   data CSV (di-gitignore)                                     │
│  runtime/  data otomatis (di-gitignore): gcaf.db, session, profil,     │
│            check_status.json, check.lock, templates.json               │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. `bot/` — Core library

Paket yang diimpor oleh GUI dan CLI. `sys.path.insert(0, <repo-root>)` di `gui/app.py`, `gui/checker_async.py`, dan setiap skrip `cli/` memastikan paket `bot` dan `cli` bisa diimpor dari mana pun proses dijalankan.

- **`bot/db.py`** — Semua akses SQLite lewat satu koneksi global (`_conn`, `threading.RLock`, `check_same_thread=False`, WAL, `row_factory = sqlite3.Row`). Inisialisasi skema + migrasi idempotent di `init_db()` (dipanggil saat startup FastAPI via `lifespan` dan oleh `cli/send.py`).
- **`bot/whatsapp_bot.py`** — Selenium + Chrome dengan satu driver persisten (`_driver` global). Profil login disimpan di `runtime/wa_chrome_profile/` dan dikunci dengan `flock` (`runtime/wa_profile.lock`) agar tidak dipakai dua proses sekaligus. `send_whatsapp_instant` adalah alias dari `send_whatsapp_message`.
- **`bot/telegram_bot.py`** — Dua jalur kirim Telegram: `send_telegram_message` (Bot API, butuh `TELEGRAM_BOT_TOKEN`) dan `send_telegram_user` (Telethon user account, session `runtime/tg_checker_session`, bisa DM siapa saja). Client Telethon di-cache (`_client`) dengan `asyncio.Lock`.
- **`bot/utils.py`** — `normalize_phone`, pembaca CSV tahan export Google Sheets (`read_csv_rows`, `_unwrap_row`), `COLUMN_ALIASES` untuk nama kolom ber-alias, template pesan (`TEMPLATES`), dan `personalize_message`.

### 2. `cli/` — Command-line tools

- **`cli/checker.py`** — Inti logika verifikasi nomor, dipanggil oleh worker pengecekan GUI:
  - `check_whatsapp_batch(numbers, progress_cb, skip_interactive)` — Selenium, membuka URL `https://web.whatsapp.com/send?phone=...` per nomor; deteksi nomor tidak terdaftar via `detect_invalid_number`.
  - `check_telegram_batch(numbers_or_players)` — Telethon `ImportContactsRequest`; satu request batch untuk semua nomor; mengembalikan `{nomor: user_id | None}`.
  - `check_all(...)` — kombinasi WA + TG untuk pemakaian CLI.
- **`cli/send.py`** — Bulk send dengan flag `--mode`, `--wa-only`, `--tg-only`, `--delay`, `--dry-run`, `--force`, `--check-file`; dedup via `msg_fingerprint` + `get_sent_set`; menulis log ke `runtime/logs/bulk_results_*.csv` dan tabel `send_logs`.
- **`cli/check_reminders.py`** — Scan report untuk pemain yang belum redeem (`status_redeem = No`) atau belum GEAR (`lencana_gear` kosong / "No Badge") → CSV `source/reminders.csv`.
- **`cli/extract_facilitators.py`** — Ekstrak baris fasilitator dari daily report CSV (nama yang cocok dengan `FASIL_NAMES`) → `source/fasilitators.csv`.
- **`cli/main.py`** — CLI lama: kirim satu pesan ke satu nomor WA/TG.

### 3. `gui/` — Dashboard web (FastAPI)

Server FastAPI berjudul **"GCAF Auto Messenger"** di `gui/app.py`. Menyajikan halaman HTML (Jinja2 + HTMX) dan partial untuk interaksi dinamis. `gui/checker_async.py` mengelola pengecekan nomor di proses terpisah.

Endpoint lengkap dan detail auth ada di [Referensi HTTP API](./API.md).

## Alur Data

Alur utama dari upload hingga dashboard:

```
 Upload CSV (POST /upload)
      │
      ▼
 db.import_daily_report(tmp_path)         ┌──────────────────────────────┐
      │  → parsing baris-per-baris        │  runtime/gcaf.db (SQLite)    │
      │  → normalisasi nama & nomor       │  ┌──────────────┐            │
      │  → INSERT ... ON CONFLICT         │  │ daily_reports│ ← source   │
      ▼                                   │  │ players      │   of truth │
 auto-upsert ke tabel players             │  │ send_logs    │            │
 (wa/tg status 0, updated_at NULL =       │  │ reminders    │            │
  "belum dicek")                          │  │ manual_queue │            │
      │                                   │  └──────────────┘            │
      ▼                                   └──────────────▲───────────────┘
 Dashboard / Players (get_players_summary:                     │
 daily_reports LEFT JOIN players)                             │ upsert
      │                                                       │
      ▼                                                       │
 POST /check ──▶ start_check_background() ──▶ worker mp.Process
      │              (flock start-lock)          │
      ▼                                          ▼
  runtime/check_status.json (protokol)   cli.checker:
  → widget dashboard poll /check/status  check_whatsapp_batch (Selenium)
       (HTMX hx-trigger="every 2s")      check_telegram_batch (Telethon)
                                             │
                                             ▼
                                      db.upsert_players_batch(...)
                                             │
                                             ▼
                                    dashboard-stats / players table
```

Detail lengkap ada di [Pipeline Pengecekan Nomor](./CHECK_PIPELINE.md) dan [Model Data](./DATA_MODEL.md).

### Alur pengiriman pesan (GUI)

`/players` menampilkan daftar peserta; per baris ada pemilih tipe pesan (kasual/formal/join-*/remind-*), pratinjau pesan (`/api/message-preview/{nomor}`), dan tombol kirim:

```
Pilih tipe → GET /api/message-preview/{nomor}?type=...
              → TEMPLATES[type] dipersonalisasi (placeholder {nama} {nama_fasil} {kode_fasil})
              → render _msg_preview.html (pratinjau + tombol Kirim WA / Kirim TG)

Kirim WA → POST /api/send-wa/{nomor}?type=...      (rate limit per IP)
            → asyncio.to_thread(send_whatsapp_instant)   [Selenium blocking]
            → db.insert_send_log(...)  jika sukses

Kirim TG → POST /api/send-tg/{nomor}?type=...      (rate limit per IP)
            → send_telegram_user(tg_user_id, msg)        [Telethon]
            → db.insert_send_log(...)  jika sukses
```

Log yang berhasil ditulis ke `send_logs` dan muncul di halaman `/logs` serta preview dashboard.

## Model Proses

### Proses GUI

- Satu proses server FastAPI (jalankan `python gui/app.py` atau `uvicorn gui.app:app`).
- `lifespan` (startup) memanggil `db.init_db()`; pada shutdown menutup driver Selenium WA (`close_wa_driver`) dan client Telethon (`close_telegram_client`).
- Operasi Selenium yang memblokir event loop dijalankan lewat `asyncio.to_thread` (upload file, `send_whatsapp_instant`).

### Worker pengecekan (multiprocessing)

`gui/checker_async.py` men-spawn `multiprocessing.Process` target `_run_check_worker` agar pengecekan (Selenium + Telethon) tidak memblokir FastAPI:

- `start_check_background()` — cek status "running" (dari file status + `flock` start-lock `runtime/check.lock`), ambil peserta yang belum dicek (`db.get_unscanned_players()`), tulis status `running`, spawn proses, catat `pid` + `pid_started`.
- `_run_check_worker(players)` — di proses anak: reset koneksi SQLite cache (`db._conn = None`), jalankan `check_whatsapp_batch` lalu `check_telegram_batch`, gabung hasilnya, lalu `db.upsert_players_batch`. Semua exception ditangkap dan ditulis ke status file — worker tidak boleh mati diam-diam.
- Protokol komunikasi: **file `runtime/check_status.json`** (status, progress, total, phase, error, pid, pid_started, started_at, updated_at). GUI hanya membaca file ini; tidak ada IPC lain.
- `get_check_status()` — pembaca status dengan deteksi mati/stale (lihat [Pipeline Pengecekan](./CHECK_PIPELINE.md)).
- `stop_check_background()` — kill tree worker (SIGTERM lalu SIGKILL), tandai status `stopped`.

## Rantai Middleware (gui/app.py)

Middleware terdaftar dengan dekorator `@app.middleware("http")` dalam urutan:

1. `require_players_middleware` — terdaftar pertama
2. `csrf_origin_middleware`
3. `auth_middleware` — terdaftar terakhir

Starlette membangun stack dari `reversed(middleware)`, sehingga **`auth_middleware` dieksekusi paling luar**, lalu CSRF, lalu `require_players`, baru route. Urutan efektif request:

```
Request → auth_middleware → csrf_origin_middleware → require_players_middleware → Route
```

| Middleware | Tugas |
|---|---|
| `auth_middleware` | Jika `DASHBOARD_TOKEN` tidak diset → lewati semua (mode terbuka, bind lokal). Jika diset: izinkan `/static`, `/login`, `/healthz`; validasi token dari `Authorization: Bearer`, cookie `gcaf_token`, atau query `?token=` (GET saja). Gagal: `/api/*` → 401 JSON; selain itu → redirect 303 ke `/login` (dengan header `HX-Redirect` untuk request HTMX). |
| `csrf_origin_middleware` | Untuk `POST/PUT/DELETE`: bandingkan `Origin` (atau `Referer`) dengan host request; beda host → 403 `{"detail": "Forbidden: asal permintaan tidak dikenali"}`. |
| `require_players_middleware` | Jika belum ada peserta terimport (`db.get_players_total_from_reports()` dengan cache TTL 3 detik), semua path selain `_ONBOARDING_ALLOWED_PATHS` dan `/static` diblokir → redirect 303 ke `/` (atau `HX-Redirect` untuk HTMX). Path yang diizinkan saat onboarding: `/`, `/upload`, `/api/dashboard-upload`, `/templates`, `/login`, `/healthz`. |

Catatan: middleware `auth_middleware` membolehkan `/templates` dan `/api/dashboard-upload` lewat dari auth (via `_AUTH_EXEMPT_PATHS` = `{"/login", "/healthz"}` dan pengecualian `/static`), tapi halaman tersebut tetap terblokir oleh `require_players_middleware` selama onboarding karena tidak ada peserta.

### Alasan desain

- **File status JSON** alih-alih IPC penuh: sederhana, mudah di-debug, dan bertahan lintas restart — widget dashboard tinggal membaca file.
- **Worker di proses terpisah**: pengecekan Selenium yang lambat tidak memblokir event loop FastAPI, dan jika worker crash, server GUI tetap hidup.
- **`GUI_RELOAD=1` tidak aman** bersama `multiprocessing.Process`: reloader men-spawn ulang server, worker child ikut mengeksekusi ulang `uvicorn.run`. Karena itu reload default OFF.
