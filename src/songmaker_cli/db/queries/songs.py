"""Query functions for songs — CRUD, move, archive."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    Album,
    Generation,
    Song,
    Version,
)

log = logging.getLogger(__name__)


class _Unset:
    """Sentinel distinguishing 'not provided' from None."""

UNSET = _Unset()


def list_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
    light: bool = False,
    offset: int = 0,
    limit: int | None = None,
) -> list[Song]:
    if light:
        query = (
            session.query(Song)
            .options(
                joinedload(Song.versions),
                joinedload(Song.generations),
                joinedload(Song.album),
            )
            .order_by(Song.album_id, Song.track_number)
        )
    else:
        query = (
            session.query(Song)
            .options(
                joinedload(Song.versions),
                joinedload(Song.generations).joinedload(Generation.scores),
                joinedload(Song.generations).joinedload(Generation.rating),
                joinedload(Song.album),
            )
            .order_by(Song.album_id, Song.track_number)
        )
    if album_id:
        query = query.filter_by(album_id=album_id)
    if user_id:
        query = query.join(Album).filter(Album.created_by == user_id)
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
) -> int:
    query = session.query(Song)
    if album_id:
        query = query.filter_by(album_id=album_id)
    if user_id:
        query = query.join(Album).filter(Album.created_by == user_id)
    return query.count()


def get_song(session: Session, song_id: str) -> Song | None:
    return (
        session.query(Song)
        .options(
            joinedload(Song.versions),
            joinedload(Song.generations).joinedload(Generation.scores),
            joinedload(Song.generations).joinedload(Generation.rating),
            joinedload(Song.album),
        )
        .filter_by(id=song_id)
        .first()
    )


def create_song(
    session: Session,
    title: str,
    album_id: str,
    lyrics: str = "",
    prompt: str = "",
    bpm: int = 0,
    duration: int = 180,
    key: str = "",
    language: str = "",
    generation_params: dict | None = None,
) -> Song:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")

    track_query = (
        session.query(Song.track_number)
        .filter_by(album_id=album_id)
        .order_by(Song.track_number.desc())
    )
    if session.bind.dialect.name != "sqlite":
        track_query = track_query.with_for_update()
    max_track = track_query.first()
    track_number = (max_track[0] + 1) if max_track else 1

    song = Song(
        title=title, album_id=album_id, language=language, track_number=track_number,
    )
    session.add(song)
    session.flush()

    version = Version(
        song_id=song.id, version_number=1,
        lyrics=lyrics, prompt=prompt, bpm=bpm, duration=duration, key=key,
        generation_params=generation_params,
    )
    session.add(version)
    session.flush()
    log.info("Created song '%s' (id=%s) in album '%s'", title, song.id, album_id)
    return song


def update_song(
    session: Session,
    song_id: str,
    lyrics: str | None = None,
    prompt: str | None = None,
    bpm: int | None = None,
    duration: int | None = None,
    key: str | None = None,
    generation_params: dict | None | _Unset = UNSET,
) -> Version:
    song = get_song(session, song_id)
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    prev = song.latest_version

    if isinstance(generation_params, _Unset):
        new_gen_params = prev.generation_params if prev else None
        prev_num = prev.version_number if prev else 0
        log.debug("generation_params not provided, carrying forward from v%d", prev_num)
    else:
        new_gen_params = generation_params or None

    new_lyrics = lyrics if lyrics is not None else (prev.lyrics if prev else "")
    new_prompt = prompt if prompt is not None else (prev.prompt if prev else "")
    new_bpm = bpm if bpm is not None else (prev.bpm if prev else 0)
    new_duration = duration if duration is not None else (prev.duration if prev else 180)
    new_key = key if key is not None else (prev.key if prev else "")

    if prev and not prev.generations:
        prev.lyrics = new_lyrics
        prev.prompt = new_prompt
        prev.bpm = new_bpm
        prev.duration = new_duration
        prev.key = new_key
        prev.generation_params = new_gen_params
        session.flush()
        log.info("Updated song %s v%d in-place", song_id, prev.version_number)
        return prev

    next_num = (prev.version_number + 1) if prev else 1
    version = Version(
        song_id=song_id,
        version_number=next_num,
        lyrics=new_lyrics,
        prompt=new_prompt,
        bpm=new_bpm,
        duration=new_duration,
        key=new_key,
        generation_params=new_gen_params,
    )
    session.add(version)
    session.flush()
    log.info("Updated song %s → v%d", song_id, next_num)
    return version


def move_song(session: Session, song_id: str, new_album_id: str) -> Song:
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    new_album = session.query(Album).filter_by(id=new_album_id).first()
    if not new_album:
        raise ValueError(f"Album not found: {new_album_id}")

    if song.album_id == new_album_id:
        return song

    old_album_id = song.album_id
    song.album_id = new_album_id
    session.flush()
    log.info("Moved song %s from album %s to %s", song_id, old_album_id, new_album_id)
    return song
