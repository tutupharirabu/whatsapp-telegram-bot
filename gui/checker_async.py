#!/usr/bin/env python3
"""
GUI-safe wrapper for checker.py functions.
Runs checks in a separate process to avoid blocking FastAPI.
Tracks progress via runtime/check_status.json.
"""
import json
import multiprocessing as mp
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot import db

_STATUS_PATH = Path(__file__).resolve().parent.parent / "runtime" / "check_status.json"
_LOCK_PATH = Path(__file__).resolve().parent.parent / "runtime" / "check.lock"
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
    """Tulis status; 'started_at' ditetapkan sekali di payload pertama pengecekan."""
    if "started_at" not in data:
        data["started_at"] = datetime.now(timezone.utc).isoformat()
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_PATH.write_text(json.dumps(data, ensure_ascii=False))


def _run_check_worker(players: list[dict]):
    """
    Worker function that runs in a separate process.
    Writes status to JSON so GUI can poll progress.
    """
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    from bot import db
    db._conn = None  # Reset SQLite cached connection for child process

    from cli.checker import check_telegram_batch, check_whatsapp_batch

    numbers = [p["nomor_normalized"] for p in players]
    total = len(numbers)
    _write_status({"status": "running", "progress": 0, "total": total, "error": ""})

    # WA check
    _write_status({"status": "running", "phase": "whatsapp", "progress": 0, "total": total, "error": ""})
    try:
        wa_results = check_whatsapp_batch(numbers, skip_interactive=True)
    except (ValueError, OSError, RuntimeError) as e:
        _write_status({"status": "error", "phase": "whatsapp", "progress": 0, "total": total, "error": f"WA: {e}"})
        return

    # TG check
    _write_status({"status": "running", "phase": "telegram", "progress": total, "total": total, "error": ""})
    try:
        import asyncio
        tg_results = asyncio.run(check_telegram_batch(players))
    except (ValueError, OSError, RuntimeError) as e:
        _write_status({"status": "error", "phase": "telegram", "progress": total, "total": total, "error": f"TG: {e}"})
        return

    # Save results
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


def get_check_status() -> dict:
    """Baca status check. Status 'running' yang >30 menit dilaporkan sebagai 'stale'."""
    if _STATUS_PATH.exists():
        try:
            data = json.loads(_STATUS_PATH.read_text())
        except (OSError, ValueError, json.JSONDecodeError):
            data = {}
        if data.get("status") == "running":
            is_stale = True
            started = data.get("started_at")
            if started:
                try:
                    started_dt = datetime.fromisoformat(started)
                    is_stale = (datetime.now(timezone.utc) - started_dt).total_seconds() > _STALE_AFTER_SECONDS
                except ValueError:
                    is_stale = True
            if is_stale:
                data["status"] = "stale"
        return data
    return {"status": "idle", "progress": 0, "total": 1, "error": ""}


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
        print(f"[GUI] Started background check for {len(players)} players (PID: {process.pid}).")
    finally:
        try:
            os.close(lock)  # tutup fd → flock terlepas
        except OSError:
            pass
