#!/bin/bash
# Songmaker restore — restores PostgreSQL + audio files from a backup snapshot.
# Runs from the project root (where docker-compose.yml lives).
#
# Usage:
#   ./scripts/restore.sh /mnt/backup/songmaker/20260329_030000
#
# This will:
#   0. Refuse unless auto-deploy is stopped and idle, the snapshot is complete
#      (dump readable, manifest present, audio count equal to the manifest's)
#   1. Stop every writer (web, music worker, ACE-Step worker, scoring worker)
#   2. Drop and recreate the database (committed at once, not undoable), then
#      restore the dump in one transaction (any error aborts that import)
#   3. Replace the audio volume's contents, dotfiles included
#   4. Leave the writers stopped and print the commands that start them again
#
# Only the import is transactional. A failed import leaves an empty database;
# a failed audio step leaves the restored database next to partial audio. The
# snapshot is never changed and the writers stay stopped: run the script again
# with a good snapshot.

set -euo pipefail

POSTGRES_USER="${POSTGRES_USER:-songmaker}"
POSTGRES_DB="${POSTGRES_DB:-songmaker}"
VOLUME_NAME="${VOLUME_NAME:-songmaker_audiofiles}"
WRITER_SERVICES=(songmaker-web songmaker-music-worker songmaker-acestep-worker-0 songmaker-scoring-worker)
AUTODEPLOY_TIMER="songmaker-autodeploy.timer"
# $1 is the snapshot's audio directory, $2 the volume's mount point.
AUDIO_REPLACE_SCRIPT='find "$2" -mindepth 1 -delete && cp -a "$1"/. "$2"/'

# why: the postgres service's image is Alpine-based (busybox sh, cp, find) and
# compose pins it by digest, so Dependabot moves this helper with compose.
audio_helper_image() {
    docker compose config --images postgres
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

autodeploy_lock_file() {
    # Same path auto-deploy.sh locks: its override, else the git admin directory.
    echo "${SONGMAKER_AUTODEPLOY_LOCK_FILE:-$(git rev-parse --absolute-git-dir)/songmaker-autodeploy.lock}"
}

require_idle_autodeploy() {
    local timer_state
    timer_state="$(systemctl show -p ActiveState --value "$AUTODEPLOY_TIMER")" \
        || fail "cannot query $AUTODEPLOY_TIMER; refusing without knowing auto-deploy is stopped."
    case "$timer_state" in
        inactive | failed) ;;
        *)
            fail "$AUTODEPLOY_TIMER is '$timer_state', not stopped, and could restart writers mid-restore. Stop it first:
    sudo systemctl stop $AUTODEPLOY_TIMER
  Re-enable it only after the recovery is verified:
    sudo systemctl start $AUTODEPLOY_TIMER"
            ;;
    esac
    local lock_file
    lock_file="$(autodeploy_lock_file)"
    flock -n "$lock_file" true || fail "a deployment holds $lock_file. Wait for it to finish, then run this again."
}

require_complete_snapshot() {
    [[ -f "$SNAPSHOT_DIR/db.dump" ]] || fail "$SNAPSHOT_DIR/db.dump not found"
    [[ -d "$SNAPSHOT_DIR/audio" ]] || fail "$SNAPSHOT_DIR/audio/ not found"
    [[ -f "$SNAPSHOT_DIR/manifest.txt" ]] || fail "$SNAPSHOT_DIR/manifest.txt not found; the backup did not finish"
    EXPECTED_AUDIO_COUNT="$(sed -n 's/^audio_files=\([0-9][0-9]*\)$/\1/p' "$SNAPSHOT_DIR/manifest.txt")"
    [[ -n "$EXPECTED_AUDIO_COUNT" ]] || fail "$SNAPSHOT_DIR/manifest.txt has no audio_files count"
    local snapshot_audio_count
    snapshot_audio_count="$(find "$SNAPSHOT_DIR/audio" -type f | wc -l)"
    [[ "$snapshot_audio_count" -eq "$EXPECTED_AUDIO_COUNT" ]] \
        || fail "snapshot holds $snapshot_audio_count audio files, its manifest records $EXPECTED_AUDIO_COUNT"
    docker volume inspect "$VOLUME_NAME" > /dev/null || fail "audio volume $VOLUME_NAME not found"
    AUDIO_HELPER_IMAGE="$(audio_helper_image)"
    [[ -n "$AUDIO_HELPER_IMAGE" ]] || fail "compose names no image for the postgres service"
    docker compose exec -T postgres pg_restore --list < "$SNAPSHOT_DIR/db.dump" > /dev/null \
        || fail "$SNAPSHOT_DIR/db.dump is not a readable dump"
}

main() {
    SNAPSHOT_DIR="$(realpath -m -- "${1:?Usage: ./scripts/restore.sh /path/to/backup/20260329_030000}")"

    require_idle_autodeploy
    require_complete_snapshot

    echo "=== Restoring from backup ==="
    cat "$SNAPSHOT_DIR/manifest.txt"
    echo "==========================="
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
        -c "DROP DATABASE \"$POSTGRES_DB\" WITH (FORCE)" \
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
        "$AUDIO_HELPER_IMAGE" sh -c "$AUDIO_REPLACE_SCRIPT" _ /source /dest

    local restored_audio_count
    restored_audio_count="$(docker run --rm -v "$VOLUME_NAME:/data:ro" "$AUDIO_HELPER_IMAGE" find /data -type f | wc -l)"
    [[ "$restored_audio_count" -eq "$EXPECTED_AUDIO_COUNT" ]] \
        || fail "volume holds $restored_audio_count audio files after the copy, the manifest records $EXPECTED_AUDIO_COUNT. Writers stay stopped."

    echo "=== Restore complete ==="
    echo "  Source: $SNAPSHOT_DIR"
    echo "  Audio files: $restored_audio_count"
    echo "  Writers: stopped. Start them again with:"
    echo "    docker compose up -d --wait ${WRITER_SERVICES[*]}"
    echo "  Then re-enable auto-deploy:"
    echo "    sudo systemctl start $AUTODEPLOY_TIMER"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
