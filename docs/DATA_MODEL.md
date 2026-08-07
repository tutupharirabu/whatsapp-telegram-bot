# Model Data

Semua persistent data disimpan di SQLite: `runtime/gcaf.db` (di-*gitignore*). Modul `bot/db.py` adalah satu-satunya lapisan akses data; ia memakai satu koneksi global dengan `check_same_thread=False`, `threading.RLock`, `PRAGMA journal_mode=WAL`, dan `PRAGMA foreign_keys=ON`, dengan `row_factory = sqlite3.Row`.

Baca juga: [Arsitektur](./ARCHITECTURE.md) · [Pipeline Pengecekan](./CHECK_PIPELINE.md) · [Referensi HTTP API](./API.md).

## Konvensi

- **Nomor telepon** disimpan dalam format internasional tanpa `+`, hasil `bot.utils.normalize_phone` (contoh: `0812...` → `62812...`). Kolom ini disebut `nomor_normalized` dan menjadi kunci natural untuk join/dedup.
- Peserta tanpa nomor HP diimpor dengan `nomor_normalized = "email:" + email.lower()`.
- **Timestamp** memakai ISO 8601 (`datetime('now')` SQLite pada default kolom, atau `datetime.now(timezone.utc).isoformat()` dari Python). Migrasi `init_db` menormalkan format lama `"YYYY-MM-DD HH:MM:SS"` (spasi) menjadi `T`.
- **Nama** dinormalisasi dengan `normalize_nama` (capitalize tiap kata, pertahankan titik/hipen/apostrof).
- `players.updated_at IS NULL` berarti **belum pernah dicek** (penanda penting untuk pipeline pengecekan).

## Tabel

Skema didefinisikan di `init_db()` (`CREATE TABLE IF NOT EXISTS ...`). Tabel: `players`, `daily_reports`, `reminders`, `send_logs`, `manual_queue`.

### `players`

Status hasil pengecekan per peserta, di-update oleh worker pengecekan.

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `nama` | TEXT NOT NULL | Dinormalisasi |
| `nomor_hp` | TEXT NOT NULL | Nomor asli dari CSV |
| `nomor_normalized` | TEXT NOT NULL UNIQUE | Kunci natural (format `62...`) |
| `wa_available` | INTEGER DEFAULT 0 | Terdaftar WhatsApp (hasil cek) |
| `tg_available` | INTEGER DEFAULT 0 | Terdaftar Telegram (hasil cek) |
| `tg_user_id` | INTEGER | User ID Telegram (hasil cek) |
| `tg_joined` | INTEGER DEFAULT 0 | Sudah bergabung grup TG (manual toggle) |
| `created_at` | TEXT DEFAULT `datetime('now')` | |
| `updated_at` | TEXT DEFAULT `datetime('now')` | `NULL` = belum dicek |

Index: `idx_players_phone (nomor_normalized)`.

### `daily_reports`

Data laporan harian per peserta (source of truth untuk daftar peserta). Satu peserta bisa punya beberapa baris (per tanggal laporan).

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `nama` | TEXT NOT NULL | |
| `email` | TEXT | |
| `nomor_hp` | TEXT NOT NULL | |
| `nomor_normalized` | TEXT NOT NULL | |
| `status_redeem` | TEXT | Contoh: "Yes"/"No" |
| `lencana_gear` | TEXT | Contoh: "Enterprise..." / "No Badge" |
| `milestone` | TEXT | |
| `bonus_milestone` | TEXT | |
| `status_verifikasi_ai_agent` | TEXT | |
| `jumlah_lencana` | INTEGER DEFAULT 0 | |
| `jumlah_arcade_game` | INTEGER DEFAULT 0 | |
| `nama_lencana` | TEXT | |
| `nama_arcade_game` | TEXT | |
| `report_date` | TEXT | Dari nama file (contoh `28 Jul 2026`) atau mtime (`YYYY-MM-DD`) |
| `created_at` | TEXT DEFAULT `datetime('now')` | |

