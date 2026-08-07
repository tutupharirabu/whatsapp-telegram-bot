# Pipeline Pengecekan Nomor

Pipeline pengecekan nomor (apakah nomor peserta terdaftar di WhatsApp dan/atau Telegram) berjalan **di proses terpisah** dari server FastAPI, dikelola oleh `gui/checker_async.py`, dan mengomunikasikan progres lewat file `runtime/check_status.json`.

Baca juga: [Arsitektur](./ARCHITECTURE.md) · [Model Data](./DATA_MODEL.md) · [Referensi HTTP API](./API.md) (route `/check`, `/check/stop`, `/check/status`).

## Gambaran Umum

```
POST /check (GUI)
   │
   ├─ get_check_status() == "running"?  → tolak start ganda (render widget running)
   │
   ├─ db.get_players_unused_numbers() kosong? → render widget "Semua dicek"
   │
   ▼
 start_check_background()
   │ 1. cek status running (file) + flock start-lock (runtime/check.lock)
   │ 2. re-check pasca-lock (TOCTOU guard)
   │ 3. players = db.get_unscanned_players()
   │ 4. _write_status({"status":"running", ...})
   │ 5. mp.Process(target=_run_check_worker, args=(players,)).start()
   │ 6. _write_status({..., "pid": process.pid, "pid_started": <ps lstart>})
   ▼
 ┌──────────────────────────────────────────────────────────┐
 │ Worker process (_run_check_worker)                      │
 │  - db._conn = None  (reset koneksi SQLite di anak)      │
 │  - _write_status(running, phase=whatsapp, pid, pid_started) │
 │  - wa_results = check_whatsapp_batch(numbers,            │
 │        progress_cb=_progress_cb, skip_interactive=True)  │
 │  - _write_status(running, phase=telegram, progress=total)│
 │  - tg_results = asyncio.run(check_telegram_batch(players)) │
 │  - gabung hasil (pertahankan tg_user_id lama bila None)  │
 │  - db.upsert_players_batch(upsert_data)                  │
 │  - _write_status({"status":"done", progress=total, ...}) │
 │  - exception → _write_status({"status":"error", ...})    │
 └──────────────────────────────────────────────────────────┘
   │
   ▼
 GUI: get_check_status() (polling via GET /check/status, HTMX every 2s)
      - deteksi worker mati → status "interrupted"
      - deteksi beku per fase → status "stale"
      - POST /check/stop → kill tree → status "stopped"
```

## Langkah Detail

### 1. Start: `start_check_background()` (`gui/checker_async.py`)

- Menolak start ganda lewat **dua lapis pengaman**:
  1. `get_check_status().get("status") == "running"` → skip.
  2. `_acquire_start_lock()` — `flock` non-blocking (`LOCK_EX | LOCK_NB`) pada `runtime/check.lock`. Jika gagal (ada proses lain yang memegang lock) → skip. File descriptor ditutup di `finally` sehingga lock terlepas.
  3. Setelah lock dipegang, **re-check** status "running" sekali lagi (TOCTOU guard untuk dua request yang datang bersamaan).
- Mengambil `db.get_unscanned_players()` — peserta dari `daily_reports` yang belum pernah dicek (`players` belum ada atau `updated_at IS NULL`), mengecualikan `email:%`. Jika kosong → batal.
- Menulis status `running` (`progress 0`, `total = len(players)`), men-spawn `multiprocessing.Process(target=_run_check_worker, args=(players,))`, lalu menulis `pid` dan `pid_started` (start time proses via `ps -o lstart=`) ke status file.

### 2. Worker: `_run_check_worker(players)` (proses anak)

