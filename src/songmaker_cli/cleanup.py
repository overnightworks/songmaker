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
from songmaker_cli.db.advisory_locks import AdvisoryLock, lock_until_transaction_ends
from songmaker_cli.db.models import Song
from songmaker_cli.db.queries.albums import delete_album, list_expired_albums
from songmaker_cli.db.queries.generations import (
    archive_generation,
    delete_expired_generation,
    list_generations_expired_for_archive,
    list_generations_expired_for_delete,
    lock_songs,
)
from songmaker_cli.db.queries.jobs import ActiveJobError
from songmaker_cli.db.queries.reference_recordings import linked_reference_ids
from songmaker_cli.db.queries.songs import delete_song, list_expired_songs, list_song_ids_for_albums
from songmaker_cli.db.soft_delete import soft_delete_cutoff
from songmaker_cli.reference_audio import commit_unused_stamps
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

# The music worker runs its daily cleanup jobs at this hour, in UTC; the admin page names it.
DAILY_CLEANUP_HOUR_UTC = 3


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


@dataclass(frozen=True, slots=True)
class _ExpiredPurge:
    paths: list[str]
    album_ids: list[str]
    orphan_song_ids: list[str]
    song_ids: list[str]
    reference_candidates: set[str]


def _purge_expired(session, cutoff: datetime) -> _ExpiredPurge:
    """Delete the expired albums, then the orphan songs, and flush; the caller commits.

    Purge runs serialize on one transaction-scoped lock, taken before the listings, so two
    runs never overlap and never wait on each other in a cycle. Every listed song is then
    locked at once, in id order; a candidate restored since its listing is skipped and stays
    out of the result. An album or song with a queued or running job is left for a later run
    and stays out of the result.
    """
    lock_until_transaction_ends(session, AdvisoryLock.PURGE)
    expired_album_ids = [album.id for album in list_expired_albums(session, cutoff)]
    orphan_song_candidates = [
        song.id for song in list_expired_songs(session, cutoff, expired_album_ids)
    ]
    album_songs = {
        album_id: list_song_ids_for_albums(session, [album_id], include_deleted_rows=True)
        for album_id in expired_album_ids
    }
    lock_songs(
        session,
        Song.id.in_([*orphan_song_candidates, *(id for ids in album_songs.values() for id in ids)]),
    )
    still_expired_album_ids = {album.id for album in list_expired_albums(session, cutoff)}
    still_expired_song_ids = {
        song.id for song in list_expired_songs(session, cutoff, list(still_expired_album_ids))
    }
    paths: list[str] = []
    album_ids: list[str] = []
    orphan_song_ids: list[str] = []
    song_ids: list[str] = []
    reference_candidates: set[str] = set()
    for album_id, album_song_ids in album_songs.items():
        if album_id not in still_expired_album_ids:
            continue
        linked = linked_reference_ids(session, album_song_ids)
        try:
            paths.extend(delete_album(session, album_id))
        except ActiveJobError:
            continue
        album_ids.append(album_id)
        song_ids.extend(album_song_ids)
        reference_candidates |= linked
    for song_id in orphan_song_candidates:
        if song_id not in still_expired_song_ids:
            continue
        linked = linked_reference_ids(session, [song_id])
        try:
            paths.extend(delete_song(session, song_id))
        except ActiveJobError:
            continue
        orphan_song_ids.append(song_id)
        song_ids.append(song_id)
        reference_candidates |= linked
    return _ExpiredPurge(paths, album_ids, orphan_song_ids, song_ids, reference_candidates)


def run_cleanup_expired(
    db_factory, audio_dir, *, now: datetime | None = None,
) -> tuple[int, int]:
    """Hard-delete expired soft-deleted albums and orphan songs.

    Returns (album_count, song_count). Albums are removed first, then
    orphan songs whose parent album was *not* in the expired set —
    songs deleted earlier than their (still-live) album. After the commit the
    references the deleted songs alone linked are stamped unused; a failed stamp
    changes neither the counts nor the file removals.
    """
    cutoff = soft_delete_cutoff(now or datetime.now(timezone.utc))
    with db_factory() as session:
        purge = _purge_expired(session, cutoff)
        session.commit()
        commit_unused_stamps(session, purge.reference_candidates)

    for album_id in purge.album_ids:
        log.info("cleanup_expired: hard-deleted album %s", album_id)
    for song_id in purge.orphan_song_ids:
        log.info("cleanup_expired: hard-deleted orphan song %s", song_id)

    cleanup_generation_files(audio_dir, purge.paths)
    for album_id in purge.album_ids:
        remove_album_cover_files(audio_dir, album_id)
        remove_album_cover_suggestion_files(audio_dir, album_id)
    for song_id in purge.song_ids:
        remove_song_cover_files(audio_dir, song_id)
    album_count, song_count = len(purge.album_ids), len(purge.orphan_song_ids)
    if album_count or song_count:
        log.info(
            "cleanup_expired: hard-deleted %d album(s) and %d orphan song(s)",
            album_count, song_count,
        )
    return album_count, song_count


def _delete_expired_takes(
    db_factory, audio_dir, reference_by_take: dict[str, str | None], cutoff: datetime,
) -> list[str]:
    """Delete each take that still qualifies, stamp its reference, unlink; return its ids."""
    deleted_ids: list[str] = []
    for gen_id, reference_id in reference_by_take.items():
        with db_factory() as session:
            paths = delete_expired_generation(session, gen_id, cutoff)
            if paths is None:
                continue
            session.commit()
            commit_unused_stamps(session, {reference_id} if reference_id else set())
        cleanup_generation_files(audio_dir, paths)
        deleted_ids.append(gen_id)
    return deleted_ids


def run_generation_retention(
    db_factory, audio_dir, *, dry_run: bool = False, now: datetime | None = None,
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
    performing any writes. `now` fixes the clock both cutoffs measure from.
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    archive_cutoff = now - timedelta(days=settings.generation_retention_days)
    delete_cutoff = now - timedelta(days=settings.final_deletion_days)
    report = GenerationRetentionReport()

    with db_factory() as session:
        to_archive = sorted(
            g.id for g in list_generations_expired_for_archive(session, archive_cutoff)
        )
        reference_by_take = {
            g.id: g.reference_recording_id
            for g in sorted(
                list_generations_expired_for_delete(session, delete_cutoff), key=lambda g: g.id,
            )
        }
    if dry_run:
        report.archived_ids, report.deleted_ids = to_archive, list(reference_by_take)
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

    report.deleted_ids = _delete_expired_takes(
        db_factory, audio_dir, reference_by_take, delete_cutoff,
    )

    if report.archived_count or report.deleted_count:
        log.info(
            "generation_retention: archived=%d hard_deleted=%d",
            report.archived_count, report.deleted_count,
        )
    return report