Constraint: `UNIQUE(nomor_normalized, report_date)`. Index: `idx_daily_reports_phone (nomor_normalized)`.

### `reminders`

Antrian reminder (dipakai `cli/check_reminders.py`; kolom `player_id` FK ke `players`).

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `player_id` | INTEGER REFERENCES players(id) | |
| `nama` | TEXT NOT NULL | |
| `nomor_hp` | TEXT NOT NULL | |
| `reminder_type` | TEXT NOT NULL | Mis. `redeem`, `gear`, `redeem,gear` |
| `status` | TEXT DEFAULT 'pending' | |
| `created_at` | TEXT DEFAULT `datetime('now')` | |
| `sent_at` | TEXT | |

Index: `idx_reminders_status (status)`.

### `send_logs`

Log pengiriman pesan (halaman `/logs`, dashboard, dan basis dedup).

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `player_id` | INTEGER | Resolved dari `players` saat insert |
| `nama` | TEXT | Dinormalisasi |
| `nomor_hp` | TEXT | |
| `wa_available` | INTEGER DEFAULT 0 | Snapshot status saat kirim |
| `tg_available` | INTEGER DEFAULT 0 | |
| `wa_sent` | INTEGER DEFAULT 0 | |
| `tg_sent` | INTEGER DEFAULT 0 | |
| `wa_error` | TEXT | Error WA; `skip:*` = bukan error nyata |
| `tg_error` | TEXT | Error TG; `skip:*` = bukan error nyata |
| `mode` | TEXT | Tipe template, mis. `kasual`, `custom` |
| `batch_id` | TEXT | ID batch (8 char hex untuk bulk send) |
| `timestamp` | TEXT DEFAULT `datetime('now')` | |
| `msg_hash` | TEXT | Hash template pra-personalisasi (migrasi idempotent `init_db` menambahkan kolom ini) |

Index: `idx_send_logs_batch (batch_id)`, `idx_send_logs_dedup (nomor_hp, msg_hash)`.

### `manual_queue`

Antrian manual (belum dipakai route GUI saat ini; disiapkan untuk fitur antrian).

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `nama` | TEXT | |
| `nomor_hp` | TEXT | |
| `nomor_normalized` | TEXT | |
| `message` | TEXT | |
| `wa_link` | TEXT | |
| `reason` | TEXT | |
| `mode` | TEXT | |
| `batch_id` | TEXT | |
| `status` | TEXT DEFAULT 'pending' | |
| `created_at` | TEXT DEFAULT `datetime('now')` | |
| `sent_at` | TEXT | |

Index: `idx_manual_queue_status (status)`.

## Fungsi Kunci `bot/db.py`

### Inisialisasi & migrasi

- `init_db()` — buat skema + index, migrasi idempotent: tambah kolom `send_logs.msg_hash`, normalisasi nama data lama, set `updated_at = NULL` untuk pemain yang auto-insert tapi belum dicek, unifikasi timestamp lama ke format ISO, set `PRAGMA user_version = 1`.

### Import laporan harian

- `import_daily_report(csv_path) -> tuple[int, int]` — parse CSV baris-per-baris (UTF-8 BOM-safe, tahan baris yang dibungkus quote ekstra via `_unwrap_row`), ambil tanggal dari nama file (`_extract_report_date`: `[28 Jul]`, `28-Jul`, `2026-07-28`, dst; fallback mtime), lalu:
  - `INSERT INTO daily_reports ... ON CONFLICT(nomor_normalized, report_date) DO UPDATE ...` (upsert per peserta per tanggal).
  - Auto-upsert ke `players` (`INSERT ... ON CONFLICT(nomor_normalized) DO UPDATE SET nama, nomor_hp`; `updated_at` dibiarkan `NULL` menandakan belum dicek).
  - Return `(imported, skipped)` — baris rusak dihitung `skipped`.

### Players

