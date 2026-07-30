#!/usr/bin/env python3
"""
SQLite database module for GCAF 2026 Auto Messenger.
All persistent data — players, check results, send logs, reminders, daily reports.
"""

import csv
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).parent.parent / "runtime" / "gcaf.db"

_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def dict_from_row(row: sqlite3.Row) -> dict:
    return dict(row) if row else None


def dicts_from_rows(rows: List[sqlite3.Row]) -> List[dict]:
    return [dict(r) for r in rows]


def normalize_nama(name: str) -> str:
    """Capitalize first letter of each word, preserve dots/hyphens/apostrophes."""
    if not name:
        return ""
    parts = re.split(r'(\s+)', name.strip())
    normalized = []
    for part in parts:
        if part.strip():
            normalized.append(part[0].upper() + part[1:].lower() if part[0].isalpha() else part)
        else:
            normalized.append(part)
    return "".join(normalized)


# ═══════════════════════════════════════════════════════════════
# SCHEMA INIT
# ═══════════════════════════════════════════════════════════════

def init_db():
    db = get_conn()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            nomor_hp TEXT NOT NULL,
            nomor_normalized TEXT NOT NULL UNIQUE,
            wa_available INTEGER DEFAULT 0,
            tg_available INTEGER DEFAULT 0,
            tg_user_id INTEGER,
            tg_joined INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT NOT NULL,
            email TEXT,
            nomor_hp TEXT NOT NULL,
            nomor_normalized TEXT NOT NULL,
            status_redeem TEXT,
            lencana_gear TEXT,
            milestone TEXT,
            bonus_milestone TEXT,
            status_verifikasi_ai_agent TEXT,
            jumlah_lencana INTEGER DEFAULT 0,
            jumlah_arcade_game INTEGER DEFAULT 0,
            nama_lencana TEXT,
            nama_arcade_game TEXT,
            report_date TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(nomor_normalized, report_date)
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER REFERENCES players(id),
            nama TEXT NOT NULL,
            nomor_hp TEXT NOT NULL,
            reminder_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            sent_at TEXT
        );

        CREATE TABLE IF NOT EXISTS send_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            nama TEXT,
            nomor_hp TEXT,
            wa_available INTEGER DEFAULT 0,
            tg_available INTEGER DEFAULT 0,
            wa_sent INTEGER DEFAULT 0,
            tg_sent INTEGER DEFAULT 0,
            wa_error TEXT,
            tg_error TEXT,
            mode TEXT,
            batch_id TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS manual_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama TEXT,
            nomor_hp TEXT,
            nomor_normalized TEXT,
            message TEXT,
            wa_link TEXT,
            reason TEXT,
            mode TEXT,
            batch_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            sent_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_players_phone ON players(nomor_normalized);
        CREATE INDEX IF NOT EXISTS idx_manual_queue_status ON manual_queue(status);
        CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);
        CREATE INDEX IF NOT EXISTS idx_send_logs_batch ON send_logs(batch_id);
        CREATE INDEX IF NOT EXISTS idx_daily_reports_phone ON daily_reports(nomor_normalized);
    """)

    # Migrasi idempotent: kolom msg_hash untuk dedup skip-sudah-terkirim
    cols = {r["name"] for r in db.execute("PRAGMA table_info(send_logs)").fetchall()}
    if "msg_hash" not in cols:
        db.execute("ALTER TABLE send_logs ADD COLUMN msg_hash TEXT")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_send_logs_dedup ON send_logs(nomor_hp, msg_hash)"
    )
    db.commit()

    # Normalize nama pada data yang sudah ada (migrasi)
    for table in ("players", "daily_reports", "reminders", "send_logs"):
        rows = db.execute(f"SELECT id, nama FROM {table}").fetchall()
        for row in rows:
            normalized = normalize_nama(row["nama"] or "")
            if normalized and normalized != row["nama"]:
                db.execute(f"UPDATE {table} SET nama = ? WHERE id = ?", (normalized, row["id"]))
    db.commit()


# ═══════════════════════════════════════════════════════════════
# PLAYERS
# ═══════════════════════════════════════════════════════════════

def get_player_by_phone(nomor_normalized: str) -> Optional[dict]:
    db = get_conn()
    row = db.execute(
        "SELECT * FROM players WHERE nomor_normalized = ?", (nomor_normalized,)
    ).fetchone()
    return dict_from_row(row)


def upsert_player(
    nama: str, nomor_hp: str, nomor_normalized: str,
    wa_available: bool = False, tg_available: bool = False, tg_user_id: int = None,
) -> int:
    db = get_conn()
    nama = normalize_nama(nama)
    now = datetime.now(timezone.utc).isoformat()
    existing = db.execute(
        "SELECT id FROM players WHERE nomor_normalized = ?", (nomor_normalized,)
    ).fetchone()

    if existing:
        db.execute(
            """UPDATE players SET
                nama = ?, nomor_hp = ?, wa_available = ?, tg_available = ?,
                tg_user_id = ?, updated_at = ?
               WHERE id = ?""",
            (nama, nomor_hp, int(wa_available), int(tg_available), tg_user_id, now, existing["id"]),
        )
        db.commit()
        return existing["id"]
    else:
        cur = db.execute(
            """INSERT INTO players (nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nama, nomor_hp, nomor_normalized, int(wa_available), int(tg_available), tg_user_id, now, now),
        )
        db.commit()
        return cur.lastrowid


