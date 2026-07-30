#!/usr/bin/env python3
"""
GUI-safe wrapper for checker.py functions.
Runs checks in a separate process to avoid blocking FastAPI.
"""
import multiprocessing as mp
from typing import List, Dict
import sys
import os

# Ensure bot module is importable
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from bot import db


def _run_check_worker(players: List[dict]):
    """
    Worker function that runs in a separate process.
    Takes players = [{nama, nomor_hp, nomor_normalized}].
    Calls check_all, then upserts results into players table.
    """
    from cli.checker import check_whatsapp_batch, check_telegram_batch
    
    numbers = [p["nomor_normalized"] for p in players]
    
    print(f"[Worker] Checking {len(numbers)} numbers via WhatsApp...")
    wa_results = check_whatsapp_batch(numbers, skip_interactive=True)
    
    print(f"[Worker] Checking {len(numbers)} numbers via Telegram...")
    tg_results = check_telegram_batch(numbers)
    
    # Build upsert payload
    upsert_data = []
    for player in players:
        phone = player["nomor_normalized"]
        upsert_data.append({
            "nama": player["nama"],
            "nomor_hp": player.get("nomor_hp", phone),
            "nomor_normalized": phone,
            "wa_available": wa_results.get(phone, False),
            "tg_available": tg_results.get(phone, False),
            "tg_user_id": None
        })
    
    # Write to DB
    db.upsert_players_batch(upsert_data)
    print(f"[Worker] Upserted {len(upsert_data)} players to DB.")


def start_check_background():
    """
    Fire-and-forget background check.
    Fetches unscanned players from DB, spawns a process, returns immediately.
    """
    players = db.get_unscanned_players()
    if not players:
        print("[GUI] No unscanned players to check.")
        return
    
    # Start process and detach
    process = mp.Process(target=_run_check_worker, args=(players,))
    process.start()
    # Don't join — let it run independently
    print(f"[GUI] Started background check for {len(players)} players (PID: {process.pid}).")
