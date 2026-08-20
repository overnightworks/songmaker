"""Query functions for durable co-writer user, song, and album memory."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from songmaker_cli.db.models import (
    CowriterAlbumMemory,
    CowriterSongMemory,
    CowriterUserMemory,
)


def get_user_memory(session: Session, user_id: str) -> CowriterUserMemory | None:
    return session.query(CowriterUserMemory).filter_by(user_id=user_id).first()


def get_song_memory(session: Session, song_id: str) -> CowriterSongMemory | None:
    return session.query(CowriterSongMemory).filter_by(song_id=song_id).first()


def get_album_memory(session: Session, album_id: str) -> CowriterAlbumMemory | None:
    return session.query(CowriterAlbumMemory).filter_by(album_id=album_id).first()


def upsert_user_memory(
    session: Session, user_id: str, body: str,
) -> CowriterUserMemory:
    existing = get_user_memory(session, user_id)
    if existing is None:
        existing = CowriterUserMemory(user_id=user_id, body=body)
        session.add(existing)
    else:
        existing.body = body
        existing.updated_at = datetime.now(timezone.utc)
    session.flush()
    return existing


def upsert_song_memory(
    session: Session, song_id: str, body: str,
) -> CowriterSongMemory:
    existing = get_song_memory(session, song_id)
    if existing is None:
        existing = CowriterSongMemory(song_id=song_id, body=body)
        session.add(existing)
    else:
        existing.body = body
        existing.updated_at = datetime.now(timezone.utc)
    session.flush()
    return existing


def upsert_album_memory(
    session: Session, album_id: str, body: str,
) -> CowriterAlbumMemory:
    existing = get_album_memory(session, album_id)
    if existing is None:
        existing = CowriterAlbumMemory(album_id=album_id, body=body)
        session.add(existing)
    else:
        existing.body = body
        existing.updated_at = datetime.now(timezone.utc)
    session.flush()
    return existing
