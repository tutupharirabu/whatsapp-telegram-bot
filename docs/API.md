# Referensi HTTP API

Daftar lengkap route HTTP pada server GUI FastAPI (`gui/app.py`). Server berjudul **"GCAF Auto Messenger"** dan berjalan di port `8000`.

Baca juga: [Arsitektur](./ARCHITECTURE.md) · [Model Keamanan](./SECURITY.md) · [Setup](./SETUP.md).

## Ringkasan

- **20 route** terdaftar di `gui/app.py` (12 GET, 8 POST — dihitung dari dekorator `@app.get`/`@app.post`).
- Hampir semua route mengembalikan **HTML** (halaman penuh atau partial Jinja2 untuk swap HTMX). Satu-satunya respons JSON murni adalah `GET /healthz`.
- Auth berlaku untuk semua route kecuali `GET /login`, `POST /login`, `GET /healthz`, dan `GET /static/*` (lihat [Model Keamanan](./SECURITY.md)).
- `GET /check` hanya redirect ke `/` (halaman standalone check dihapus; fitur ada di dashboard).

## Autentikasi

Cara memberikan token (semua memakai perbandingan konstan-waktu `secrets.compare_digest`):

1. **Header**: `Authorization: Bearer <token>`
2. **Cookie**: `gcaf_token=<token>` (diset oleh `POST /login`, `httponly`, `samesite=lax`, `secure` bila HTTPS, berlaku 7 hari)
3. **Query string** (hanya GET): `?token=<token>`

Jika `DASHBOARD_TOKEN` kosong, semua permintaan lolos auth (mode terbuka, server bind `127.0.0.1`). Jika token diset dan permintaan tidak valid:

- Path `/api/*` → `401` JSON `{"detail": "Unauthorized"}`
- Path lain → redirect `303` ke `/login` (dengan header `HX-Redirect: /login` bila request HTMX)

## Middleware yang Berlaku untuk Semua Route

| Middleware | Perilaku |
|---|---|
| `auth_middleware` | Validasi token (lihat di atas). Pengecualian: `/static`, `/login`, `/healthz`. |
| `csrf_origin_middleware` | Untuk `POST/PUT/DELETE`: jika `Origin` atau `Referer` ada dan `netloc`-nya beda dengan host request → `403` JSON `{"detail": "Forbidden: asal permintaan tidak dikenali"}`. |
| `require_players_middleware` | Jika belum ada peserta terimport, semua path selain `_ONBOARDING_ALLOWED_PATHS` (`/`, `/upload`, `/api/dashboard-upload`, `/templates`, `/login`, `/healthz`) dan `/static` diblokir → redirect `303` ke `/` (atau `HX-Redirect: /` untuk HTMX). |

## Rate Limiting

Pada endpoint kirim (`POST /api/send-wa/{nomor}` dan `POST /api/send-tg/{nomor}`):

- Batas **10 request per 60 detik per IP** (in-memory, `_RATE_LIMIT_MAX = 10`, `_RATE_LIMIT_WINDOW = 60.0`).
- Ketika terlampaui → respons HTML dengan status **429** "Terlalu banyak permintaan — coba lagi sebentar lagi".
- Penyimpanan in-memory per proses; ter-reset saat server restart.

## Route Halaman (HTML penuh)

### `GET /login` — Halaman login

- Response: `_login.html` (halaman HTML). Jika `DASHBOARD_TOKEN` tidak diset → redirect `303` ke `/`.

### `POST /login` — Submit token login

- Form field: `token` (string).
- Jika token cocok → `RedirectResponse` ke `/` dan set cookie `gcaf_token` (httponly, samesite=lax, secure bila HTTPS, `max_age = 7 * 24 * 3600`).
- Jika salah → render ulang `_login.html` dengan `error = "Token akses salah."`.
- Dikecualikan dari auth middleware.

### `GET /healthz` — Health check

- Response: **JSON** `{"status": "ok"}`. Dikecualikan dari auth.

### `GET /` — Dashboard

- Jika `total_reports == 0` → render `_onboarding.html` (flow upload pertama kali).
- Selain itu → render `dashboard.html` dengan context: `stats` (dari `db.get_dashboard_stats()`), `logs` (`db.get_recent_logs(limit=5)`), dan status check (`is_running`, `status`, `progress`, `total`, `phase`, `error`, `all_checked` dari `get_check_status()`).

### `GET /api/dashboard-upload` — Form upload dashboard

- Render partial `_dashboard_upload.html` (dropzone upload). Salah satu path yang diizinkan saat onboarding.

