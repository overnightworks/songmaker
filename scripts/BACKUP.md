# Backup & Restore

Backs up PostgreSQL + audio files together. Both must be restored as a pair — one without the other leaves the system broken.

## Setup

```bash
# 1. Plug in your external drive and find it
lsblk

# 2. Mount it
sudo mkdir -p /mnt/backup
sudo mount /dev/sdX1 /mnt/backup    # replace sdX1 with your drive

# 3. Create the backup directory
mkdir -p /mnt/backup/songmaker

# 4. Run your first backup
cd ~/git/songmaker
./scripts/backup.sh
```

## Scripts

| Script | What it does |
|--------|-------------|
| `backup.sh` | Dumps DB + copies audio to `BACKUP_DIR` |
| `restore.sh <path>` | Restores DB + audio from a snapshot |
| `backup-list.sh` | Lists available backups with sizes |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_DIR` | `/mnt/backup/songmaker` | Where backups go |
| `RETENTION_DAYS` | `7` | Delete backups older than this |
| `POSTGRES_USER` | `songmaker` | PostgreSQL username |
| `POSTGRES_DB` | `songmaker` | PostgreSQL database name |

## Manual Backup

```bash
# With default path
./scripts/backup.sh

# With custom path
BACKUP_DIR=/media/felix/external/songmaker ./scripts/backup.sh

# List what you have
./scripts/backup-list.sh
```

## Automatic Daily Backup (cron)

```bash
# Add to cron (runs daily at 3am)
echo '0 3 * * * cd /home/felix-hummert/git/songmaker && BACKUP_DIR=/mnt/backup/songmaker ./scripts/backup.sh >> /var/log/songmaker-backup.log 2>&1' | sudo tee /etc/cron.d/songmaker-backup
```

Make sure your external drive auto-mounts on boot. Add to `/etc/fstab`:

```
UUID=YOUR-DRIVE-UUID  /mnt/backup  ext4  defaults,nofail  0  2
```

The `nofail` flag means the system still boots if the drive is unplugged. The backup script will exit with an error if the directory doesn't exist.

## Restore

```bash
# List available backups
./scripts/backup-list.sh

# Restore from a specific snapshot
./scripts/restore.sh /mnt/backup/songmaker/20260329_030000
```

This will:
1. Stop the web and worker containers
2. Restore the PostgreSQL database
3. Restore all audio files
4. Restart everything

You'll be asked to confirm before anything is overwritten.

## What Gets Backed Up

| Data | Backed up? | Why |
|------|-----------|-----|
| PostgreSQL (songs, users, scores) | Yes | Source of truth |
| Audio files (MP3 + WAV + album and song covers) | Yes | Not reproducible without re-generating; covers live on the same audio volume (`covers/` and `song-covers/`) |
| Redis | No | Ephemeral cache, rebuilds on restart |
| Model weights (`_models/`) | No | Re-downloadable, ~10GB |
| `.env` | No | Copy manually to the backup drive |
