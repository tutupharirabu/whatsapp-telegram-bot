# Setup & Menjalankan

Panduan menyiapkan environment, konfigurasi, dan menjalankan aplikasi (GUI maupun CLI).

Baca juga: [Arsitektur](./ARCHITECTURE.md) · [Model Keamanan](./SECURITY.md) · [Referensi HTTP API](./API.md).

## Persyaratan Sistem

- **Python 3.9+** (venv/conda disarankan). Workflow CodeQL di repositori memakai Python 3.11.
- **Google Chrome** — driver dikelola otomatis oleh `webdriver-manager` (versi Chrome dan ChromeDriver harus cocok; `webdriver-manager` menangani ini).
- **Akun Telegram** — API ID & API hash dari [my.telegram.org](https://my.telegram.org), dan nomor telepon akun.
- **Akun WhatsApp** — login via QR WhatsApp Web (session disimpan di `runtime/wa_chrome_profile/`).

## 1. Klon & Siapkan Virtual Environment

```shell
git clone https://github.com/tutupharirabu/whatsapp-telegram-bot.git
cd whatsapp-telegram-bot

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

Install dependensi:

```shell
pip install -r requirements.txt
```

Isi `requirements.txt` (root): `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `jinja2>=3.1`, `python-multipart>=0.0.9`, `python-telegram-bot==21.4`, `python-dotenv==1.0.1`, `telethon>=1.36`, `phonenumbers>=8.13`, `selenium>=4.15`, `webdriver-manager>=4.0`.

## 2. Konfigurasi Environment (.env)

Salin contoh konfigurasi:

```shell
cp .env.example .env
```

Lalu lengkapi nilai-nilainya. Variabel yang didukung (dari `.env.example` dan kode):

| Variabel | Diperlukan | Keterangan |
|---|---|---|
| `TELEGRAM_API_ID` | Ya (untuk TG) | API ID akun Telegram (my.telegram.org) |
| `TELEGRAM_API_HASH` | Ya (untuk TG) | API hash akun Telegram |
| `TELEGRAM_PHONE` | Ya (untuk TG) | Nomor akun Telegram (format internasional, contoh `+628123456789`); dipakai juga untuk skip nomor sendiri di `cli/send.py` |
| `TELEGRAM_BOT_TOKEN` | Opsional | Token Bot API dari @BotFather, hanya untuk jalur kirim `send_telegram_message` (Bot API) |
| `FASIL_NAME` | Ya (untuk template) | Nama fasilitator, dipakai placeholder `{nama_fasil}` (default di kode: `Irfan Zharauri`) |
| `FASIL_CODE` | Ya (untuk template) | Kode fasilitator, dipakai placeholder `{kode_fasil}` (default di kode: `GCAF26-ID-9MJ-EP6`) |
| `FASIL_NAMES` | Opsional | Daftar nama fasil dipisah koma untuk `cli/extract_facilitators.py` |
| `DASHBOARD_TOKEN` | **WAJIB untuk akses jarak jauh** | Token akses dashboard. Tanpa token, server hanya bind `127.0.0.1` |
| `HOST` | Opsional | Host bind; default `127.0.0.1` (tanpa token) atau `0.0.0.0` (dengan token) |
| `GUI_RELOAD` | Opsional (dev) | `1`/`true`/`yes` untuk auto-reload uvicorn (hanya untuk pengembangan) |
| `WA_HEADLESS` | Opsional | `1` = mode headless Chrome |
| `WA_NONINTERACTIVE` | Opsional | `1` = jangan blok di `input()` saat WA belum login (dipakai GUI/CI) |

Membuat token dashboard:

```shell
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Tempel hasilnya ke `DASHBOARD_TOKEN` di `.env`. **Jangan commit `.env` ke git** (sudah ada di `.gitignore`).

## 3. Menjalankan Dashboard (GUI)

Jalankan **dari folder project ini**, bukan dari salinan folder lain (mis. `/tmp/...`) — salinan memiliki DB/status/session terpisah dan membuat pengecekan tampak macet karena state-nya terbelah.

```shell
python gui/app.py
```

Ini setara dengan menjalankan uvicorn:

```shell
uvicorn gui.app:app --host 127.0.0.1 --port 8000
```

Akses di browser: `http://localhost:8000`.

Keterangan mode `__main__` di `gui/app.py`:

- `default_host = "127.0.0.1"` bila `DASHBOARD_TOKEN` kosong, selain itu `"0.0.0.0"`.
- `HOST` env menimpa default host.
- Port selalu `8000` (belum ada env `PORT`).
- `GUI_RELOAD=1` mengaktifkan auto-reload; **jangan** dipakai bersamaan dengan fitur pengecekan (reloader men-spawn server, worker `multiprocessing.Process` ikut mengeksekusi ulang `uvicorn.run`).

Pada jalankan pertama:

1. Buka browser Chrome yang muncul dari Selenium (profil `runtime/wa_chrome_profile/`) dan **scan QR code WhatsApp Web**.
2. Jalankan login session Telethon sekali (lihat di bawah), karena session `checker_session` dan `tg_checker_session` harus sudah ter-autorisasi untuk cek & kirim TG.

Jika `DASHBOARD_TOKEN` diset, browser akan diarahkan ke halaman `/login` untuk memasukkan token (cookie `gcaf_token` berlaku 7 hari).

### Login session Telegram (sekali saja)

Fase Telegram pada pengecekan memakai session Telethon `runtime/checker_session` dan **tidak akan memanggil `input()`** (dengan sengaja, agar worker tidak menggantung). Login interaktif dilakukan lewat CLI, misalnya `cli/send.py` atau dengan membuat session terlebih dahulu:

```shell
python cli/send.py source/data_peserta.csv -m "Tes" --dry-run
```

atau jalankan proses yang memanggil `TelegramClient.start()` interaktif dengan nomor `TELEGRAM_PHONE` (2FA diminta bila aktif). Session `runtime/tg_checker_session` dipakai pengiriman TG (`bot/telegram_bot.py`), sedangkan `runtime/checker_session` dipakai cek nomor (`cli/checker.py`) — keduanya terpisah agar tidak saling kunci.

## 4. Menjalankan CLI

### Pengecekan nomor (verifikasi WA & TG)

```shell
python cli/checker.py
```

`cli/checker.py` pada `__main__` menerima nomor sebagai argumen:

```shell
python cli/checker.py 6281234567890 6289876543210
```

Fungsi batch (`check_whatsapp_batch`, `check_telegram_batch`, `check_all`) diimpor juga oleh worker GUI.

### Pengiriman pesan massal

```shell
python cli/send.py source/data_peserta.csv --mode join-full --wa-only
```

Flag penting: `--mode <formal|kasual|remind-redeem|remind-gear|remind-both|join-redeem|join-gear|join-full>`, `-m/--message`, `--wa-only`, `--tg-only`, `--delay N` (default 5 detik), `--dry-run`, `--force` (lewati dedup), `--check-file hasil.json` (pakai hasil cek sebelumnya). Lihat `python cli/send.py --help` untuk daftar lengkap.

### Skrip pendukung

```shell
python cli/check_reminders.py            # scan report → source/reminders.csv
python cli/extract_facilitators.py       # ekstrak fasilitator → source/fasilitators.csv
./scripts/backup_runtime.sh /path/ke/media-encrypted   # backup runtime/
```

## 5. Backup Runtime

Data penting (DB SQLite, session Telegram, profil Chrome WA) berada di `runtime/` dan bersifat PII/kredensial. Skrip backup:

```shell
./scripts/backup_runtime.sh /path/ke/media-encrypted
```

Skrip memakai `sqlite3 .backup` (WAL-aware) bila CLI tersedia, menyalin session/profil, dan mempertahankan 7 backup terakhir. Simpan target di media terenkripsi (FileVault / encrypted volume).

## Masalah Umum

### Selenium / ChromeDriver

- **Chrome tidak bisa start / versi tidak cocok**: driver di-install otomatis oleh `webdriver-manager`; pastikan Chrome ter-install dan versinya didukung. Hapus cache driver jika perlu.
- **WA terus minta login QR**: jangan hapus `runtime/wa_chrome_profile/`; pastikan permission benar. Jangan jalankan GUI dan CLI/checker bersamaan — keduanya berbagi profil yang sama (ada lock otomatis di `runtime/wa_profile.lock`; proses kedua gagal dengan `RuntimeError`).

### Telethon

- **`TELEGRAM_API_ID / TELEGRAM_API_HASH tidak diatur`**: isi `.env`.
- **Session checker belum login**: jalankan login interaktif sekali (lihat bagian Login session Telegram di atas).
- **FloodWait**: kena rate limit Telegram; tunggu sesuai `e.seconds`. `check_telegram_batch` menangkap `FloodWaitError` dan mengembalikan hasil parsial.
- **2FA (`SessionPasswordNeededError`)**: login dulu secara interaktif dengan password.

### Port / Server

- **Port 8000 sudah terpakai**: hentikan proses lain, atau ubah port dengan menjalankan uvicorn langsung (`uvicorn gui.app:app --port 8001`). Variabel env `PORT` belum didukung.
- **Pengecekan tampak macet ("Memeriksa…" terus)**: worker berjalan di proses terpisah (`runtime/check_status.json` berisi `pid` + `pid_started`). Jika proses mati di tengah jalan, widget otomatis menampilkan **"Pengecekan terputus"** dan menawarkan tombol Mulai Ulang (tidak perlu menunggu 30 menit). Pastikan server dijalankan dari folder project.
- **`TypeError: unhashable type: 'dict'` di Dashboard**: masalah kompatibilitas `Jinja2Templates` FastAPI/Starlette; pastikan route memakai signature `TemplateResponse(request, "name.html", context)`.

### CSV / Import

- **Error CSV DictReader**: pastikan file export Google Sheets konsisten format kolomnya (contoh: tanpa double-quote `"..."` ekstra yang tidak di-escape). Pembaca CSV proyek (`read_csv_rows`, `_unwrap_row` di `bot/utils.py` dan `bot/db.py`) sudah menangani baris yang dibungkus satu lapis quote tambahan.
- **Kolom tidak dikenali**: nama kolom memakai alias — lihat `COLUMN_ALIASES` di `bot/utils.py` (contoh: `Nama Peserta`, `Nomor HP Peserta`, `Email Peserta`).

## Referensi

- Variabel env: `.env.example` di root repositori.
- Skema tabel: [Model Data](./DATA_MODEL.md).
- Menjalankan dashboard untuk akses jarak jauh dengan aman: [Model Keamanan](./SECURITY.md).
