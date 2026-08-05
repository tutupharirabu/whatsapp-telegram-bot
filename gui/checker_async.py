#!/usr/bin/env python3
"""
GUI-safe wrapper for checker.py functions.
Runs checks in a separate process to avoid blocking FastAPI.
Tracks progress via runtime/check_status.json.
"""
import json
import multiprocessing as mp
import os
import signal
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot import db

_STATUS_PATH = Path(__file__).resolve().parent.parent / "runtime" / "check_status.json"
_LOCK_PATH = Path(__file__).resolve().parent.parent / "runtime" / "check.lock"
# Jaring pengaman terakhir: status running tanpa update apa pun melewati batas
# waktu per fase dianggap macet. Deteksi utama tetaplah verifikasi PID (lihat _pid_alive).
_STALE_AFTER_SECONDS = 30 * 60


def _acquire_start_lock():
    """Lock non-blocking antar-proses (flock) supaya dua request /check tidak spawn 2 worker."""
    try:
        import fcntl
    except ImportError:
        return None
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def _write_status(data: dict):
    """Tulis status; pertahankan started_at, pid, dan field lain dari status sebelumnya.
    Selalu perbarui updated_at agar watchdog bisa mendeteksi status yang beku."""
    existing = {}
    if _STATUS_PATH.exists():
        try:
            existing = json.loads(_STATUS_PATH.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
    merged = {**existing, **data}
    if "started_at" not in merged:
        merged["started_at"] = datetime.now(timezone.utc).isoformat()
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_PATH.write_text(json.dumps(merged, ensure_ascii=False))


def _proc_start_time(pid) -> str | None:
    """Start time proses (ps lstart). Dipakai untuk mendeteksi PID yang sudah di-reuse:
    kalau start time tidak cocok dengan yang disimpan, berarti proses asli sudah mati
    dan pid-nya dipakai proses lain — worker dianggap tidak hidup."""
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(int(pid))],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return out or None


def _pid_alive(pid, started: str | None = None) -> bool:
    """True jika proses dengan pid tersebut masih hidup DAN masih proses yang sama.
    - Dengan `started` (lstart yang direkam saat worker di-spawn): PID yang sudah
      dipakai ulang proses lain langsung dianggap mati — mencegah UI macet "running"
      padahal worker sudah tiada.
    - Tanpa `started`: fallback ke cek pid + status zombie (perilaku lama)."""
    if started:
        return _proc_start_time(pid) == started
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, PermissionError, ValueError, OSError):
        return False
    # Zombie (<defunct>) sudah mati tapi belum di-reap; os.kill(pid, 0) tetap sukses
    # untuk zombie, jadi periksa status proses secara eksplisit.
    try:
        out = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(int(pid))],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError, ValueError):
        return True  # ps tidak tersedia — fallback ke hasil os.kill di atas
    return bool(out) and "Z" not in out.upper()


def _run_check_worker(players: list[dict]):
    """
    Worker function that runs in a separate process.
    Writes status to JSON so GUI can poll progress.
    Semua exception ditangkap dan ditulis ke status file — worker TIDAK BOLEH
    mati diam-diam (penyebab utama "pengecekan macet" tanpa jejak error).
    """
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    from bot import db
    db._conn = None  # Reset SQLite cached connection for child process

    numbers = [p["nomor_normalized"] for p in players]
    total = len(numbers)

    # Rekam start time proses sendiri supaya kematian worker (termasuk PID reuse)
    # terdeteksi GUI dengan pasti.
    pid_started = _proc_start_time(os.getpid())
    _write_status({
        "status": "running", "progress": 0, "total": total, "error": "",
        "pid": os.getpid(), "pid_started": pid_started or "",
    })

    def _progress_cb(current: int, _total: int):
        """Update progress real-time agar refresh menunjukkan kemajuan, bukan angka beku."""
        _write_status({
            "status": "running", "phase": "whatsapp",
            "progress": current, "total": total, "error": "",
        })

    try:
        from cli.checker import check_telegram_batch, check_whatsapp_batch

        current_phase = "whatsapp"
        # WA check
        _write_status({"status": "running", "phase": "whatsapp", "progress": 0, "total": total, "error": ""})
        wa_results = check_whatsapp_batch(numbers, progress_cb=_progress_cb, skip_interactive=True)

        # TG check
        current_phase = "telegram"
        _write_status({"status": "running", "phase": "telegram", "progress": total, "total": total, "error": ""})
        import asyncio
        tg_results = asyncio.run(check_telegram_batch(players))

        # Save results
        current_phase = "save"
        upsert_data = []
        for player in players:
            phone = player["nomor_normalized"]
            tg_uid = tg_results.get(phone)
            if tg_uid is None:
                # Re-check tidak boleh menghapus data valid: pertahankan tg_user_id lama
                existing = db.get_player_by_phone(phone)
                if existing and existing.get("tg_user_id") is not None:
                    tg_uid = existing["tg_user_id"]
            upsert_data.append({
                "nama": player["nama"],
                "nomor_hp": player.get("nomor_hp", phone),
                "nomor_normalized": phone,
                "wa_available": wa_results.get(phone, False),
                "tg_available": tg_uid is not None,
                "tg_user_id": tg_uid,
            })
        db.upsert_players_batch(upsert_data)
        _write_status({"status": "done", "progress": total, "total": total, "error": ""})
    except Exception as e:  # noqa: BLE001 — worker tidak boleh mati tanpa status
        _write_status({
            "status": "error",
            "phase": current_phase,
            "progress": total if current_phase in ("telegram", "save") else 0,
            "total": total,
            "error": f"Worker error: {e}",
        })
        # Jangan print traceback penuh ke stdout worker yang tidak terbaca siapa pun;
        # simpan baris terakhirnya sebagai bagian dari error.
        tb = traceback.format_exc().strip().splitlines()
        if tb and len(tb) > 1:
            print(f"  [checker] Worker error: {tb[-1]}")


