"""Query functions for albums — CRUD, sharing, cleanup, deletion."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import Album, Generation, Song
from songmaker_cli.db.queries.library import apply_library_sort, title_matches
from songmaker_cli.db.queries.sentinels import UNSET, _Unset
from songmaker_cli.db.queries.sharing import disable_sharing, enable_sharing
from songmaker_cli.db.soft_delete import include_deleted
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)


class RestoreWindowExpiredError(Exception):
    """Raised when restore is attempted past the soft-delete restore window."""


def list_albums(
    session: Session,
    user_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    q: str | None = None,
    sort: str | None = None,
    archived: bool = False,
) -> list[Album]:
    query = _album_query(session, user_id=user_id, q=q, archived=archived)
    if sort is None:
        query = query.order_by(Album.title, Album.id)
    else:
        query = apply_library_sort(query, Album, sort)
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_albums(
    session: Session,
    user_id: str | None = None,
    q: str | None = None,
    archived: bool = False,
) -> int:
    return _album_query(session, user_id=user_id, q=q, archived=archived).count()


def _album_query(
    session: Session,
    user_id: str | None = None,
    q: str | None = None,
    archived: bool = False,
):
    query = session.query(Album).filter(Album.is_archived.is_(archived))
    if user_id:
        query = query.filter_by(created_by=user_id)
    if q:
        query = query.filter(title_matches(Album.title, q))
    return query


def count_picked_songs_by_album(
    session: Session, album_ids: Sequence[str],
) -> dict[str, int]:
    """Count songs with an active picked generation, grouped by album.

    One aggregate query rather than a per-album loop over loaded
    generations — keeps album list/detail responses free of N+1 queries.
    A song counts once even if (impossibly) it had more than one active
    pick, since is_picked is exclusive per song.
    """
    if not album_ids:
        return {}
    rows = (
        session.query(Song.album_id, func.count(func.distinct(Song.id)))
        .join(Generation, Generation.song_id == Song.id)
        .filter(
            Song.album_id.in_(album_ids),
            Generation.is_picked == True,  # noqa: E712
            Generation.is_archived == False,  # noqa: E712
        )
        .group_by(Song.album_id)
        .all()
    )
    return dict(rows)


def count_songs_by_album(
    session: Session, album_ids: Sequence[str],
) -> dict[str, int]:
    """Count songs per album, grouped.

    One aggregate query rather than a joinedload(Album.songs) whose only
    purpose was AlbumResponse.from_orm's len(album.songs) — keeps album
    list/detail responses free of the eager-loaded songs collection
    entirely. Mirrors count_picked_songs_by_album().
    """
    if not album_ids:
        return {}
    rows = (
        session.query(Song.album_id, func.count(Song.id))
        .filter(Song.album_id.in_(album_ids))
        .group_by(Song.album_id)
        .all()
    )
    return dict(rows)


def get_album(
    session: Session, album_id: str, *, include_deleted_rows: bool = False,
) -> Album | None:
    query = session.query(Album)
    if include_deleted_rows:
        query = query.execution_options(include_deleted=True)
    return query.filter_by(id=album_id).first()


def create_album(
    session: Session,
    album_id: str,
    title: str,
    artist: str = "",
    created_by: str | None = None,
) -> Album:
    album = Album(id=album_id, title=title, artist=artist, created_by=created_by)
    session.add(album)
    session.flush()
    log.info("Created album '%s' (id=%s, owner=%s)", title, album_id, created_by)
    return album


def update_album(
    session: Session,
    album_id: str,
    title: str | None = None,
    subtitle: str | _Unset = UNSET,
    year: str | _Unset = UNSET,
) -> Album:
    """Partially update album metadata.

    `title` of `None` and `subtitle`/`year` of `UNSET` leave that field
    untouched, letting callers update title, subtitle, and year independently.
    """
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    applied: dict[str, str] = {}
    if title is not None:
        album.title = title
        applied["title"] = title
    if not isinstance(subtitle, _Unset):
        album.subtitle = subtitle
        applied["subtitle"] = subtitle
    if not isinstance(year, _Unset):
        album.year = year
        applied["year"] = year
    session.flush()
    log.info("Updated album %s: %s", album_id, applied)
    return album


def set_album_cover_key(session: Session, album_id: str, cover_key: str | None) -> Album:
    album = get_album(session, album_id)
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    album.cover_key = cover_key
    session.flush()
    log.info("Set album %s cover_key=%r", album_id, cover_key)
    return album


def get_album_by_slug(session: Session, slug: str) -> Album | None:
    return (
        session.query(Album)
        .options(
            joinedload(Album.songs)
            .joinedload(Song.generations)
            .joinedload(Generation.version),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_album_sharing(session: Session, album_id: str) -> Album:
    return enable_sharing(session, Album, album_id)


def disable_album_sharing(session: Session, album_id: str) -> Album:
    return disable_sharing(session, Album, album_id)


def cleanup_album(session: Session, album_id: str) -> tuple[int, list[str]]:
    """Remove unpicked generations. Returns (count, paths) for post-commit cleanup."""
    gens = (
        session.query(Generation)
        .join(Song)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter(
            Song.album_id == album_id,
            Generation.is_picked == False,  # noqa: E712
            Generation.is_kept == False,  # noqa: E712
        )
        .all()
    )
    count = len(gens)
    paths: list[str] = []
    for gen in gens:
        for p in [gen.mp3_path, gen.wav_path]:
            if p:
                paths.append(p)
        session.delete(gen)
    session.flush()

    return count, paths


def soft_delete_album(session: Session, album_id: str) -> datetime:
    """Mark an album as soft-deleted. Cascades to live songs.

    Songs that were already soft-deleted (individually, before the album
    delete) are left alone — see restore_album for the matching restore
    semantics.
    """
    album = get_album(session, album_id)
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    now = datetime.now(timezone.utc)
    album.deleted_at = now
    for song in album.songs:
        if song.deleted_at is None:
            song.deleted_at = now
    session.flush()
    log.info("Soft-deleted album %s", album_id)
    return now


def restore_album(session: Session, album_id: str) -> Album:
    """Clear deleted_at on the album and on songs sharing the cascade timestamp.

    Songs deleted *before* the album was deleted (different timestamp)
    stay deleted, preserving the user's earlier intent.

    Raises RestoreWindowExpiredError if past the soft-delete restore window.
    Raises ValueError if the album doesn't exist.
    """
    album = get_album(session, album_id, include_deleted_rows=True)
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    if album.deleted_at is None:
        return album
    deleted_at = album.deleted_at
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - deleted_at
    window = timedelta(days=get_settings().soft_delete_retention_days)
    if age > window:
        raise RestoreWindowExpiredError(
            f"Album {album_id} was deleted {age.days} days ago, "
            f"past the {window.days}-day restore window",
        )
    cascade_ts = album.deleted_at
    album.deleted_at = None
    with include_deleted(session):
        songs = session.query(Song).filter_by(album_id=album_id).all()
        for song in songs:
            song_ts = song.deleted_at
            if song_ts is None:
                continue
            if song_ts.tzinfo is None:
                song_ts = song_ts.replace(tzinfo=timezone.utc)
            cascade_norm = cascade_ts
            if cascade_norm.tzinfo is None:
                cascade_norm = cascade_norm.replace(tzinfo=timezone.utc)
            if song_ts == cascade_norm:
                song.deleted_at = None
    session.flush()
    log.info("Restored album %s", album_id)
    return album


def delete_album(session: Session, album_id: str) -> list[str]:
    """Hard-delete an album and return file paths for post-commit cleanup.

    Sees soft-deleted albums (used by cleanup_expired and hard_delete_user).
    """
    with include_deleted(session):
        album = session.query(Album).filter_by(id=album_id).first()
        if not album:
            raise ValueError(f"Album not found: {album_id}")

        gens = (
            session.query(Generation)
            .join(Song)
            .options(joinedload(Generation.scores), joinedload(Generation.rating))
            .filter(Song.album_id == album_id)
            .all()
        )
        paths: list[str] = []
        for gen in gens:
            for p in [gen.mp3_path, gen.wav_path]:
                if p:
                    paths.append(p)
            session.delete(gen)

        session.delete(album)
        session.flush()

    log.info("Hard-deleted album %s", album_id)
    return paths


def archive_album(session: Session, album_id: str) -> Album:
    """Hide an album from the default library, search, and mix/pool.

    A visibility flag, not a soft-delete: the album's data, songs, and any
    existing share links are untouched and keep working (see get_album_by_slug).
    """
    album = get_album(session, album_id)
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    album.is_archived = True
    album.archived_at = datetime.now(timezone.utc)
    session.flush()
    log.info("Archived album %s", album_id)
    return album


def unarchive_album(session: Session, album_id: str) -> Album:
    album = get_album(session, album_id)
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    album.is_archived = False
    album.archived_at = None
    session.flush()
    log.info("Unarchived album %s", album_id)
    return album


def list_expired_albums(session: Session, cutoff: datetime) -> list[Album]:
    """Return soft-deleted albums whose deleted_at < cutoff. For cleanup_expired."""
    return (
        session.query(Album)
        .execution_options(include_deleted=True)
        .filter(Album.deleted_at.isnot(None), Album.deleted_at < cutoff)
        .all()
    )
