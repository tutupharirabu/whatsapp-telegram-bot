# Model Keamanan

Dokumen ini menjelaskan lapisan keamanan pada dashboard web dan repositori: autentikasi token, CSRF, rate limiting, bind lokal, praktik operasional, serta setup CodeQL dan Dependabot.

Baca juga: [Arsitektur](./ARCHITECTURE.md) · [Referensi HTTP API](./API.md) · [Setup](./SETUP.md).

## Ringkasan Lapisan Keamanan

```
 Request
   │
   ▼
 [1] Bind host          DASHBOARD_TOKEN kosong → 127.0.0.1 saja
   │
   ▼
 [2] auth_middleware    Token dari Bearer header / cookie gcaf_token / ?token= (GET)
   │                     gagal → 401 (API) atau redirect 303 ke /login
   ▼
 [3] csrf_origin_middleware   POST/PUT/DELETE: Origin/Referer beda host → 403
   │
   ▼
 [4] require_players_middleware  Belum ada peserta → blokir selain halaman onboarding
   │
   ▼
 [5] rate limiting (per IP)  POST /api/send-wa & /api/send-tg: 10 req / 60 detik → 429
   │
   ▼
 [6] Route
```

## 1. Token Dashboard (`DASHBOARD_TOKEN`)

Diambil dari env `DASHBOARD_TOKEN` (dimuat `load_dotenv()`). Dua mode:

- **Token kosong (mode terbuka)**: `auth_middleware` membiarkan semua request; server bind `127.0.0.1` (warning dicetak saat startup). Aman hanya untuk penggunaan lokal.
- **Token diset**: semua request harus membawa token, kecuali `/static`, `/login`, `/healthz`.

Cara membawa token (validasi memakai `secrets.compare_digest` — perbandingan konstan-waktu):

1. **Header**: `Authorization: Bearer <token>`
2. **Cookie**: `gcaf_token=<token>` — diset oleh `POST /login` dengan `httponly=True`, `samesite="lax"`, `secure=request.url.scheme == "https"`, `max_age = 7 * 24 * 3600` (7 hari).
3. **Query string** (hanya metode GET): `?token=<token>`

Respons tidak valid:

- Path `/api/*` → `401` JSON `{"detail": "Unauthorized"}`
- Path lain → `RedirectResponse(303)` ke `/login`; bila request HTMX, ditambah header `HX-Redirect: /login`.

Halaman login: `GET /login` (render `_login.html`), `POST /login` (form field `token`; cocok → redirect + set cookie; salah → render ulang dengan pesan error). Keduanya dikecualikan dari auth middleware.

Membuat token:

```shell
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 2. CSRF Origin Check

`csrf_origin_middleware` berlaku untuk **POST/PUT/DELETE**:

- Ambil header `Origin`; jika tidak ada, fallback ke `Referer`.
- Parsing `netloc` dan bandingkan dengan `request.url.netloc`.
- Berbeda host → `403` JSON `{"detail": "Forbidden: asal permintaan tidak dikenali"}`.

Catatan: header yang tidak ada sama sekali tidak diblokir (tidak ada source yang bisa dibandingkan). Ini adalah pertahanan berbasis origin, bukan token CSRF.

## 3. Rate Limiting

- In-memory per IP: `_RATE_LIMIT: {client_ip: [timestamps]}`, dilindungi `threading.Lock`.
- `_RATE_LIMIT_MAX = 10` request per `_RATE_LIMIT_WINDOW = 60.0` detik.
- Berlaku pada **`POST /api/send-wa/{nomor}`** dan **`POST /api/send-tg/{nomor}`** (di cek sebelum pengiriman).
- Terlampaui → respons HTML status **429** "Terlalu banyak permintaan — coba lagi sebentar lagi".
- Struktur data dibersihkan saat melebihi 500 key (mencegah pertumbuhan tak terbatas).
- Keterbatasan: state di memori per proses, hilang saat restart; tidak membedakan pengguna (semua share bucket per IP).

## 4. Bind Lokal vs Akses Jarak Jauh

- `DASHBOARD_TOKEN` kosong → `default_host = "127.0.0.1"` (hanya akses dari mesin yang sama).
- Token diset → default host `"0.0.0.0"` (bisa diakses jaringan). Env `HOST` menimpa.
- Rekomendasi di `.env.example` dan README: biarkan `127.0.0.1` dan akses jarak jauh via **Tailscale / SSH tunnel**; jangan buka port mentah-mentah ke jaringan.

## 5. Praktik Operasional

- **Set `DASHBOARD_TOKEN`** jika dashboard diakses dari luar localhost.
- **Gunakan HTTPS** di depan server bila diakses dari jarak jauh (reverse proxy / tunnel); cookie `gcaf_token` baru diberi flag `secure` bila skema request HTTPS.
- **Jangan commit `.env`** — sudah ada di `.gitignore`; berisi kredensial (API ID/hash Telegram, bot token).
- **Runtime berisi PII**: `runtime/` di-gitignore (DB SQLite berisi nama/email/nomor peserta, session Telegram, profil Chrome WA). Backup wajib ke media terenkripsi (`scripts/backup_runtime.sh` mengingatkan hal ini).
- **Jangan jalankan GUI dan CLI/checker bersamaan** — keduanya berbagi profil WhatsApp Web (`wa_profile.lock` mencegah dua proses memakai profil yang sama).
- **Jangan gunakan `GUI_RELOAD=1`** di produksi — reloader men-spawn server dan bisa membuat worker `multiprocessing.Process` ikut mengeksekusi ulang `uvicorn.run`.

## 6. CodeQL & Dependabot

Repositori menyertakan konfigurasi keamanan otomatis GitHub (folder `.github/`, belum di-commit — muncul sebagai untracked).

### CodeQL Advanced — `.github/workflows/codeql.yml`

- Nama workflow: **"CodeQL Advanced"**, menganalisis bahasa `python`.
- Trigger: `push` ke `main`, `pull_request` ke `main`, dan jadwal mingguan (`cron: "30 1 * * 1"`).
- `concurrency` membatalkan run yang sedang berjalan untuk PR yang sama (hanya analisis terbaru).
- `permissions: security-events: write` (prinsip least-privilege — hanya perlu upload SARIF ke security-events).
- Langkah: checkout (`actions/checkout@v4`), setup Python 3.11 (`actions/setup-python@v5`), `pip install -r requirements.txt`, init CodeQL dengan `queries: security-extended` dan `config-file: ./.github/codeql/codeql-config.yml`, autobuild, lalu analyze (`github/codeql-action/*@v3`).
- `timeout-minutes: 360`.

### Konfigurasi CodeQL — `.github/codeql/codeql-config.yml`

- `paths-ignore`: `runtime/` (state runtime: DB, log, profil Chrome, session), `.venv/`, `__pycache__/`, `.playwright-mcp/`, `.uiwork/`, `source/` (hanya data CSV).

### Dependabot — `.github/dependabot.yml`

- `package-ecosystem: pip`, `directory: "/"` (root `requirements.txt`).
- Jadwal: mingguan, setiap **Senin pukul 06:00 Asia/Jakarta**.
- `open-pull-requests-limit: 5`.
- Group `python-minor` menggabungkan update `minor` dan `patch` ke dalam satu PR (versi `major` tetap terpisah).

## Rekomendasi Tambahan

- Pertimbangkan memindahkan `DASHBOARD_TOKEN` ke secret manager / variabel environment deployment daripada `.env` lokal bila dipakai di server bersama.
- Pantau hasil CodeQL (Security tab → Code scanning) dan review PR Dependabot secara berkala.
- Untuk autentikasi yang lebih kuat (multi-user, sesi server-side), perlu pengembangan lebih lanjut — model saat ini adalah token tunggal yang dibagikan.
