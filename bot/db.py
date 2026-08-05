#!/usr/bin/env python3
"""
SQLite database module for GCAF 2026 Auto Messenger.
All persistent data — players, check results, send logs, reminders, daily reports.
"""
from __future__ import annotations

import csv
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "runtime" / "gcaf.db"

_conn: sqlite3.Connection | None = None
_lock = threading.RLock()


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def dict_from_row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def dicts_from_rows(rows: list[sqlite3.Row]) -> list[dict]:
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

_TIMESTAMP_COLS = {
    "players": ("created_at", "updated_at"),
    "daily_reports": ("created_at",),
    "send_logs": ("timestamp",),
    "reminders": ("created_at", "sent_at"),
    "manual_queue": ("created_at", "sent_at"),
}


def init_db():
    with _lock:
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

        if db.execute("PRAGMA user_version").fetchone()[0] < 1:
            # Normalize nama pada data yang sudah ada (migrasi)
            for table in ("players", "daily_reports", "reminders", "send_logs"):
                rows = db.execute(f"SELECT id, nama FROM {table}").fetchall()
                for row in rows:
                    normalized = normalize_nama(row["nama"] or "")
                    if normalized and normalized != row["nama"]:
                        db.execute(f"UPDATE {table} SET nama = ? WHERE id = ?", (normalized, row["id"]))

            # Migrasi: Set updated_at ke NULL untuk pemain yang di-auto-insert tapi belum pernah dicek
            db.execute("""
                UPDATE players 
                SET updated_at = NULL 
                WHERE updated_at = created_at AND wa_available = 0 AND tg_available = 0 AND tg_user_id IS NULL
            """)

            # Unifikasi timestamp lama (spasi) ke format ISO (T)
            for table, cols in _TIMESTAMP_COLS.items():
                for col in cols:
                    db.execute(
                        f"UPDATE {table} SET {col} = replace({col}, ' ', 'T')"
                        f" WHERE {col} LIKE '____-__-__ __:__:__%'"
                    )

            db.execute("PRAGMA user_version = 1")
            db.commit()


# ═══════════════════════════════════════════════════════════════
# PLAYERS
# ═══════════════════════════════════════════════════════════════

def get_player_by_phone(nomor_normalized: str) -> dict | None:
    db = get_conn()
    row = db.execute(
        "SELECT * FROM players WHERE nomor_normalized = ?", (nomor_normalized,)
    ).fetchone()
    return dict_from_row(row)


