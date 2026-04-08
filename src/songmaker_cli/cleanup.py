"""Hard-delete soft-deleted Albums/Songs older than RESTORE_WINDOW.

Scheduled as an arq cron job. Reuses the existing delete_album/delete_song
query functions (which already collect mp3/wav paths before ORM cascade
fires) so file unlinks happen post-commit, exactly like the synchronous
DELETE endpoints used to.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from songmaker_cli.api_helpers import cleanup_generation_files
from songmaker_cli.constants import RESTORE_WINDOW
from songmaker_cli.db.queries import (
    delete_album,
    delete_song,
    list_expired_albums,
    list_expired_songs,
)

log = logging.getLogger(__name__)


def run_cleanup_expired(db_factory, audio_dir) -> tuple[int, int]:
    """Hard-delete expired soft-deleted albums and orphan songs.

    Returns (album_count, song_count). Albums are removed first, then
    orphan songs whose parent album was *not* in the expired set —
    songs deleted earlier than their (still-live) album.
    """
    cutoff = datetime.now(timezone.utc) - RESTORE_WINDOW
    paths: list[str] = []
    album_count = 0
    song_count = 0

    with db_factory() as session:
        expired_albums = list_expired_albums(session, cutoff)
        expired_album_ids = [a.id for a in expired_albums]
        for album in expired_albums:
            paths.extend(delete_album(session, album.id))
            album_count += 1

        expired_songs = list_expired_songs(session, cutoff, expired_album_ids)
        for song in expired_songs:
            paths.extend(delete_song(session, song.id))
            song_count += 1

        session.commit()

    cleanup_generation_files(audio_dir, paths)
    if album_count or song_count:
        log.info(
            "cleanup_expired: hard-deleted %d album(s) and %d orphan song(s)",
            album_count, song_count,
        )
    return album_count, song_count
