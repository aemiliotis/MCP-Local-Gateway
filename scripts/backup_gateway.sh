#!/bin/bash
set -uo pipefail

DB="${GATEWAY_DB:-/home/logictech/logictech1/gateway.db}"
BACKUP_DIR="${BACKUP_DIR:-/home/logictech/logictech1/backups}"
RETENTION="${RETENTION:-7}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/gateway-${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

sqlite3 "$DB" ".backup '${BACKUP_FILE}'" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: SQLite backup failed"
    exit 1
fi

INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check" 2>/dev/null)
if [ "$INTEGRITY" != "ok" ]; then
    echo "ERROR: Backup integrity check failed: $INTEGRITY"
    rm -f "$BACKUP_FILE"
    exit 1
fi

echo "BACKUP OK: ${BACKUP_FILE}"
ls -t "${BACKUP_DIR}"/gateway-*.db 2>/dev/null | tail -n +$((RETENTION + 1)) | xargs rm -f 2>/dev/null
