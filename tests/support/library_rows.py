"""The builders of an album, song, version and take row for tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, Generation, Song, Version


def an_album(
    session: Session, album_id: str, *, title: str = "Album", artist: str = "Artist",
    created_by: str | None = None, **fields: object,
) -> Album:
    """Add and flush the row; the caller commits."""
    row = Album(id=album_id, title=title, artist=artist, created_by=created_by, **fields)
    session.add(row)
    session.flush()
    return row


def a_song(
    session: Session, song_id: str, album_id: str, *, title: str | None = None,
    track_number: int = 1, slug: str | None = None, **fields: object,
) -> Song:
    """Add and flush the row; title and slug default to the id."""
    row = Song(
        id=song_id, album_id=album_id, title=title or song_id, track_number=track_number,
        slug=slug or song_id, **fields,
    )
    session.add(row)
    session.flush()
    return row


def a_version(
    session: Session, version_id: str, song_id: str, *, version_number: int = 1,
    lyrics: str = "", **fields: object,
) -> Version:
    """Add and flush the row; the caller commits."""
    row = Version(
        id=version_id, song_id=song_id, version_number=version_number, lyrics=lyrics, **fields,
    )
    session.add(row)
    session.flush()
    return row


def a_take(
    session: Session, take_id: str, song_id: str, *, owner: str, version_id: str | None = None,
    generation_number: int = 1, seed: int | None = 1, mp3_path: str | None = None, **fields: object,
) -> Generation:
    """Add and flush the row; without ``mp3_path`` the audio is ``<owner>/<take_id>.mp3``."""
    row = Generation(
        id=take_id, song_id=song_id, version_id=version_id, generation_number=generation_number,
        seed=seed, mp3_path=mp3_path if mp3_path is not None else f"{owner}/{take_id}.mp3",
        **fields,
    )
    session.add(row)
    session.flush()
    return row
