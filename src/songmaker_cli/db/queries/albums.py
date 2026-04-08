"""Query functions for albums — CRUD, sharing, cleanup, deletion."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.constants import RESTORE_WINDOW
from songmaker_cli.db.models import Album, Generation, Song
from songmaker_cli.db.queries.sharing import disable_sharing, enable_sharing
from songmaker_cli.db.soft_delete import include_deleted

log = logging.getLogger(__name__)


class RestoreWindowExpiredError(Exception):
    """Raised when restore is attempted past RESTORE_WINDOW."""


def list_albums(
    session: Session,
    user_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> list[Album]:
    query = session.query(Album).options(joinedload(Album.songs))
    if user_id:
        query = query.filter_by(created_by=user_id)
    query = query.order_by(Album.title).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_albums(session: Session, user_id: str | None = None) -> int:
    query = session.query(Album)
    if user_id:
        query = query.filter_by(created_by=user_id)
    return query.count()


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


def get_album_by_slug(session: Session, slug: str) -> Album | None:
    return (
        session.query(Album)
        .options(
            joinedload(Album.songs)
            .joinedload(Song.generations),
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

    Raises RestoreWindowExpiredError if past RESTORE_WINDOW.
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
    if age > RESTORE_WINDOW:
        raise RestoreWindowExpiredError(
            f"Album {album_id} was deleted {age.days} days ago, "
            f"past the {RESTORE_WINDOW.days}-day restore window",
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


def list_expired_albums(session: Session, cutoff: datetime) -> list[Album]:
    """Return soft-deleted albums whose deleted_at < cutoff. For cleanup_expired."""
    return (
        session.query(Album)
        .execution_options(include_deleted=True)
        .filter(Album.deleted_at.isnot(None), Album.deleted_at < cutoff)
        .all()
    )
