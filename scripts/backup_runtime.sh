#!/usr/bin/env bash
# Backup runtime data (SQLite DB + session Telegram + profil Chrome WA) ke folder backup/.
# PII & kredensial akun ada di runtime/ — backup wajib disimpan di media terenkripsi.
#
# Usage:
#   ./scripts/backup_runtime.sh [target_dir]
#   cron: 0 3 * * * /path/ke/proyek/scripts/backup_runtime.sh /Volumes/Backup/gcaf

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$PROJECT_ROOT/runtime"
TARGET_DIR="${1:-$PROJECT_ROOT/backup}"

if [ ! -d "$RUNTIME_DIR" ]; then
    echo "runtime/ tidak ditemukan — tidak ada yang perlu di-backup."
    exit 0
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$TARGET_DIR/$STAMP"
mkdir -p "$BACKUP_DIR"

# Backup SQLite secara konsisten (WAL-aware) kalau sqlite3 CLI tersedia
if command -v sqlite3 >/dev/null 2>&1 && [ -f "$RUNTIME_DIR/gcaf.db" ]; then
    sqlite3 "$RUNTIME_DIR/gcaf.db" ".backup '$BACKUP_DIR/gcaf.db'"
    echo "✓ gcaf.db (konsisten via .backup)"
else
    cp -p "$RUNTIME_DIR/gcaf.db" "$BACKUP_DIR/gcaf.db" 2>/dev/null || true
    echo "⚠ sqlite3 CLI tidak tersedia — DB dicopy mentah (non-atomik)."
fi

# Session & profil
for item in tg_checker_session tg_checker_session.session checker_session*.session wa_chrome_profile wa_profile; do
    [ -e "$RUNTIME_DIR/$item" ] && cp -rp "$RUNTIME_DIR/$item" "$BACKUP_DIR/" && echo "✓ $item"
done

# Retensi: simpan 7 backup terakhir
ls -1dt "$TARGET_DIR"/20* 2>/dev/null | tail -n +8 | xargs -r rm -rf

echo "→ Backup selesai: $BACKUP_DIR"
echo "  ⚠ Pastikan folder target berada di media terenkripsi (FileVault/encrypted volume)."
