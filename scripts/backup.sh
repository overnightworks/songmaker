#!/bin/bash
# Songmaker backup — dumps PostgreSQL + syncs audio files to BACKUP_DIR.
# Runs from the project root (where docker-compose.yml lives).
#
# Usage:
#   ./scripts/backup.sh                          # uses default /mnt/backup/songmaker
#   BACKUP_DIR=/media/usb/songmaker ./scripts/backup.sh
#
# Cron (daily at 3am):
#   0 3 * * * cd /home/felix-hummert/git/songmaker && ./scripts/backup.sh >> /var/log/songmaker-backup.log 2>&1

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/mnt/backup/songmaker}"
POSTGRES_USER="${POSTGRES_USER:-songmaker}"
POSTGRES_DB="${POSTGRES_DB:-songmaker}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
VOLUME_NAME="${VOLUME_NAME:-songmaker_audiofiles}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_DIR="$BACKUP_DIR/$TIMESTAMP"

if [[ ! -d "$BACKUP_DIR" ]]; then
    echo "ERROR: Backup directory $BACKUP_DIR does not exist."
    echo "Mount your external drive and create the directory first."
    exit 1
fi

echo "=== Songmaker Backup: $TIMESTAMP ==="

mkdir -p "$SNAPSHOT_DIR"

echo "Dumping PostgreSQL..."
docker compose exec -T postgres pg_dump \
    -U "$POSTGRES_USER" \
    --format=custom \
    "$POSTGRES_DB" \
    > "$SNAPSHOT_DIR/db.dump"

DB_SIZE=$(stat -c%s "$SNAPSHOT_DIR/db.dump")
echo "  DB dump: $(numfmt --to=iec "$DB_SIZE")"

echo "Syncing audio files..."
mkdir -p "$SNAPSHOT_DIR/audio"
docker run --rm \
    -v "$VOLUME_NAME:/source:ro" \
    -v "$SNAPSHOT_DIR/audio:/dest" \
    alpine sh -c 'cp -a /source/. /dest/'

AUDIO_COUNT=$(find "$SNAPSHOT_DIR/audio" -type f | wc -l)
AUDIO_SIZE=$(du -sb "$SNAPSHOT_DIR/audio" 2>/dev/null | cut -f1)
echo "  Audio files: $AUDIO_COUNT ($(numfmt --to=iec "${AUDIO_SIZE:-0}"))"

cat > "$SNAPSHOT_DIR/manifest.txt" <<MANIFEST
timestamp=$TIMESTAMP
db_size=$DB_SIZE
audio_files=$AUDIO_COUNT
audio_bytes=${AUDIO_SIZE:-0}
hostname=$(hostname)
MANIFEST

if [[ "$RETENTION_DAYS" -gt 0 ]]; then
    PRUNED=$(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +"$RETENTION_DAYS" | wc -l)
    if [[ "$PRUNED" -gt 0 ]]; then
        find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} +
        echo "Pruned $PRUNED old backups (older than $RETENTION_DAYS days)"
    fi
fi

TOTAL_SIZE=$(du -sh "$SNAPSHOT_DIR" | cut -f1)
echo "=== Backup complete: $SNAPSHOT_DIR ($TOTAL_SIZE) ==="
