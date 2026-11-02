"""Hard-delete soft-deleted Albums/Songs older than the soft-delete retention window.

Scheduled as an arq cron job. Reuses the existing delete_album/delete_song
query functions (which already collect mp3/wav paths before ORM cascade
fires) so file unlinks happen post-commit, exactly like the synchronous
DELETE endpoints used to.

Also runs generation retention: archives expired unpicked/unkept
generations and hard-deletes archived generations after a second window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from songmaker_cli.api_helpers import cleanup_generation_files
from songmaker_cli.cover_suggestions import remove_album_cover_suggestion_files
from songmaker_cli.covers import remove_album_cover_files, remove_song_cover_files
from songmaker_cli.db.queries.albums import delete_album, list_expired_albums
from songmaker_cli.db.queries.generations import (
    archive_generation,
    delete_expired_generation,
    list_generations_expired_for_archive,
    list_generations_expired_for_delete,
)
from songmaker_cli.db.queries.songs import delete_song, list_expired_songs, list_song_ids_for_albums
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

# The music worker runs the generation retention daily at this hour, in UTC;
# the admin page names it.
GENERATION_RETENTION_HOUR_UTC = 3


@dataclass(slots=True)
class GenerationRetentionReport:
    archived_ids: list[str] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)

    @property
    def archived_count(self) -> int:
        return len(self.archived_ids)

    @property
    def deleted_count(self) -> int:
        return len(self.deleted_ids)


def run_cleanup_expired(db_factory, audio_dir) -> tuple[int, int]:
    """Hard-delete expired soft-deleted albums and orphan songs.

    Returns (album_count, song_count). Albums are removed first, then
    orphan songs whose parent album was *not* in the expired set —
    songs deleted earlier than their (still-live) album.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=get_settings().final_deletion_days,
    )
    paths: list[str] = []
    album_count = 0
    song_count = 0
    deleted_album_ids: list[str] = []
    deleted_orphan_song_ids: list[str] = []

    with db_factory() as session:
        expired_albums = list_expired_albums(session, cutoff)
        expired_album_ids = [a.id for a in expired_albums]
        expired_song_ids = list_song_ids_for_albums(
            session, expired_album_ids, include_deleted_rows=True,
        )
        for album in expired_albums:
            paths.extend(delete_album(session, album.id))
            deleted_album_ids.append(album.id)
            album_count += 1

        expired_songs = list_expired_songs(session, cutoff, expired_album_ids)
        for song in expired_songs:
            expired_song_ids.append(song.id)
            paths.extend(delete_song(session, song.id))
            deleted_orphan_song_ids.append(song.id)
            song_count += 1

        session.commit()

    for album_id in deleted_album_ids:
        log.info("cleanup_expired: hard-deleted album %s", album_id)
    for song_id in deleted_orphan_song_ids:
        log.info("cleanup_expired: hard-deleted orphan song %s", song_id)

    cleanup_generation_files(audio_dir, paths)
    for album_id in expired_album_ids:
        remove_album_cover_files(audio_dir, album_id)
        remove_album_cover_suggestion_files(audio_dir, album_id)
    for song_id in expired_song_ids:
        remove_song_cover_files(audio_dir, song_id)
    if album_count or song_count:
        log.info(
            "cleanup_expired: hard-deleted %d album(s) and %d orphan song(s)",
            album_count, song_count,
        )
    return album_count, song_count


def run_generation_retention(
    db_factory, audio_dir, *, dry_run: bool = False,
) -> GenerationRetentionReport:
    """Two-stage generation retention.

    Stage 1 — archive generations that are not picked/kept and older
    than `generation_retention_days`.

    Stage 2 — hard-delete (files + row) generations archived longer
    than `final_deletion_days` ago, unless referenced as a
    reproducibility anchor by another generation.

    Both stages re-check at their write, so a take that became a Pick or a
    Keep after selection is left alone. The report names the takes written.
    `dry_run=True` returns the IDs that would be affected without
    performing any writes.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    archive_cutoff = now - timedelta(days=settings.generation_retention_days)
    delete_cutoff = now - timedelta(days=settings.final_deletion_days)
    report = GenerationRetentionReport()

    with db_factory() as session:
        to_archive = sorted(
            g.id for g in list_generations_expired_for_archive(session, archive_cutoff)
        )
        to_delete = sorted(
            g.id for g in list_generations_expired_for_delete(session, delete_cutoff)
        )
    if dry_run:
        report.archived_ids, report.deleted_ids = to_archive, to_delete
        return report

    # One transaction per take: each locks only its own row, so a Pick or Keep
    # that commits first wins and no transaction waits for a second take while
    # holding the first.
    for gen_id in to_archive:
        with db_factory() as session:
            if archive_generation(session, gen_id) is None:
                continue
            session.commit()
        report.archived_ids.append(gen_id)

    for gen_id in to_delete:
        with db_factory() as session:
            paths = delete_expired_generation(session, gen_id, delete_cutoff)
            if paths is None:
                continue
            session.commit()
        cleanup_generation_files(audio_dir, paths)
        report.deleted_ids.append(gen_id)

    if report.archived_count or report.deleted_count:
        log.info(
            "generation_retention: archived=%d hard_deleted=%d",
            report.archived_count, report.deleted_count,
        )
    return report