### `POST /upload` — Upload CSV laporan harian

- Multipart form: `file` (UploadFile, wajib).
- Menulis ke temp dir (`gcaf_upload_*`), memanggil `db.import_daily_report(tmp_path)`.
- `HX-Target: dashboard-upload` → partial `_dashboard_upload_result.html`; selain itu `_upload_result.html`. State: `success` (dengan `imported`, `skipped`), `empty`, atau `error`.
- `ValueError`/`OSError` → state `error`. Pada `success`, cache `_PLAYERS_CACHE` di-invalidasi.

### `GET /players` — Daftar peserta

- Query params: `search` (str, default ""), `limit` (int, default 100, minimal 1), `offset` (int, default 0, minimal 0).
- Request HTMX (`HX-Request`) → partial `_players_table.html`; selain itu halaman penuh `players.html`.
- Data dari `db.get_players_summary(search, limit, offset)`; `total` dari `db.get_players_total_from_reports()`; pagination (`has_prev`, `has_next`).

### `GET /logs` — Riwayat pengiriman

- Query params: `limit` (int, default 100, minimal 1), `offset` (int, default 0, minimal 0).
- Render `logs.html`; data `db.get_send_logs(limit, offset)` dan `db.get_send_logs_count()`.

### `GET /templates` — Kelola template pesan

- Render `templates.html` dengan `templates = TEMPLATES` (dari `bot/utils.py`, gabungan default + `runtime/templates.json`).
- Salah satu path yang diizinkan saat onboarding.

## Route Aksi (HTMX partial)

### `POST /players/toggle-tg/{nomor}` — Toggle status join grup Telegram

- Path param: `nomor` (nomor_normalized).
- Memanggil `db.toggle_tg_joined(nomor)` (flip bit `tg_joined` 0↔1).
- Peserta tidak ditemukan → HTML inline `<span>Peserta tidak ditemukan</span>`.
- Sukses → partial `_player_row.html` dengan `p` dari `db.get_player_summary_by_phone(nomor)`.

### `POST /check` — Mulai pengecekan nomor

- Baca `get_check_status()`:
  - Status `running` → render widget `running` tanpa spawn proses kedua.
  - Ada nomor belum dicek (`db.get_players_unused_numbers()`) → `start_check_background()` lalu render widget `running` dengan `total` = jumlah nomor.
  - Tidak ada nomor baru → render widget dengan `all_checked: True` dan notice "Tidak ada nomor baru untuk dicek."
- Response: partial `_check_widget.html`.

### `GET /check` — Halaman check (di-deprecate)

- Selalu `RedirectResponse` ke `/` (`303`). Fitur cek dipusatkan di dashboard.

### `POST /check/stop` — Hentikan pengecekan

- Memanggil `stop_check_background()` (kill tree worker, tandai status `stopped`).
- Response: partial `_check_widget.html` dengan status hasil stop.

### `GET /check/status` — Status pengecekan (untuk polling HTMX)

- Baca `get_check_status()`:
  - `idle`/`done` → jika masih ada nomor belum dicek render widget tidak-running (`progress 0`, status `None`); jika semua sudah dicek render status `done` dengan `progress/total` dari file status. Bila status file `done`, tambahkan header `HX-Trigger: update-dashboard`.
  - `running`/`interrupted`/`stale`/`error`/`stopped` → render widget sesuai status.
- Response: partial `_check_widget.html`. Widget dashboard mem-poll endpoint ini via `hx-trigger="every 2s"`.

### `GET /api/dashboard-stats` — Statistik dashboard (partial)

- Render `_dashboard_stats.html` dengan `stats` dari `db.get_dashboard_stats()`. Dipicu event `update-dashboard`.

### `GET /api/dashboard-logs` — Log terbaru dashboard (partial)

- Render `_dashboard_logs.html` dengan `logs` dari `db.get_recent_logs(limit=5)`. Dipicu event `update-dashboard`.

### `GET /api/message-preview/{nomor_normalized}` — Pratinjau pesan

- Query param: `type` (default `kasual`).
- Peserta tidak ditemukan atau template tidak dikenal → HTML inline pesan error.
- `type` di `("remind-both", "join-full", "join-redeem", "join-gear")` → `_msg_preview.html` dengan `msg_wa` dan `msg_tg` (pesan gabungan, sama untuk kedua platform).
- `type` lain (mis. `kasual`, `formal`) → `_msg_preview.html` hanya dengan `msg_wa`.
- Pesan dibuat via `personalize_message(tpl, player, FASIL_NAME, FASIL_CODE)` (env, fallback `Irfan Zharauri` / `GCAF26-ID-9MJ-EP6`).

