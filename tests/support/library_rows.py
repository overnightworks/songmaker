"""The builders of an album, song, version and take row for tests.

The ``a_*`` builders add and flush a row on a session; the ``loose_*`` ones build a row
that belongs to no session, for pure logic. Each ``a_*`` builder takes the session, then the
parameters of its ``loose_*`` twin.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Concatenate

from sqlalchemy.orm import Session

from songmaker_cli.db.models import Album, Generation, Song, Version


def _added[**Parameters, Row](
    build: Callable[Parameters, Row],
) -> Callable[Concatenate[Session, Parameters], Row]:
    """The twin of a ``loose_*`` builder that adds and flushes its row; the caller commits."""

    def add(session: Session, *args: Parameters.args, **kwargs: Parameters.kwargs) -> Row:
        row = build(*args, **kwargs)
        session.add(row)
        session.flush()
        return row

    return add


def loose_album(
    album_id: str,
    *,
    title: str = "Album",
    artist: str = "Artist",
    created_by: str | None = None,
    **fields: object,
) -> Album:
    """A row outside any session."""
    return Album(id=album_id, title=title, artist=artist, created_by=created_by, **fields)


def loose_song(
    song_id: str,
    album_id: str,
    *,
    title: str | None = None,
    track_number: int = 1,
    slug: str | None = None,
    **fields: object,
) -> Song:
    """A row outside any session; title and slug default to the id."""
    return Song(
        id=song_id,
        album_id=album_id,
        title=title or song_id,
        track_number=track_number,
        slug=slug or song_id,
        **fields,
    )


def loose_version(
    version_id: str,
    song_id: str,
    *,
    version_number: int = 1,
    lyrics: str = "",
    **fields: object,
) -> Version:
    """A row outside any session."""
    return Version(
        id=version_id,
        song_id=song_id,
        version_number=version_number,
        lyrics=lyrics,
        **fields,
    )


def loose_take(
    take_id: str,
    song_id: str,
    *,
    owner: str,
    version_id: str | None = None,
    generation_number: int = 1,
    seed: int | None = 1,
    mp3_path: str | None = None,
    **fields: object,
) -> Generation:
    """A row outside any session; without ``mp3_path`` the audio is ``<owner>/<take_id>.mp3``."""
    return Generation(
        id=take_id,
        song_id=song_id,
        version_id=version_id,
        generation_number=generation_number,
        seed=seed,
        mp3_path=mp3_path if mp3_path is not None else f"{owner}/{take_id}.mp3",
        **fields,
    )


an_album = _added(loose_album)
a_song = _added(loose_song)
a_version = _added(loose_version)
a_take = _added(loose_take)
