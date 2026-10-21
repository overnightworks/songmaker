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
| `RETENTION_DAYS` | `7` | Delete backups older than this many days; `0` prunes nothing |
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

Pruning deletes every directory directly under `BACKUP_DIR` older than `RETENTION_DAYS`, not only snapshots this script made. Give `BACKUP_DIR` a directory of its own that holds nothing else. A snapshot you must keep (for example the one taken just before a cutover) belongs in a dedicated directory run with `RETENTION_DAYS=0`:

```bash
BACKUP_DIR=/mnt/backup/songmaker-cutover RETENTION_DAYS=0 ./scripts/backup.sh
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

Before restoring, stop auto-deploy and make sure no deployment is running, or it restarts writers mid-restore:

```bash
sudo systemctl stop songmaker-autodeploy.timer
```

The script refuses while the timer is active or a deployment holds auto-deploy's lock (`songmaker-autodeploy.lock` in the git admin directory); wait for the deployment to finish and run it again. Keep the timer stopped until the recovery is verified, then `sudo systemctl start songmaker-autodeploy.timer`.

This will:
1. Refuse an incomplete snapshot: no `manifest.txt`, an unreadable dump (`pg_restore --list`), or an audio file count that differs from the manifest's `audio_files`
2. Stop every writer: `songmaker-web`, `songmaker-music-worker`, `songmaker-acestep-worker-0`, `songmaker-scoring-worker`
3. Drop and recreate the database, then restore it with `pg_restore --exit-on-error --single-transaction`
4. Replace the audio volume's contents with the snapshot's, dotfiles included, and fail if the volume's file count differs from the manifest's
5. Leave the writers stopped and print the commands that start them and re-enable auto-deploy

You'll be asked to confirm before anything is overwritten.

Only the import is one transaction. The drop and create commit before it and cannot be undone, so a failed import leaves an empty database, and a failed audio step leaves the restored database next to partial audio. In every case the snapshot is unchanged and the writers stay stopped. Recovery: fix the cause and run the script again with a good snapshot.

## What Gets Backed Up

| Data | Backed up? | Why |
|------|-----------|-----|
| PostgreSQL (songs, users, scores) | Yes | Source of truth |
| Audio files (MP3 + WAV + album and song covers) | Yes | Not reproducible without re-generating; covers live on the same audio volume (`covers/` and `song-covers/`) |
| Redis | No | Ephemeral cache, rebuilds on restart |
| Model weights (`_models/`) | No | Re-downloadable, ~10GB |
| `.env` | No | Copy manually to the backup drive |