### `POST /api/send-wa/{nomor_normalized}` — Kirim pesan WhatsApp

- Query param: `type` (default `kasual`). **Rate limit: 10/60s per IP → 429.**
- Peserta tidak ditemukan → HTML "Error". Template tidak dikenal → HTML "Template tak dikenal".
- Memanggil `send_whatsapp_instant(nomor, msg)` via `asyncio.to_thread` (Selenium blocking).
- Sukses (`status == "success"`) → `db.insert_send_log(...)` (wa_available/wa_sent true, mode=type), respons HTML "✓ Terkirim via WA" dengan header `HX-Trigger: update-dashboard`.
- Gagal → HTML "Gagal: <error>" (`ValueError`/`OSError`/`RuntimeError` ditangkap).

### `POST /api/send-tg/{nomor_normalized}` — Kirim pesan Telegram

- Query param: `type` (default `kasual`). **Rate limit: 10/60s per IP → 429.**
- Peserta tidak ditemukan → HTML "Error". Tanpa `tg_user_id` → HTML "Gagal: TG User ID tidak ditemukan". Template tidak dikenal → HTML "Template tak dikenal".
- Memanggil `send_telegram_user(int(tg_user_id), msg)` (Telethon, `await` langsung).
- Sukses (ada `message_id`) → `db.insert_send_log(...)` (tg_available/tg_sent true), HTML "✓ Terkirim via TG" dengan header `HX-Trigger: update-dashboard`.
- Gagal → HTML "Gagal" atau "Gagal: <error>".

### `POST /templates/save/{key}` — Simpan template pesan

- Path param: `key` (mis. `kasual`, `join-full`).
- Form field: `content` (string).
- Gabungkan `_DEFAULT_TEMPLATES` + `_load_templates()`, set `current[key] = content`, tulis ke `runtime/templates.json` (JSON indent 2, `ensure_ascii=False`), lalu hot-reload `bot.utils.TEMPLATES` di proses berjalan.
- Response: partial `_template_card.html` (`{"key": key, "tpl": new_content}`).

## Tabel Ringkasan Route

| Method | Path | Params | Response | Auth |
|---|---|---|---|---|
| GET | `/login` | — | HTML (`_login.html`) | exempt |
| POST | `/login` | form `token` | Redirect + cookie | exempt |
| GET | `/healthz` | — | JSON `{"status":"ok"}` | exempt |
| GET | `/` | — | HTML (`_onboarding.html` / `dashboard.html`) | ya |
| GET | `/api/dashboard-upload` | — | partial `_dashboard_upload.html` | ya |
| POST | `/upload` | file | partial upload result | ya |
| GET | `/players` | `search`, `limit`, `offset` | partial `_players_table.html` / `players.html` | ya |
| POST | `/players/toggle-tg/{nomor}` | path | partial `_player_row.html` | ya |
| POST | `/check` | — | partial `_check_widget.html` | ya |
| GET | `/check` | — | Redirect 303 ke `/` | ya |
| POST | `/check/stop` | — | partial `_check_widget.html` | ya |
| GET | `/check/status` | — | partial `_check_widget.html` | ya |
| GET | `/api/dashboard-stats` | — | partial `_dashboard_stats.html` | ya |
| GET | `/api/dashboard-logs` | — | partial `_dashboard_logs.html` | ya |
| GET | `/api/message-preview/{nomor_normalized}` | `type` | partial `_msg_preview.html` | ya |
| POST | `/api/send-wa/{nomor_normalized}` | `type` | HTML inline (429 bila rate limit) | ya |
| POST | `/api/send-tg/{nomor_normalized}` | `type` | HTML inline (429 bila rate limit) | ya |
| GET | `/templates` | — | HTML (`templates.html`) | ya |
| POST | `/templates/save/{key}` | form `content` | partial `_template_card.html` | ya |
| GET | `/static/*` | — | file statis (mount) | exempt |

## Catatan

- Endpoint `POST /api/send-*` hanya mengecek rate limit untuk IP klien; tidak ada rate limit pada route lain.
- Respons "JSON" murni hanya `/healthz`; error JSON juga muncul dari middleware (`401`/`403`).
- `FASIL_NAME`/`FASIL_CODE` dibaca dari env dengan fallback ke nilai default yang tertanam di kode; lihat [Setup](./SETUP.md).
