#!/usr/bin/env bash
# Cosmoport 2.0 — Automated Daily Backup (COS-108) — Linux/Mac
#
# 1. PostgreSQL: pg_dump -Fc via docker exec or direct pg_dump
# 2. MinIO S3: mirror cosmo-evidence bucket via mc (MinIO Client)
# 3. SHA-256 checksums for every backup file
# 4. Retention: 7 daily + 4 weekly (Sunday) — oldest deleted
# 5. Audit: reports/backup-audit.log
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_ROOT="$REPO_ROOT/backups"
AUDIT_LOG="$REPO_ROOT/reports/backup-audit.log"

# ── Config ────────────────────────────────────────────────────────────
PG_USER="${COSMO_PG_USER:-cosmo}"
PG_PASSWORD="${COSMO_PG_PASSWORD:-cosmo}"
PG_HOST="127.0.0.1"
PG_PORT="${COSMO_PG_PORT:-5432}"
PG_DB="${COSMO_PG_DB:-cosmo}"
PG_CONTAINER="cosmo-postgres"

MINIO_ALIAS="cosmo-local"
MINIO_URL="http://127.0.0.1:9100"
MINIO_ACCESS="${COSMO_MINIO_USER:-cosmo}"
MINIO_SECRET="${COSMO_MINIO_PASSWORD:-cosmo-minio-dev}"
MINIO_BUCKET="cosmo-evidence"

RETENTION_DAILY=7
RETENTION_WEEKLY=4

DATE="$(date +%Y-%m-%d)"
DOW="$(date +%u)"
IS_WEEKLY=false
[ "$DOW" -eq 7 ] && IS_WEEKLY=true

TAG="${DATE}_daily"
$IS_WEEKLY && TAG="${DATE}_weekly"

# ── Dirs ──────────────────────────────────────────────────────────────
PG_BACKUP_DIR="$BACKUP_ROOT/pg"
MINIO_BACKUP_DIR="$BACKUP_ROOT/minio_$TAG"
CHECKSUM_DIR="$BACKUP_ROOT/checksums"
mkdir -p "$PG_BACKUP_DIR" "$MINIO_BACKUP_DIR" "$CHECKSUM_DIR" "$REPO_ROOT/reports"

audit() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$AUDIT_LOG"; }

# ══════════════════════════════════════════════════════════════════════

audit "=== Cosmo Daily Backup started ==="
audit "  Date=$DATE  Weekly=$IS_WEEKLY"
echo ""

# ── 1. PostgreSQL dump ───────────────────────────────────────────────

audit "--- PostgreSQL Backup ---"

PG_DUMP_FILE="pg_cosmo_$TAG.dump"
PG_DUMP_PATH="$PG_BACKUP_DIR/$PG_DUMP_FILE"

if [ -f "$PG_DUMP_PATH" ]; then
    audit "  SKIP: $PG_DUMP_FILE already exists"
else
    audit "  Dumping PostgreSQL: $PG_DB"

    if docker ps --filter "name=$PG_CONTAINER" --format '{{.Names}}' 2>/dev/null | grep -q "$PG_CONTAINER"; then
        docker exec "$PG_CONTAINER" sh -c \
            "PGPASSWORD=$PG_PASSWORD pg_dump -h localhost -p 5432 -U $PG_USER -d $PG_DB -Fc -f /tmp/$PG_DUMP_FILE"
        docker cp "$PG_CONTAINER:/tmp/$PG_DUMP_FILE" "$PG_DUMP_PATH"
    else
        PGPASSWORD="$PG_PASSWORD" pg_dump -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -Fc -f "$PG_DUMP_PATH"
    fi

    if [ -f "$PG_DUMP_PATH" ] && [ -s "$PG_DUMP_PATH" ]; then
        audit "  OK: $PG_DUMP_FILE ($(du -h "$PG_DUMP_PATH" | cut -f1))"
    else
        audit "  FAIL: pg_dump failed"
        exit 1
    fi
fi

if [ -f "$PG_DUMP_PATH" ]; then
    PG_CHECKSUM=$(sha256sum "$PG_DUMP_PATH" | cut -d' ' -f1)
    echo -n "$PG_CHECKSUM" > "$CHECKSUM_DIR/$PG_DUMP_FILE.sha256"
    audit "  SHA256: $PG_CHECKSUM"
fi

# ── 2. MinIO mirror ───────────────────────────────────────────────────