def get_check_status() -> dict:
    """Baca status check.
    - Status 'running' yang worker-nya sudah mati (PID tidak ditemukan / PID di-reuse
      proses lain) langsung dilaporkan 'interrupted'.
    - Status 'running' tanpa update > batas waktu per fase dilaporkan 'stale'."""
    if _STATUS_PATH.exists():
        try:
            data = json.loads(_STATUS_PATH.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        if data.get("status") == "running":
            pid = data.get("pid")
            started = data.get("pid_started") or None
            if pid and not _pid_alive(pid, started):
                # Worker mati di tengah jalan — laporkan segera, jangan biarkan UI
                # "memeriksa" palsu hingga batas waktu stale.
                data["status"] = "interrupted"
                data["error"] = "Proses pengecekan terputus di tengah jalan."
                try:
                    _write_status(data)
                except OSError:
                    pass
                return data
            is_stale = True
            updated = data.get("updated_at")
            started_at = data.get("started_at")
            ref_ts = updated or started_at
            if ref_ts:
                try:
                    ref_dt = datetime.fromisoformat(ref_ts)
                    limit = _stale_after(data)
                    is_stale = (datetime.now(timezone.utc) - ref_dt).total_seconds() > limit
                except ValueError:
                    is_stale = True
            else:
                # Tidak ada timestamp sama sekali — anggap macet.
                is_stale = False
            if is_stale:
                data["status"] = "stale"
        return data
    return {"status": "idle", "progress": 0, "total": 1, "error": ""}


def _stale_after(data: dict) -> int:
    """Batas waktu 'macet' per fase. WA lambat secara alami (Selenium per nomor),
    jadi batasnya proporsional dengan jumlah nomor; TG cepat (satu request batch)."""
    phase = data.get("phase")
    total = int(data.get("total") or 1)
    if phase == "whatsapp":
        return max(180, total * 35)
    if phase == "telegram":
        return 300
    return _STALE_AFTER_SECONDS


def _kill_tree(pid: int) -> None:
    """Kirim SIGTERM ke worker dan anak langsungnya (mis. chromedriver)."""
    targets = [pid]
    try:
        out = subprocess.run(
            ["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=2, check=False,
        ).stdout.split()
        targets += [int(c) for c in out if c.isdigit()]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    for t in targets:
        try:
            os.kill(t, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError, ValueError):
            pass
    # Beri waktu worker membersihkan diri; sisanya di-SIGKILL.
    import time
    time.sleep(1.0)
    for t in targets:
        try:
            if _pid_alive(t):
                os.kill(t, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError, ValueError):
            pass


def stop_check_background() -> dict:
    """Hentikan check yang sedang berjalan: kill worker, tandai status 'stopped'.
    Return status terakhir untuk dirender widget."""
    s = get_check_status()
    if s.get("status") == "running":
        pid = s.get("pid")
        if pid:
            try:
                _kill_tree(int(pid))
            except (ValueError, TypeError):
                pass
        s["status"] = "stopped"
        s["error"] = ""
        try:
            _write_status(s)
        except OSError:
            pass
    return s


def start_check_background():
    """
    Fire-and-forget background check.
    Fetches unscanned players from DB, spawns a process, returns immediately.
    Menolak start ganda bila masih ada check yang berjalan (status file + flock).
    """
    if get_check_status().get("status") == "running":
        print("[GUI] Check masih berjalan — lewati start ganda.")
        return

    lock = _acquire_start_lock()
    if lock is None:
        print("[GUI] Check lain sedang di-start — lewati (flock).")
        return
    try:
        # Re-check setelah lock: TOCTOU guard untuk dua request yang datang bersamaan
        if get_check_status().get("status") == "running":
            print("[GUI] Check masih berjalan — lewati start ganda (post-lock).")
            return

        players = db.get_unscanned_players()
        if not players:
            print("[GUI] No unscanned players to check.")
            return

        _write_status({"status": "running", "progress": 0, "total": len(players), "error": ""})
        process = mp.Process(target=_run_check_worker, args=(players,))
        process.start()
        # Simpan PID + start time worker agar kematian proses di tengah cek bisa
        # terdeteksi — termasuk kasus PID di-reuse oleh proses lain.
        _write_status({
            "status": "running", "progress": 0, "total": len(players), "error": "",
            "pid": process.pid,
            "pid_started": _proc_start_time(process.pid) or "",
        })
        print(f"[GUI] Started background check for {len(players)} players (PID: {process.pid}).")
    finally:
        try:
            os.close(lock)  # tutup fd → flock terlepas
        except OSError:
            pass