def upsert_player(
    nama: str, nomor_hp: str, nomor_normalized: str,
    wa_available: bool = False, tg_available: bool = False, tg_user_id: int | None = None,
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
        return int(existing["id"])
    else:
        cur = db.execute(
            """INSERT INTO players (nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nama, nomor_hp, nomor_normalized, int(wa_available), int(tg_available), tg_user_id, now, now),
        )
        db.commit()
        return int(cur.lastrowid or 0)


def upsert_players_batch(players: list[dict[str, Any]]):
    """Bulk upsert from check results. players = [{nama, nomor_hp, nomor_normalized, wa_available, tg_available, tg_user_id}]"""
    for p in players:
        upsert_player(
            nama=p["nama"],
            nomor_hp=p.get("nomor_hp", ""),
            nomor_normalized=p.get("nomor_normalized", ""),
            wa_available=p.get("wa_available", False),
            tg_available=p.get("tg_available", False),
            tg_user_id=p.get("tg_user_id"),
        )


def get_players_summary(search: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
    """Semua peserta dari daily_reports (source of truth), di-LEFT-JOIN dengan players untuk WA/TG status."""
    db = get_conn()
    if search:
        rows = db.execute(
            """SELECT
                dr.nama, dr.email, dr.nomor_hp, dr.nomor_normalized,
                dr.status_redeem, dr.lencana_gear,
                dr.milestone, dr.bonus_milestone, dr.status_verifikasi_ai_agent,
                dr.jumlah_lencana, dr.jumlah_arcade_game,
                COALESCE(p.wa_available, 0) as wa_available,
                COALESCE(p.tg_available, 0) as tg_available,
                p.tg_user_id, COALESCE(p.tg_joined, 0) as tg_joined, p.updated_at as checked_at,
                dr.created_at,
                (SELECT sl.wa_error FROM send_logs sl
                 WHERE sl.nomor_hp = dr.nomor_hp AND sl.wa_error IS NOT NULL AND sl.wa_error != ''
                   AND sl.wa_error NOT LIKE 'skip:%'
                 ORDER BY sl.timestamp DESC LIMIT 1) as wa_error
               FROM daily_reports dr
               JOIN (SELECT nomor_normalized, MAX(id) AS max_id FROM daily_reports GROUP BY nomor_normalized) latest
                 ON latest.max_id = dr.id
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
                dr.milestone, dr.bonus_milestone, dr.status_verifikasi_ai_agent,
                dr.jumlah_lencana, dr.jumlah_arcade_game,
                COALESCE(p.wa_available, 0) as wa_available,
                COALESCE(p.tg_available, 0) as tg_available,
                p.tg_user_id, COALESCE(p.tg_joined, 0) as tg_joined, p.updated_at as checked_at,
                dr.created_at,
                (SELECT sl.wa_error FROM send_logs sl
                 WHERE sl.nomor_hp = dr.nomor_hp AND sl.wa_error IS NOT NULL AND sl.wa_error != ''
                   AND sl.wa_error NOT LIKE 'skip:%'
                 ORDER BY sl.timestamp DESC LIMIT 1) as wa_error
               FROM daily_reports dr
               JOIN (SELECT nomor_normalized, MAX(id) AS max_id FROM daily_reports GROUP BY nomor_normalized) latest
                 ON latest.max_id = dr.id
               LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
               GROUP BY dr.nomor_normalized
               ORDER BY dr.nama COLLATE NOCASE
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
    return dicts_from_rows(rows)


def get_player_summary_by_phone(nomor_normalized: str) -> dict | None:
    """Satu baris ringkasan peserta (sama shape dengan get_players_summary) untuk re-render row."""
    db = get_conn()
    row = db.execute(
        """SELECT
            dr.nama, dr.email, dr.nomor_hp, dr.nomor_normalized,
            dr.status_redeem, dr.lencana_gear,
            dr.milestone, dr.bonus_milestone, dr.status_verifikasi_ai_agent,
            dr.jumlah_lencana, dr.jumlah_arcade_game,
            COALESCE(p.wa_available, 0) as wa_available,
            COALESCE(p.tg_available, 0) as tg_available,
            p.tg_user_id, COALESCE(p.tg_joined, 0) as tg_joined, p.updated_at as checked_at,
            dr.created_at,
            (SELECT sl.wa_error FROM send_logs sl
             WHERE sl.nomor_hp = dr.nomor_hp AND sl.wa_error IS NOT NULL AND sl.wa_error != ''
               AND sl.wa_error NOT LIKE 'skip:%'
             ORDER BY sl.timestamp DESC LIMIT 1) as wa_error
           FROM daily_reports dr
           JOIN (SELECT nomor_normalized, MAX(id) AS max_id FROM daily_reports GROUP BY nomor_normalized) latest
             ON latest.max_id = dr.id
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
    if row is None:
        return 0
    new_value = 0 if row["tg_joined"] else 1
    db.execute(
        "UPDATE players SET tg_joined = ? WHERE nomor_normalized = ?",
        (new_value, nomor_normalized),
    )
    db.commit()
    return new_value


def get_players_total_from_reports() -> int:
    """Total peserta unik dari semua daily_reports."""
    db = get_conn()
    return int(db.execute("SELECT COUNT(DISTINCT nomor_normalized) FROM daily_reports").fetchone()[0] or 0)


def get_players_unused_numbers() -> list[str]:
    """Nomor dari reports yang belum pernah dicek (WA/TG belum ada di players atau updated_at IS NULL)."""
    db = get_conn()
    rows = db.execute("""
        SELECT DISTINCT dr.nomor_normalized
        FROM daily_reports dr
        LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
        WHERE (p.id IS NULL OR p.updated_at IS NULL)
          AND dr.nomor_normalized NOT LIKE 'email:%'
    """).fetchall()
    return [r["nomor_normalized"] for r in rows]

def get_unscanned_players() -> list[dict]:
    """Peserta dari reports yang belum pernah dicek (WA/TG belum ada di players atau updated_at IS NULL)."""
    db = get_conn()
    rows = db.execute("""
        SELECT dr.nama, dr.nomor_hp, dr.nomor_normalized
        FROM daily_reports dr
        LEFT JOIN players p ON p.nomor_normalized = dr.nomor_normalized
        WHERE (p.id IS NULL OR p.updated_at IS NULL)
          AND dr.nomor_normalized NOT LIKE 'email:%'
        GROUP BY dr.nomor_normalized
    """).fetchall()
    return dicts_from_rows(rows)


def get_players_count() -> int:
    db = get_conn()
    return int(db.execute("SELECT COUNT(*) FROM players").fetchone()[0] or 0)


def get_wa_registered_count() -> int:
    db = get_conn()
    return int(db.execute("SELECT COUNT(*) FROM players WHERE wa_available = 1").fetchone()[0] or 0)


def get_tg_registered_count() -> int:
    db = get_conn()
    return int(db.execute("SELECT COUNT(*) FROM players WHERE tg_available = 1").fetchone()[0] or 0)


# ═══════════════════════════════════════════════════════════════
# DAILY REPORTS
# ═══════════════════════════════════════════════════════════════

_MONTHS_BY_NAME = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt_date(month: int, day: int, year: int) -> str:
    if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 1900):
        return ""
    return f"{day} {_MONTH_ABBR[month - 1]} {year}"


def _extract_report_date(filename: str) -> str:
    """Ambil tanggal dari nama file: '[28 Jul]', '28-Jul', '[28 Jul 2026]',
    '28-07-2026', '2026-07-28' → '28 Jul 2026' (tahun bila ada).
    Fallback ke tanggal mtime file (YYYY-MM-DD) jika nama file tanpa tanggal."""
    text = os.path.basename(filename)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        date = _fmt_date(int(m.group(2)), int(m.group(3)), int(m.group(1)))
        if date:
            return date
    m = re.search(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)", text)
    if m:
        date = _fmt_date(int(m.group(2)), int(m.group(1)), int(m.group(3)))
        if date:
            return date
    m = re.search(
        r"(?<!\d)(\d{1,2})\s*[-/.]?\s*([A-Za-z]{3,9})\.?(?:\s*,?\s*(\d{4}))?(?!\d)",
        text,
    )
    if m:
        day = int(m.group(1))
        month = _MONTHS_BY_NAME.get(m.group(2).lower())
        if month and 1 <= day <= 31:
            if m.group(3):
                return f"{day} {_MONTH_ABBR[month - 1]} {int(m.group(3))}"
            return f"{day} {_MONTH_ABBR[month - 1]}"
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(filename), tz=timezone.utc)
    except OSError:
        return ""
    return mtime.strftime("%Y-%m-%d")


def _unwrap_row(line: str, n_cols: int) -> list | None:
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
    with _lock:
        report_date = _extract_report_date(csv_path)
        now = datetime.now(timezone.utc).isoformat()

        def to_int(value) -> int:
            try:
                return int(str(value or "0").strip() or "0")
            except (ValueError, TypeError):
                return 0

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
            if not lines:
                return 0, 0
            header = next(csv.reader([lines[0]]), [])
            n_cols = len(header)

            from bot.utils import get_col, normalize_phone
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

                nama = normalize_nama((get_col(row, "nama") or "").strip())
                hp = (get_col(row, "hp") or "").strip()
                email = (get_col(row, "email") or "").strip()
                if not hp:
                    # Peserta tanpa nomor HP tetap di-import; kontak dilakukan via email.
                    if not email:
                        continue
                    normalized = "email:" + email.lower()
                else:
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
                        email,
                        hp,
                        normalized,
                        (get_col(row, "status_redeem") or "").strip(),
                        (get_col(row, "lencana_gear") or "").strip(),
                        (get_col(row, "milestone") or "").strip(),
                        (get_col(row, "bonus_milestone") or "").strip(),
                        (get_col(row, "status_verifikasi_ai_agent") or "").strip(),
                        to_int(get_col(row, "jumlah_lencana")),
                        to_int(get_col(row, "jumlah_arcade_game")),
                        (get_col(row, "nama_lencana") or "").strip(),
                        (get_col(row, "nama_arcade_game") or "").strip(),
                        report_date,
                        now,
                    ),
                )

                # Auto-upsert ke players supaya muncul di list (WA/TG status default 0, updated_at NULL to indicate unchecked)
                db.execute(
                    """INSERT INTO players (nama, nomor_hp, nomor_normalized, created_at, updated_at)
                       VALUES (?, ?, ?, ?, NULL)
                       ON CONFLICT(nomor_normalized) DO UPDATE SET nama=excluded.nama, nomor_hp=excluded.nomor_hp""",
                    (nama, hp, normalized, now),
                )
                count += 1

            db.commit()
            return count, skipped
        except Exception:
            db.rollback()
            raise


def get_daily_reports(search: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
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
    return int(db.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0] or 0)


# ═══════════════════════════════════════════════════════════════
# SEND LOGS
# ═══════════════════════════════════════════════════════════════

def insert_send_log(entry: dict[str, Any], batch_id: str | None = None) -> int:
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
    return int(cur.lastrowid or 0)


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


def insert_send_logs_batch(entries: list[dict[str, Any]], batch_id: str | None = None) -> int:
    bid = batch_id or uuid.uuid4().hex[:8]
    count = 0
    for entry in entries:
        entry["batch_id"] = bid
        insert_send_log(entry, bid)
        count += 1
    return count


def get_send_logs(limit: int = 200, offset: int = 0, batch_id: str | None = None) -> list[dict]:
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
    
    results = []
    for r in rows:
        d = dict(r)
        # Tentukan platform & status untuk template Jinja
        if d.get("wa_sent"):
            d["platform"] = "wa"
            d["status"] = "SUCCESS"
        elif d.get("tg_sent"):
            d["platform"] = "tg"
            d["status"] = "SUCCESS"
        elif d.get("wa_error"):
            d["platform"] = "wa"
            d["status"] = "FAILED"
        elif d.get("tg_error"):
            d["platform"] = "tg"
            d["status"] = "FAILED"
        else:
            d["platform"] = "wa"
            d["status"] = "SUCCESS"
            
        # Tentukan preview pesan
        d["msg_preview"] = f"Template: {d.get('mode') or 'Custom'}"
        results.append(d)
        
    return results


def get_send_logs_count() -> int:
    db = get_conn()
    return int(db.execute("SELECT COUNT(*) FROM send_logs").fetchone()[0] or 0)


def get_recent_logs(limit: int = 5) -> list[dict]:
    """Get N most recent send logs. Used for dashboard preview."""
    return get_send_logs(limit=limit)


# ═══════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════

def get_tg_joined_count() -> int:
    db = get_conn()
    return int(db.execute("SELECT COUNT(*) FROM players WHERE tg_joined = 1").fetchone()[0] or 0)


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