- `db._conn = None` — mereset koneksi SQLite yang di-cache di proses induk (koneksi SQLite tidak bisa dipakai lintas fork dengan aman; koneksi baru dibuat di anak).
- Menulis status `running` dengan `phase: "whatsapp"`.
- **Fase WhatsApp** — `cli.checker.check_whatsapp_batch(numbers, progress_cb=_progress_cb, skip_interactive=True)`:
  - Membuka Chrome (via `create_wa_driver`, profil `runtime/wa_chrome_profile/`, lock `wa_profile.lock`), navigasi ke `web.whatsapp.com`.
  - `skip_interactive=True` → jika belum login WA, langsung return `{n: False}` tanpa menunggu `input()` (worker tidak punya terminal interaktif).
  - Untuk tiap nomor: buka `https://web.whatsapp.com/send?phone=<nomor>`, `wait_for_chat_or_invalid`, deteksi `detect_invalid_number`; hasil `{nomor: bool}`.
  - `_progress_cb(current, total)` menulis status `running, phase=whatsapp, progress=current` tiap nomor.
- Menulis status `running` dengan `phase: "telegram"`, `progress: total`.
- **Fase Telegram** — `asyncio.run(cli.checker.check_telegram_batch(players))`:
  - Telethon client dengan session khusus `runtime/checker_session` (terpisah dari `tg_checker_session` milik pengiriman agar tidak saling lock).
  - `connect()` + `is_user_authorized()`; jika belum login → return dict `{nomor: None}` (worker tidak memanggil `input()`, mencegah hang).
  - `ImportContactsRequest` dengan semua nomor sekaligus; `result.users` yang match dipetakan ke `{nomor: user_id}`.
- Menulis status `running` dengan `phase: "save"`.
- **Simpan hasil** — untuk tiap player: `tg_uid = tg_results.get(phone)`; jika `None`, pertahankan `tg_user_id` lama dari DB (re-check tidak boleh menghapus data valid). Lalu `db.upsert_players_batch(upsert_data)` dengan `{nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id}`.
- Menulis `{"status": "done", "progress": total, "total": total, "error": ""}`.
- **Semua exception** ditangkap (`except Exception`) dan ditulis ke status file sebagai `{"status": "error", "phase": <fase saat ini>, "progress": ..., "error": "Worker error: ..."}` — worker **tidak boleh mati diam-diam**. Baris terakhir traceback dicetak ke stdout worker.

### 3. Stop: `stop_check_background()`

- Hanya berlaku jika status file `running`.
- `_kill_tree(pid)`: kumpulkan PID + anak langsung (`pgrep -P pid`), kirim `SIGTERM`, tunggu 1 detik, lalu `SIGKILL` yang masih hidup (mencakup child seperti `chromedriver`).
- Tandai status `stopped` (hapus `error`) dan tulis ke file.
- UI menampilkan widget "Pengecekan dihentikan" dengan tombol "Cek Nomor Baru".

## Protokol Status File (`runtime/check_status.json`)

File JSON tunggal sebagai satu-satunya kanal status antara worker dan GUI.

| Field | Tipe | Keterangan |
|---|---|---|
| `status` | string | `idle`, `running`, `done`, `error`, `interrupted`, `stale`, `stopped` |
| `progress` | int | Nomor yang sudah diproses |
| `total` | int | Total nomor pada batch ini |
| `phase` | string | Fase aktif: `whatsapp`, `telegram`, `save` (atau kosong) |
| `error` | string | Pesan error (kosong bila tidak ada) |
| `pid` | int | PID worker (`mp.Process.pid`) |
| `pid_started` | string | Start time worker dari `ps -o lstart=` — dipakai deteksi PID reuse |
| `started_at` | string | Timestamp ISO UTC saat batch dimulai (dipertahankan `_write_status`) |
| `updated_at` | string | Timestamp ISO UTC setiap kali status ditulis — dipakai watchdog stale |

`_write_status(data)` selalu me-*merge* dengan status lama (mempertahankan `started_at`, `pid`, dll) dan selalu memperbarui `updated_at`.

### Statuses

| Status | Arti | Ditulis oleh |
|---|---|---|
| `idle` | Tidak ada batch / status file tidak ada | `get_check_status()` fallback |
| `running` | Batch sedang berjalan | start + worker (tiap progress) |
| `done` | Batch selesai (semua nomor diproses & di-upsert) | worker |
| `error` | Worker menangkap exception | worker |
| `interrupted` | Status `running` tapi worker sudah mati (PID tidak hidup / PID di-reuse) | `get_check_status()` (deteksi) |
| `stale` | Status `running` tanpa update melebihi batas waktu per fase | `get_check_status()` (deteksi) |
| `stopped` | Dihentikan pengguna via `/check/stop` | `stop_check_background()` |

