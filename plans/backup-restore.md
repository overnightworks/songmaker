# Backup & Restore Strategy

## Context

Audio files live in `data/audio/` (Docker volume `audiofiles`), DB records reference them by relative path. Restoring one without the other leaves the system broken: DB without audio = 404 on playback, audio without DB = unreachable files. Currently there is no backup mechanism.

## Constraints

- Single PC running Docker containers (no cloud storage, no second server)
- PostgreSQL + Redis + audio files on local Docker volumes
- Redis is ephemeral (session cache, queue) — no backup needed
- Audio files are large (each generation ~5-10MB WAV + ~1MB MP3)
- DB is small (metadata, scores, users — a few MB)

## Recommendation: Local Backup Script + External Drive

For a single-PC setup, the pragmatic approach is a cron script that dumps DB + syncs audio to a backup location (external drive, NAS, or a second partition).

### Option A: Simple Script (recommended)

**backup.sh** — runs daily via cron:

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/mnt/backup/songmaker}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SNAPSHOT_DIR="$BACKUP_DIR/$TIMESTAMP"

mkdir -p "$SNAPSHOT_DIR"

# 1. Dump PostgreSQL (consistent snapshot)
docker compose exec -T postgres pg_dump \
  -U "${POSTGRES_USER:-songmaker}" \
  --format=custom \
  "${POSTGRES_DB:-songmaker}" \
  > "$SNAPSHOT_DIR/db.dump"

# 2. Sync audio files (incremental — only copies new/changed files)
rsync -a --delete \
  "$(docker volume inspect songmaker_audiofiles --format '{{.Mountpoint}}')/" \
  "$SNAPSHOT_DIR/audio/"

# 3. Write manifest
echo "timestamp=$TIMESTAMP" > "$SNAPSHOT_DIR/manifest.txt"
echo "db_size=$(stat -c%s "$SNAPSHOT_DIR/db.dump")" >> "$SNAPSHOT_DIR/manifest.txt"
echo "audio_files=$(find "$SNAPSHOT_DIR/audio" -type f | wc -l)" >> "$SNAPSHOT_DIR/manifest.txt"

# 4. Prune old backups (keep last 7 days)
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +

echo "Backup complete: $SNAPSHOT_DIR"
```

**restore.sh**:

```bash
#!/bin/bash
set -euo pipefail

SNAPSHOT_DIR="${1:?Usage: restore.sh /path/to/backup/20260329_030000}"

# 1. Stop services (keep postgres running)
docker compose stop songmaker-web songmaker-worker

# 2. Restore PostgreSQL
docker compose exec -T postgres pg_restore \
  -U "${POSTGRES_USER:-songmaker}" \
  --clean --if-exists \
  -d "${POSTGRES_DB:-songmaker}" \
  < "$SNAPSHOT_DIR/db.dump"

# 3. Restore audio files
rsync -a --delete \
  "$SNAPSHOT_DIR/audio/" \
  "$(docker volume inspect songmaker_audiofiles --format '{{.Mountpoint}}')/"

# 4. Restart services
docker compose up -d --wait songmaker-web songmaker-worker

echo "Restore complete from: $SNAPSHOT_DIR"
```

### Cron Setup

```bash
# /etc/cron.d/songmaker-backup
0 3 * * * root /opt/songmaker/backup.sh >> /var/log/songmaker-backup.log 2>&1
```

### What Gets Backed Up

| Data | Method | Size | Frequency |
|------|--------|------|-----------|
| PostgreSQL | `pg_dump --format=custom` | ~5-50MB | Daily 3am |
| Audio files | `rsync --delete` (incremental) | Grows with usage | Daily 3am |
| Redis | Not backed up (ephemeral cache) | N/A | N/A |
| Model weights | Not backed up (re-downloadable) | N/A | N/A |
| `.server.env` | Manual — keep a copy on the external drive | <1KB | On change |

### Option B: Future Cloud Backup

If you later add a second machine or cloud storage:

- Replace `rsync` destination with `rclone` to S3/B2/Google Drive
- Add GPG encryption before upload: `gpg --symmetric --cipher-algo AES256 db.dump`
- Keep local backup as primary, cloud as offsite copy
- No application code changes needed — it's all in the backup script

## What NOT to Do

- Don't use Docker volume export (`docker run --rm -v ... tar`) — it's slow and can't do incremental
- Don't dump PostgreSQL from inside the app — use `pg_dump` directly
- Don't try to backup Redis — it's a cache, not a store. Session data regenerates on login
- Don't back up `_models/acestep/` — model weights are large (~10GB+) and re-downloadable

## Decision Needed

**Where should backups go?**
- External USB drive mounted at `/mnt/backup`?
- A NAS on the local network?
- A second internal drive?

The script works with any mount point — just set `BACKUP_DIR`.

## Effort

- Backup script: ~30 minutes
- Restore script: ~30 minutes
- Cron setup: ~5 minutes
- Testing a full backup/restore cycle: ~1 hour