def upsert_players_batch(players: List[dict]):
    """Bulk upsert from check results. players = [{nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id}]."""
    for p in players:
        upsert_player(
            nama=p["nama"],
            nomor_hp=p.get("nomor_hp", ""),
            nomor_normalized=p.get("nomor_normalized", ""),
            wa_available=p.get("wa_available", False),
            tg_available=p.get("tg_available", False),
            tg_user_id=p.get("tg_user_id"),
        )


def get_players_summary(search: str = "", limit: int = 200, offset: int = 0) -> List[dict]:
    """Semua peserta dari daily_reports (source of truth), di-LEFT-JOIN dengan players untuk WA/TG status."""
    db = get_conn()
    if search:
        rows = db.execute(
            """SELECT
                dr.nama, dr.email, dr.nomor_hp, dr.nomor_normalized,
                dr.status_redeem, dr.lencana_gear,
                COALESCE(p.wa_available, 0) as wa_available,
                COALESCE(p.tg_available, 0) as tg_available,
                p.tg_user_id, COALESCE(p.tg_joined, 0) as tg_joined, p.updated_at as checked_at,
                dr.created_at,
                (SELECT sl.wa_error FROM send_logs sl
                 WHERE sl.nomor_hp = dr.nomor_hp AND sl.wa_error IS NOT NULL AND sl.wa_error != ''
                   AND sl.wa_error NOT LIKE 'skip:%'
                 ORDER BY sl.timestamp DESC LIMIT 1) as wa_error
               FROM daily_reports dr
               LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
               WHERE dr.nama LIKE ? OR dr.nomor_hp LIKE ?
               GROUP BY dr.nomor_normalized
               ORDER BY dr.nama COLLATE NOCASE
               LIMIT ? OFFSET ?""",
            (f"%{search}%", f"%{search}%", limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT
                dr.nama, dr.email, dr.nomor_hp, dr.nomor_normalized,
                dr.status_redeem, dr.lencana_gear,
                COALESCE(p.wa_available, 0) as wa_available,
                COALESCE(p.tg_available, 0) as tg_available,
                p.tg_user_id, COALESCE(p.tg_joined, 0) as tg_joined, p.updated_at as checked_at,
                dr.created_at,
                (SELECT sl.wa_error FROM send_logs sl
                 WHERE sl.nomor_hp = dr.nomor_hp AND sl.wa_error IS NOT NULL AND sl.wa_error != ''
                   AND sl.wa_error NOT LIKE 'skip:%'
                 ORDER BY sl.timestamp DESC LIMIT 1) as wa_error
               FROM daily_reports dr
               LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
               GROUP BY dr.nomor_normalized
               ORDER BY dr.nama COLLATE NOCASE
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    return dicts_from_rows(rows)


def get_player_summary_by_phone(nomor_normalized: str) -> Optional[dict]:
    """Satu baris ringkasan peserta (sama shape dengan get_players_summary) untuk re-render row."""
    db = get_conn()
    row = db.execute(
        """SELECT
            dr.nama, dr.email, dr.nomor_hp, dr.nomor_normalized,
            dr.status_redeem, dr.lencana_gear,
            COALESCE(p.wa_available, 0) as wa_available,
            COALESCE(p.tg_available, 0) as tg_available,
            p.tg_user_id, COALESCE(p.tg_joined, 0) as tg_joined, p.updated_at as checked_at,
            dr.created_at,
            (SELECT sl.wa_error FROM send_logs sl
             WHERE sl.nomor_hp = dr.nomor_hp AND sl.wa_error IS NOT NULL AND sl.wa_error != ''
               AND sl.wa_error NOT LIKE 'skip:%'
             ORDER BY sl.timestamp DESC LIMIT 1) as wa_error
           FROM daily_reports dr
           LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
           WHERE dr.nomor_normalized = ?
           GROUP BY dr.nomor_normalized""",
        (nomor_normalized,),
    ).fetchone()
    return dict_from_row(row)


def toggle_tg_joined(nomor_normalized: str) -> int:
    """Flip tg_joined bit (0<->1) untuk satu peserta. Return nilai baru."""
    db = get_conn()
    row = db.execute(
        "SELECT tg_joined FROM players WHERE nomor_normalized = ?", (nomor_normalized,)
    ).fetchone()
    new_value = 0 if (row and row["tg_joined"]) else 1
    db.execute(
        "UPDATE players SET tg_joined = ? WHERE nomor_normalized = ?",
        (new_value, nomor_normalized),
    )
    db.commit()
    return new_value


def get_players_total_from_reports() -> int:
    """Total peserta unik dari semua daily_reports."""
    db = get_conn()
    return db.execute("SELECT COUNT(DISTINCT nomor_normalized) FROM daily_reports").fetchone()[0]


def get_players_unused_numbers() -> List[str]:
    """Nomor dari reports yang belum pernah dicek (WA/TG belum ada di players)."""
    db = get_conn()
    rows = db.execute("""
        SELECT DISTINCT dr.nomor_normalized
        FROM daily_reports dr
        LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
        WHERE p.id IS NULL
    """).fetchall()
    return [r["nomor_normalized"] for r in rows]


def get_players_count() -> int:
    db = get_conn()
    return db.execute("SELECT COUNT(*) FROM players").fetchone()[0]


def get_wa_registered_count() -> int:
    db = get_conn()
    return db.execute("SELECT COUNT(*) FROM players WHERE wa_available = 1").fetchone()[0]


def get_tg_registered_count() -> int:
    db = get_conn()
    return db.execute("SELECT COUNT(*) FROM players WHERE tg_available = 1").fetchone()[0]


# ═══════════════════════════════════════════════════════════════
# DAILY REPORTS
# ═══════════════════════════════════════════════════════════════

def _extract_report_date(filename: str) -> str:
    """Extract date from filename like 'GCAF26-ID-9MJ-EP6 [28 Jul].csv'."""
    match = re.search(r'\[(\d{1,2}\s+\w{3})\]', filename)
    if match:
        return match.group(1)
    return ""


def _unwrap_row(line: str, n_cols: int) -> Optional[list]:
    """Parse satu baris CSV mentah. Beberapa export Google Sheets membungkus
    seluruh baris dengan satu lapis quote tambahan (tiap quote internal jadi ""),
    sehingga csv standar cuma baca 1 kolom raksasa. Deteksi & buka bungkusnya."""
    row = next(csv.reader([line]), [])
    if len(row) == n_cols:
        return row
    stripped = line.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        inner = stripped[1:-1].replace('""', '"')
        row = next(csv.reader([inner]), [])
        if len(row) == n_cols:
            return row
    return None


def import_daily_report(csv_path: str) -> tuple:
    """Import daily report CSV ke daily_reports. Return (jumlah baris di-import, jumlah baris di-skip karena rusak)."""
    db = get_conn()
    report_date = _extract_report_date(os.path.basename(csv_path))
    now = datetime.now(timezone.utc).isoformat()

    with open(csv_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    if not lines:
        return 0, 0
    header = next(csv.reader([lines[0]]), [])
    n_cols = len(header)

    count = 0
    skipped = 0
    for raw_line in lines[1:]:
        if not raw_line.strip():
            continue
        fields = _unwrap_row(raw_line, n_cols)
        if fields is None:
            skipped += 1
            continue
        row = dict(zip(header, fields))

        nama = normalize_nama((row.get("Nama Peserta") or "").strip())
        hp = (row.get("Nomor HP Peserta") or "").strip()
        if not hp:
            continue

        from bot.utils import normalize_phone
        normalized = normalize_phone(hp)

        db.execute(
            """INSERT INTO daily_reports
               (nama, email, nomor_hp, nomor_normalized, status_redeem, lencana_gear,
                milestone, bonus_milestone, status_verifikasi_ai_agent,
                jumlah_lencana, jumlah_arcade_game, nama_lencana, nama_arcade_game,
                report_date, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(nomor_normalized, report_date) DO UPDATE SET
                   nama=excluded.nama, email=excluded.email, nomor_hp=excluded.nomor_hp,
                   status_redeem=excluded.status_redeem, lencana_gear=excluded.lencana_gear,
                   milestone=excluded.milestone, bonus_milestone=excluded.bonus_milestone,
                   status_verifikasi_ai_agent=excluded.status_verifikasi_ai_agent,
                   jumlah_lencana=excluded.jumlah_lencana, jumlah_arcade_game=excluded.jumlah_arcade_game,
                   nama_lencana=excluded.nama_lencana, nama_arcade_game=excluded.nama_arcade_game""",
            (
                nama,
                (row.get("Email Peserta") or "").strip(),
                hp,
                normalized,
                (row.get("Status Redeem Kode Akses") or "").strip(),
                (row.get("Lencana Digital GEAR yang diraih") or "").strip(),
                (row.get("Milestone yang diraih") or "").strip(),
                (row.get("Bonus Milestone yang diraih") or "").strip(),
                (row.get("Status Verifikasi AI Agent") or "").strip(),
                int((row.get("Jumlah Lencana Keahlian yang diselesaikan") or "0") or 0),
                int((row.get("Jumlah Arcade Game yang diselesaikan") or "0") or 0),
                (row.get("Nama Lencana Keahlian yang diselesaikan") or "").strip(),
                (row.get("Nama Arcade Game yang diselesaikan") or "").strip(),
                report_date,
                now,
            ),
        )

        # Auto-upsert ke players supaya muncul di list (WA/TG status default 0)
        db.execute(
            """INSERT INTO players (nama, nomor_hp, nomor_normalized, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(nomor_normalized) DO UPDATE SET nama=excluded.nama, nomor_hp=excluded.nomor_hp""",
            (nama, hp, normalized, now, now),
        )
        count += 1

    db.commit()
    return count, skipped


def get_daily_reports(search: str = "", limit: int = 200, offset: int = 0) -> List[dict]:
    db = get_conn()
    if search:
        rows = db.execute(
            """SELECT * FROM daily_reports
               WHERE nama LIKE ? OR nomor_hp LIKE ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (f"%{search}%", f"%{search}%", limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM daily_reports ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return dicts_from_rows(rows)


def get_daily_reports_count() -> int:
    db = get_conn()
    return db.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0]


# ═══════════════════════════════════════════════════════════════
# SEND LOGS
# ═══════════════════════════════════════════════════════════════

def insert_send_log(entry: dict, batch_id: str = None) -> int:
    db = get_conn()
    nomor_hp = entry.get("nomor_hp", "")

    # Resolve player_id
    from bot.utils import normalize_phone
    normalized = normalize_phone(nomor_hp) if nomor_hp else ""
    player_row = db.execute(
        "SELECT id FROM players WHERE nomor_normalized = ?", (normalized,)
    ).fetchone() if normalized else None

    cur = db.execute(
        """INSERT INTO send_logs (player_id, nama, nomor_hp, wa_available, tg_available,
            wa_sent, tg_sent, wa_error, tg_error, mode, batch_id, timestamp, msg_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            player_row["id"] if player_row else None,
            normalize_nama(entry.get("nama", "")),
            nomor_hp,
            int(entry.get("wa_available", False)),
            int(entry.get("tg_available", False)),
            int(entry.get("wa_sent", False)),
            int(entry.get("tg_sent", False)),
            entry.get("wa_error"),
            entry.get("tg_error"),
            entry.get("mode", ""),
            batch_id or entry.get("batch_id", ""),
            entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
            entry.get("msg_hash", ""),
        ),
    )
    db.commit()
    return cur.lastrowid


def msg_fingerprint(msg_template: str) -> str:
    """Hash template pesan (SEBELUM personalisasi) → satu kampanye = satu hash.
    Placeholder {nama} dst dibuang supaya nama tiap penerima tak pecahkan dedup."""
    import hashlib
    base = re.sub(r"\{[^}]*\}", "", msg_template or "")
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def get_sent_set(platform: str, msg_hash: str) -> set:
    """Set nomor_normalized yang SUDAH sukses terkirim di platform ini untuk pesan ini.
    platform: 'wa' | 'tg'. Cocokkan by phone, bukan nama."""
    col = "wa_sent" if platform == "wa" else "tg_sent"
    db = get_conn()
    rows = db.execute(
        f"SELECT DISTINCT nomor_hp FROM send_logs WHERE {col}=1 AND msg_hash=?",
        (msg_hash,),
    ).fetchall()
    from bot.utils import normalize_phone
    return {normalize_phone(r["nomor_hp"]) for r in rows if r["nomor_hp"]}


def insert_send_logs_batch(entries: List[dict], batch_id: str = None) -> int:
    bid = batch_id or uuid.uuid4().hex[:8]
    count = 0
    for entry in entries:
        entry["batch_id"] = bid
        insert_send_log(entry, bid)
        count += 1
    return count


def get_send_logs(limit: int = 200, offset: int = 0, batch_id: str = None) -> List[dict]:
    db = get_conn()
    if batch_id:
        rows = db.execute(
            "SELECT * FROM send_logs WHERE batch_id = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (batch_id, limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM send_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return dicts_from_rows(rows)


def get_send_logs_count() -> int:
    db = get_conn()
    return db.execute("SELECT COUNT(*) FROM send_logs").fetchone()[0]


def get_recent_logs(limit: int = 5) -> List[dict]:
    """Get N most recent send logs. Used for dashboard preview."""
    return get_send_logs(limit=limit)


# ═══════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════

def get_tg_joined_count() -> int:
    db = get_conn()
    return db.execute("SELECT COUNT(*) FROM players WHERE tg_joined = 1").fetchone()[0]


def get_dashboard_stats() -> dict:
    return {
        "total_players": get_players_count(),
        "wa_registered": get_wa_registered_count(),
        "tg_registered": get_tg_registered_count(),
        "tg_joined_count": get_tg_joined_count(),
        "total_reports": get_daily_reports_count(),
        "total_logs": get_send_logs_count(),
        "unscanned_count": len(get_players_unused_numbers()),
        "recent_logs": get_recent_logs(5),
    }