audit ""
audit "--- MinIO Backup ---"

if command -v mc >/dev/null 2>&1; then
    mc alias set "$MINIO_ALIAS" "$MINIO_URL" "$MINIO_ACCESS" "$MINIO_SECRET" 2>/dev/null || true
    mc mirror --overwrite "$MINIO_ALIAS/$MINIO_BUCKET" "$MINIO_BACKUP_DIR" 2>/dev/null && \
        audit "  OK: mc mirror completed" || audit "  WARN: mc mirror had issues"
else
    audit "  WARN: mc not installed — try 'brew install minio/stable/minio'"
    audit "  Skipping MinIO backup"
fi

if [ -d "$MINIO_BACKUP_DIR" ]; then
    MINIO_COUNT=$(find "$MINIO_BACKUP_DIR" -type f 2>/dev/null | wc -l)
    audit "  Files: $MINIO_COUNT"
    if [ "$MINIO_COUNT" -gt 0 ]; then
        MINIO_CHECKSUM=$(find "$MINIO_BACKUP_DIR" -type f -exec sha256sum {} \; | sort -k2 | sha256sum | cut -d' ' -f1)
        echo -n "$MINIO_CHECKSUM" > "$CHECKSUM_DIR/minio_$TAG.sha256"
        audit "  Combined SHA256: $MINIO_CHECKSUM"
    fi
fi

# ── 3. Retention ────────────────────────────────────────────────────

audit ""
audit "--- Retention Policy ---"
audit "  Keep: ${RETENTION_DAILY} daily + ${RETENTION_WEEKLY} weekly"

cleanup_files() {
    local pattern="$1" dir="$2" limit="$3" label="$4"
    local files; files=$(find "$dir" -maxdepth 1 -name "$pattern" -type f 2>/dev/null | sort -r || true)
    local count; count=$(echo "$files" | grep -c . 2>/dev/null || echo 0)
    if [ "$count" -gt "$limit" ]; then
        local to_delete; to_delete=$(echo "$files" | tail -n +$((limit + 1)))
        local del_count; del_count=$(echo "$to_delete" | grep -c . 2>/dev/null || echo 0)
        audit "  $label: deleting $del_count (keeping newest $limit)"
        echo "$to_delete" | while read -r f; do
            [ -n "$f" ] || continue
            rm -f "$f" "$CHECKSUM_DIR/$(basename "$f").sha256" 2>/dev/null || true
            audit "    Deleted: $(basename "$f")"
        done
    else
        audit "  $label: $count (limit $limit) — ok"
    fi
}

cleanup_files "*_daily.dump"  "$PG_BACKUP_DIR" "$RETENTION_DAILY" "PG dailies"
cleanup_files "*_weekly.dump" "$PG_BACKUP_DIR" "$RETENTION_WEEKLY" "PG weeklies"

for type in daily weekly; do
    limit=$RETENTION_DAILY; [ "$type" = "weekly" ] && limit=$RETENTION_WEEKLY
    dirs=$(find "$BACKUP_ROOT" -maxdepth 1 -type d -name "minio_*_$type" 2>/dev/null | sort -r || true)
    count=$(echo "$dirs" | grep -c . 2>/dev/null || echo 0)
    if [ "$count" -gt "$limit" ]; then
        todel=$(echo "$dirs" | tail -n +$((limit + 1)))
        dc=$(echo "$todel" | grep -c . 2>/dev/null || echo 0)
        audit "  MinIO $type: deleting $dc (keeping newest $limit)"
        echo "$todel" | while read -r d; do
            [ -n "$d" ] || continue
            rm -rf "$d" && audit "    Deleted: $(basename "$d")"
        done
    else
        audit "  MinIO $type: $count (limit $limit) — ok"
    fi
done

# ── 4. Summary ───────────────────────────────────────────────────────

audit ""
audit "=== Cosmo Daily Backup Complete ==="
audit "  PG dir     : $PG_BACKUP_DIR"
audit "  MinIO dirs : $BACKUP_ROOT"
audit "  Checksums  : $CHECKSUM_DIR"

echo ""
echo "=== Backup Complete ==="
echo "  PG     : $PG_BACKUP_DIR"
echo "  MinIO  : $BACKUP_ROOT"
echo "  Audit  : $AUDIT_LOG"
echo "  Retained: ${RETENTION_DAILY} daily + ${RETENTION_WEEKLY} weekly"
exit 0