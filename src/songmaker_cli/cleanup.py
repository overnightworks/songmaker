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
from songmaker_cli.covers import remove_album_cover_files, remove_song_cover_files
from songmaker_cli.db.queries import (
    archive_generation,
    delete_album,
    delete_generation,
    delete_song,
    list_expired_albums,
    list_expired_songs,
    list_generations_expired_for_archive,
    list_generations_expired_for_delete,
    list_song_ids_for_albums,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)


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
        days=get_settings().soft_delete_retention_days,
    )
    paths: list[str] = []
    album_count = 0
    song_count = 0

    with db_factory() as session:
        expired_albums = list_expired_albums(session, cutoff)
        expired_album_ids = [a.id for a in expired_albums]
        expired_song_ids = list_song_ids_for_albums(
            session, expired_album_ids, include_deleted_rows=True,
        )
        for album in expired_albums:
            paths.extend(delete_album(session, album.id))
            album_count += 1

        expired_songs = list_expired_songs(session, cutoff, expired_album_ids)
        for song in expired_songs:
            expired_song_ids.append(song.id)
            paths.extend(delete_song(session, song.id))
            song_count += 1

        session.commit()

    cleanup_generation_files(audio_dir, paths)
    for album_id in expired_album_ids:
        remove_album_cover_files(audio_dir, album_id)
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
    than `generation_hard_delete_days` ago, unless referenced as a
    reproducibility anchor by another generation.

    `dry_run=True` returns the IDs that would be affected without
    performing any writes.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    archive_cutoff = now - timedelta(days=settings.generation_retention_days)
    delete_cutoff = now - timedelta(days=settings.generation_hard_delete_days)
    report = GenerationRetentionReport()
    paths: list[str] = []

    with db_factory() as session:
        to_archive = list_generations_expired_for_archive(session, archive_cutoff)
        report.archived_ids = [g.id for g in to_archive]

        to_delete = list_generations_expired_for_delete(session, delete_cutoff)
        report.deleted_ids = [g.id for g in to_delete]

        if dry_run:
            return report

        for gen in to_archive:
            archive_generation(session, gen.id)

        for gen_id in report.deleted_ids:
            paths.extend(delete_generation(session, gen_id))

        session.commit()

    cleanup_generation_files(audio_dir, paths)
    if report.archived_count or report.deleted_count:
        log.info(
            "generation_retention: archived=%d hard_deleted=%d",
            report.archived_count, report.deleted_count,
        )
    return report
