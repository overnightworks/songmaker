#!/bin/bash
# Songmaker restore — restores PostgreSQL + audio files from a backup snapshot.
# Runs from the project root (where docker-compose.yml lives).
#
# Usage:
#   ./scripts/restore.sh /mnt/backup/songmaker/20260329_030000
#
# This will:
#   1. Stop web + worker containers
#   2. Restore the PostgreSQL database
#   3. Restore audio files
#   4. Restart all services

set -euo pipefail

SNAPSHOT_DIR="${1:?Usage: ./scripts/restore.sh /path/to/backup/20260329_030000}"
POSTGRES_USER="${POSTGRES_USER:-songmaker}"
POSTGRES_DB="${POSTGRES_DB:-songmaker}"
VOLUME_NAME="${VOLUME_NAME:-songmaker_audiofiles}"

if [[ ! -f "$SNAPSHOT_DIR/db.dump" ]]; then
    echo "ERROR: $SNAPSHOT_DIR/db.dump not found"
    exit 1
fi

if [[ ! -d "$SNAPSHOT_DIR/audio" ]]; then
    echo "ERROR: $SNAPSHOT_DIR/audio/ not found"
    exit 1
fi

if [[ -f "$SNAPSHOT_DIR/manifest.txt" ]]; then
    echo "=== Restoring from backup ==="
    cat "$SNAPSHOT_DIR/manifest.txt"
    echo "==========================="
fi

echo ""
echo "WARNING: This will overwrite the current database and audio files."
read -r -p "Continue? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo "Stopping songmaker services..."
docker compose stop songmaker-web songmaker-worker

echo "Restoring PostgreSQL..."
docker compose exec -T postgres pg_restore \
    -U "$POSTGRES_USER" \
    --clean --if-exists \
    -d "$POSTGRES_DB" \
    < "$SNAPSHOT_DIR/db.dump" || true
# pg_restore returns non-zero on warnings (e.g. "relation does not exist" during --clean)
# which is expected on a fresh DB. The || true prevents script abort.

echo "Restoring audio files..."
docker run --rm \
    -v "$VOLUME_NAME:/dest" \
    -v "$SNAPSHOT_DIR/audio:/source:ro" \
    alpine sh -c 'rm -rf /dest/* && cp -a /source/. /dest/'

echo "Restarting services..."
docker compose up -d --wait songmaker-web songmaker-worker

AUDIO_COUNT=$(docker run --rm -v "$VOLUME_NAME:/data:ro" alpine find /data -type f | wc -l 2>/dev/null || echo "?")
echo "=== Restore complete ==="
echo "  Source: $SNAPSHOT_DIR"
echo "  Audio files: $AUDIO_COUNT"
echo "  Services: running"
