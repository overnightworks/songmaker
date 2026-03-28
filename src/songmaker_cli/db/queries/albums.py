"""Query functions for albums — CRUD, sharing, cleanup, deletion."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import Album, Generation, Song

log = logging.getLogger(__name__)


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


def get_album(session: Session, album_id: str) -> Album | None:
    return session.query(Album).filter_by(id=album_id).first()


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
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    if not album.share_slug:
        album.share_slug = str(uuid.uuid4())
    album.is_shared = True
    session.flush()
    log.info("Enabled sharing for album %s (slug=%s)", album_id, album.share_slug)
    return album


def disable_album_sharing(session: Session, album_id: str) -> Album:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    album.share_slug = None
    album.is_shared = False
    session.flush()
    log.info("Disabled sharing for album %s", album_id)
    return album


def cleanup_album(session: Session, album_id: str) -> tuple[int, list[str]]:
    """Remove unpicked generations. Returns (count, paths) for post-commit cleanup."""
    gens = (
        session.query(Generation)
        .join(Song)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter(Song.album_id == album_id, Generation.is_picked == False)  # noqa: E712
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


def delete_album(session: Session, album_id: str) -> list[str]:
    """Delete an album and return file paths for post-commit cleanup."""
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

    log.info("Deleted album %s", album_id)
    return paths
