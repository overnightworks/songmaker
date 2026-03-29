#!/bin/bash
# List available songmaker backups with size and file counts.
#
# Usage:
#   ./scripts/backup-list.sh
#   BACKUP_DIR=/media/usb/songmaker ./scripts/backup-list.sh

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/mnt/backup/songmaker}"

if [ ! -d "$BACKUP_DIR" ]; then
    echo "No backup directory at $BACKUP_DIR"
    exit 1
fi

SNAPSHOTS=$(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d | sort -r)

if [ -z "$SNAPSHOTS" ]; then
    echo "No backups found in $BACKUP_DIR"
    exit 0
fi

printf "%-20s  %8s  %8s  %s\n" "SNAPSHOT" "DB" "FILES" "TOTAL"
printf "%-20s  %8s  %8s  %s\n" "--------" "--" "-----" "-----"

for dir in $SNAPSHOTS; do
    name=$(basename "$dir")
    if [ -f "$dir/manifest.txt" ]; then
        db_size=$(grep "^db_size=" "$dir/manifest.txt" | cut -d= -f2)
        audio_count=$(grep "^audio_files=" "$dir/manifest.txt" | cut -d= -f2)
        db_human=$(numfmt --to=iec "$db_size" 2>/dev/null || echo "${db_size}B")
    else
        db_human="?"
        audio_count="?"
    fi
    total=$(du -sh "$dir" 2>/dev/null | cut -f1 || echo "?")
    printf "%-20s  %8s  %8s  %s\n" "$name" "$db_human" "$audio_count" "$total"
done
