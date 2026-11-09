"""Query functions for durable co-writer user, song, and album memory."""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from songmaker_cli.db.models import (
    CowriterAlbumMemory,
    CowriterSongMemory,
    CowriterUserMemory,
)
from songmaker_cli.timestamps import utcnow


def get_user_memory(session: Session, user_id: str) -> CowriterUserMemory | None:
    return session.query(CowriterUserMemory).filter_by(user_id=user_id).first()


def get_song_memory(session: Session, song_id: str) -> CowriterSongMemory | None:
    return session.query(CowriterSongMemory).filter_by(song_id=song_id).first()


def get_album_memory(session: Session, album_id: str) -> CowriterAlbumMemory | None:
    return session.query(CowriterAlbumMemory).filter_by(album_id=album_id).first()


def _upsert_memory[Row: CowriterUserMemory | CowriterSongMemory | CowriterAlbumMemory](
    session: Session, model: type[Row], key_column: str, key: str, body: str,
) -> Row:
    """Write the note in one statement, so two first writes of one key both succeed and
    the later body stays, then reload the stored row."""
    session.execute(
        insert(model)
        .values({key_column: key, "body": body})
        .on_conflict_do_update(
            index_elements=[key_column], set_={"body": body, "updated_at": utcnow()},
        ),
    )
    return session.query(model).filter_by(**{key_column: key}).populate_existing().one()


def upsert_user_memory(session: Session, user_id: str, body: str) -> CowriterUserMemory:
    return _upsert_memory(session, CowriterUserMemory, "user_id", user_id, body)


def upsert_song_memory(session: Session, song_id: str, body: str) -> CowriterSongMemory:
    return _upsert_memory(session, CowriterSongMemory, "song_id", song_id, body)


def upsert_album_memory(session: Session, album_id: str, body: str) -> CowriterAlbumMemory:
    return _upsert_memory(session, CowriterAlbumMemory, "album_id", album_id, body)
