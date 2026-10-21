#!/bin/bash
# Songmaker restore — restores PostgreSQL + audio files from a backup snapshot.
# Runs from the project root (where docker-compose.yml lives).
#
# Usage:
#   ./scripts/restore.sh /mnt/backup/songmaker/20260329_030000
#
# This will:
#   1. Stop every writer (web, music worker, ACE-Step worker, scoring worker)
#   2. Recreate the database and restore it in one transaction (any error aborts)
#   3. Replace the audio volume's contents, dotfiles included
#   4. Leave the writers stopped and print the command that starts them again

set -euo pipefail

SNAPSHOT_DIR="${1:?Usage: ./scripts/restore.sh /path/to/backup/20260329_030000}"
POSTGRES_USER="${POSTGRES_USER:-songmaker}"
POSTGRES_DB="${POSTGRES_DB:-songmaker}"
VOLUME_NAME="${VOLUME_NAME:-songmaker_audiofiles}"
WRITER_SERVICES=(songmaker-web songmaker-music-worker songmaker-acestep-worker-0 songmaker-scoring-worker)

if [[ ! -f "$SNAPSHOT_DIR/db.dump" ]]; then
    echo "ERROR: $SNAPSHOT_DIR/db.dump not found" >&2
    exit 1
fi

if [[ ! -d "$SNAPSHOT_DIR/audio" ]]; then
    echo "ERROR: $SNAPSHOT_DIR/audio/ not found" >&2
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

echo "Stopping writers: ${WRITER_SERVICES[*]}..."
docker compose stop "${WRITER_SERVICES[@]}"

echo "Recreating database $POSTGRES_DB..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres \
    -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""

echo "Restoring PostgreSQL..."
docker compose exec -T postgres pg_restore \
    -U "$POSTGRES_USER" \
    --exit-on-error --single-transaction \
    -d "$POSTGRES_DB" \
    < "$SNAPSHOT_DIR/db.dump"

echo "Restoring audio files..."
docker run --rm \
    -v "$VOLUME_NAME:/dest" \
    -v "$SNAPSHOT_DIR/audio:/source:ro" \
    alpine sh -c 'find /dest -mindepth 1 -delete && cp -a /source/. /dest/'

AUDIO_COUNT=$(docker run --rm -v "$VOLUME_NAME:/data:ro" alpine find /data -type f | wc -l)
echo "=== Restore complete ==="
echo "  Source: $SNAPSHOT_DIR"
echo "  Audio files: $AUDIO_COUNT"
echo "  Writers: stopped. Start them again with:"
echo "    docker compose up -d --wait ${WRITER_SERVICES[*]}"