## Deteksi Worker Mati & Stale (`get_check_status()`)

Saat status file berstatus `running`:

1. **PID check**: `_pid_alive(pid, pid_started)`:
   - Jika `pid_started` ada: bandingkan dengan `ps -o lstart=` proses sekarang. Tidak cocok → PID sudah di-reuse proses lain → worker dianggap mati.
   - Tanpa `pid_started`: `os.kill(pid, 0)` + cek status zombie (`ps -o stat=`; `Z` = mati).
   - Worker mati → status diubah jadi **`interrupted`** dengan error "Proses pengecekan terputus di tengah jalan." dan ditulis balik ke file (jika bisa).
2. **Stale check**: hitung umur sejak `updated_at` (fallback `started_at`). Batas per fase dari `_stale_after(data)`:
   - `phase == "whatsapp"` → `max(180, total * 35)` detik (WA lambat secara alami; proporsional dengan jumlah nomor).
   - `phase == "telegram"` → `300` detik (satu request batch, cepat).
   - fase lain → `_STALE_AFTER_SECONDS = 30 * 60` (1800 detik).
   - Melebihi batas → status **`stale`** (UI: "Pengecekan macet" dengan tombol Mulai Pengecekan).
   - Tanpa timestamp sama sekali → dianggap tidak stale (agar tidak menandai start yang baru menulis status).

Catatan: batas stale per fase ini **lebih cepat** dari `_STALE_AFTER_SECONDS`; nilai 30 menit hanya jaring pengaman untuk fase yang tidak dikenali.

## Perilaku UI (widget `_check_widget.html`)

Widget di dashboard mem-poll `GET /check/status` via HTMX `hx-trigger="every 2s"` (`hx-swap="outerHTML"`):

- **`running`** — spinner, label fase ("Memeriksa WhatsApp…"/"Memeriksa Telegram…"), progres `progress/total` dengan progress bar, dan tombol **Stop Pengecekan** (`POST /check/stop`).
- **`interrupted`** — strip error "Pengecekan terputus" + tombol **Mulai Ulang** (`POST /check`).
- **`error`** — strip error menampilkan `error` + tombol **Coba Lagi**.
- **`stale`** — strip error "Pengecekan macet" + tombol **Mulai Pengecekan**.
- **`stopped`** — strip warning "Pengecekan dihentikan" (progres terakhir) + tombol **Cek Nomor Baru**.
- **`done` / semua dicek** — strip sukses "Semua nomor sudah dicek" + tombol **Cek Nomor Baru**.
- **idle** — tombol **Cek Nomor Baru**.

`GET /check/status` dengan status `done` juga mengirim header `HX-Trigger: update-dashboard` sehingga statistik dan log dashboard di-refresh otomatis.

## Batasan & Catatan

- **Satu batch berjalan pada satu waktu**: start ganda ditolak oleh status file + `flock`. `flock` bersifat lintas proses di Linux/macOS (`fcntl`); pada platform tanpa `fcntl`, `_acquire_start_lock` mengembalikan `None` dan hanya pengecekan status file yang berlaku.
- **Profil WA tidak bisa dibagi**: jika GUI dan CLI/checker dijalankan bersamaan, keduanya berebut `runtime/wa_chrome_profile/`; lock `wa_profile.lock` membuat proses kedua gagal dengan `RuntimeError`.
- **Session Telethon checker terpisah** (`runtime/checker_session`) dari session pengiriman (`runtime/tg_checker_session`) supaya check dan send tidak saling kunci; harus di-login interaktif lebih dulu (lihat [Setup](./SETUP.md)).
- **Re-check tidak menghapus data**: `tg_user_id` lama dipertahankan bila batch baru tidak menemukan user (hasil `None`).
- **Worker error dicatat di file**, bukan hanya stdout yang tidak terbaca siapa pun.