- `upsert_player(nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id) -> int` — insert/update satu peserta (kunci `nomor_normalized`), set `updated_at` saat update.
- `upsert_players_batch(players)` — bulk upsert dari hasil cek (`[{nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id}]`).
- `get_player_by_phone(nomor_normalized) -> dict | None` — baris penuh `players`.
- `get_players_summary(search, limit, offset) -> list[dict]` — daftar peserta dari `daily_reports` (hanya baris terbaru per `nomor_normalized` via subquery `MAX(id)`), `LEFT JOIN players` untuk status WA/TG, plus `wa_error` terakhir dari `send_logs` (mengabaikan `skip:*`). Ordering `nama COLLATE NOCASE`.
- `get_player_summary_by_phone(nomor_normalized) -> dict | None` — satu baris ringkasan (shape sama dengan `get_players_summary`), untuk re-render row.
- `toggle_tg_joined(nomor_normalized) -> int` — flip bit `tg_joined` (0↔1); return nilai baru.
- `get_players_total_from_reports() -> int` — `COUNT(DISTINCT nomor_normalized)` dari `daily_reports`.
- `get_players_unused_numbers() -> list[str]` — nomor dari reports yang belum pernah dicek (`players` belum ada atau `updated_at IS NULL`), mengecualikan `email:%`.
- `get_unscanned_players() -> list[dict]` — sama seperti di atas tapi mengembalikan `{nama, nomor_hp, nomor_normalized}` (dipakai `start_check_background`).
- `get_players_count()`, `get_wa_registered_count()`, `get_tg_registered_count()` — hitung dari `players`.

### Send logs

- `insert_send_log(entry, batch_id=None) -> int` — insert satu log; resolve `player_id` via `normalize_phone(nomor_hp)`.
- `insert_send_logs_batch(entries, batch_id=None) -> int` — insert banyak log dalam satu `batch_id` (uuid 8 char bila tidak diberikan).
- `msg_fingerprint(msg_template) -> str` — SHA-256 (16 hex) dari template **sebelum** personalisasi (placeholder `{...}` dibuang) → satu kampanye = satu hash.
- `get_sent_set(platform, msg_hash) -> set` — set `nomor_normalized` yang sudah sukses terkirim (`wa_sent=1`/`tg_sent=1`) untuk pesan tersebut; dipakai dedup di `cli/send.py`.
- `get_send_logs(limit, offset, batch_id=None) -> list[dict]` — log terbaru dulu; menambah field turunan `platform` (`wa`/`tg`) dan `status` (`SUCCESS`/`FAILED`) plus `msg_preview` (`Template: <mode>`) untuk template Jinja.
- `get_send_logs_count() -> int`.
- `get_recent_logs(limit=5) -> list[dict]` — alias `get_send_logs` untuk preview dashboard.

### Dashboard stats

- `get_tg_joined_count() -> int` — `COUNT(*) players WHERE tg_joined = 1`.
- `get_dashboard_stats() -> dict` — mengembalikan:
  - `total_players` (dari `players`)
  - `wa_registered`, `tg_registered`, `tg_joined_count`
  - `total_reports` (dari `daily_reports`)
  - `total_logs` (dari `send_logs`)
  - `unscanned_count` (jumlah `get_players_unused_numbers()`)
  - `recent_logs` (5 log terbaru)

## Alur Data Ringkas

1. **Upload CSV** → `import_daily_report` → baris `daily_reports` + stub `players` (`updated_at = NULL`, belum dicek).
2. **Check** (`/check`) → worker mengambil `get_unscanned_players()` → hasil cek disimpan via `upsert_players_batch` (mengisi `wa_available`, `tg_available`, `tg_user_id`, `updated_at`).
3. **Kirim** (`/api/send-*`) → `insert_send_log` → tampil di `/logs` dan preview dashboard.
4. **Dedup CLI** → `msg_fingerprint` + `get_sent_set` mencegah kirim ulang kampanye yang sama.

## Catatan

- `players` tidak punya constraint unik pada `(nama, nomor_hp)`; kunci uniknya `nomor_normalized`. `daily_reports` adalah source of truth peserta; `players` berisi status cek.
- `manual_queue` dan `reminders` ada di skema namun belum terhubung ke route GUI saat ini.
