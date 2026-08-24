"""Query functions for songs — CRUD, move, archive, sharing."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Final

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    Album,
    Generation,
    Song,
    Version,
)
from songmaker_cli.db.queries.albums import RestoreWindowExpiredError
from songmaker_cli.db.queries.library import apply_library_sort, title_matches
from songmaker_cli.db.queries.sentinels import UNSET, _Unset
from songmaker_cli.db.queries.sharing import disable_sharing, enable_sharing
from songmaker_cli.db.soft_delete import include_deleted
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

INITIAL_TRACK_NUMBER: Final[int] = 1


def list_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
    light: bool = False,
    offset: int = 0,
    limit: int | None = None,
    q: str | None = None,
    sort: str | None = None,
    exclude_archived_albums: bool = False,
) -> list[Song]:
    if light:
        query = session.query(Song).options(
            joinedload(Song.versions),
            joinedload(Song.album),
        )
    else:
        query = session.query(Song).options(
            joinedload(Song.versions),
            joinedload(Song.generations).joinedload(Generation.scores),
            joinedload(Song.generations).joinedload(Generation.rating),
            joinedload(Song.generations).joinedload(Generation.src_generation),
            joinedload(Song.generations).joinedload(Generation.version),
            joinedload(Song.album),
        )
    query = _apply_song_filters(
        query, album_id=album_id, user_id=user_id, q=q,
        exclude_archived_albums=exclude_archived_albums,
    )
    if sort is None:
        query = query.order_by(Song.album_id, Song.track_number, Song.id)
    else:
        query = apply_library_sort(query, Song, sort)
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
    q: str | None = None,
    exclude_archived_albums: bool = False,
) -> int:
    query = session.query(Song)
    query = _apply_song_filters(
        query, album_id=album_id, user_id=user_id, q=q,
        exclude_archived_albums=exclude_archived_albums,
    )
    return query.count()


def _apply_song_filters(
    query,
    *,
    album_id: str | None,
    user_id: str | None,
    q: str | None,
    exclude_archived_albums: bool = False,
):
    if album_id:
        query = query.filter_by(album_id=album_id)
    joined_album = False
    if user_id:
        query = query.join(Album).filter(Album.created_by == user_id)
        joined_album = True
    if exclude_archived_albums:
        if not joined_album:
            query = query.join(Album)
        query = query.filter(Album.is_archived.is_(False))
    if q:
        query = query.filter(title_matches(Song.title, q))
    return query


def get_song(
    session: Session, song_id: str, *, include_deleted_rows: bool = False,
) -> Song | None:
    query = session.query(Song).options(
        joinedload(Song.versions),
        joinedload(Song.generations).joinedload(Generation.scores),
        joinedload(Song.generations).joinedload(Generation.rating),
        joinedload(Song.generations).joinedload(Generation.src_generation),
        joinedload(Song.generations).joinedload(Generation.version),
        joinedload(Song.album),
    )
    if include_deleted_rows:
        query = query.execution_options(include_deleted=True)
    return query.filter_by(id=song_id).first()


def set_song_cover_key(session: Session, song_id: str, cover_key: str | None) -> Song:
    song = get_song(session, song_id)
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    song.cover_key = cover_key
    session.flush()
    log.info("Set song %s cover_key=%r", song_id, cover_key)
    return song


def list_song_ids_for_albums(
    session: Session, album_ids: list[str], *, include_deleted_rows: bool = False,
) -> list[str]:
    if not album_ids:
        return []
    query = session.query(Song.id).filter(Song.album_id.in_(album_ids))
    if include_deleted_rows:
        query = query.execution_options(include_deleted=True)
    return [song_id for (song_id,) in query.all()]


def list_song_ids_for_owner(session: Session, user_id: str) -> list[str]:
    query = (
        session.query(Song.id)
        .join(Album)
        .filter(Album.created_by == user_id)
        .execution_options(include_deleted=True)
    )
    return [song_id for (song_id,) in query.all()]


def create_song(
    session: Session,
    title: str,
    album_id: str,
    lyrics: str = "",
    prompt: str = "",
    bpm: int = 0,
    audio_duration: int = 180,
    key_scale: str = "",
    vocal_language: str = "",
    generation_params: dict | None = None,
) -> Song:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")

    track_query = (
        session.query(Song.track_number)
        .execution_options(include_deleted=True)
        .filter_by(album_id=album_id)
        .order_by(Song.track_number.desc())
    )
    if session.bind.dialect.name != "sqlite":
        track_query = track_query.with_for_update()
    max_track = track_query.first()
    track_number = (max_track[0] + 1) if max_track else INITIAL_TRACK_NUMBER

    song = Song(
        title=title, album_id=album_id, vocal_language=vocal_language,
        track_number=track_number,
    )
    session.add(song)
    session.flush()

    version = Version(
        song_id=song.id, version_number=1,
        lyrics=lyrics, prompt=prompt, bpm=bpm,
        audio_duration=audio_duration, key_scale=key_scale,
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
    audio_duration: int | None = None,
    key_scale: str | None = None,
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
    new_audio_duration = (
        audio_duration if audio_duration is not None
        else (prev.audio_duration if prev else 180)
    )
    new_key_scale = (
        key_scale if key_scale is not None else (prev.key_scale if prev else "")
    )

    creative_changed = prev is None or (
        new_lyrics != prev.lyrics
        or new_prompt != prev.prompt
        or new_bpm != prev.bpm
        or new_audio_duration != prev.audio_duration
        or new_key_scale != prev.key_scale
    )

    if prev and (not prev.generations or not creative_changed):
        prev.lyrics = new_lyrics
        prev.prompt = new_prompt
        prev.bpm = new_bpm
        prev.audio_duration = new_audio_duration
        prev.key_scale = new_key_scale
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
        audio_duration=new_audio_duration,
        key_scale=new_key_scale,
        generation_params=new_gen_params,
    )
    session.add(version)
    session.flush()
    log.info("Updated song %s → v%d", song_id, next_num)
    return version


def delete_song(session: Session, song_id: str) -> list[str]:
    """Hard-delete a song and all its versions/generations.

    Sees soft-deleted songs (used by cleanup_expired). Returns file paths
    for post-commit cleanup.
    """
    with include_deleted(session):
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            raise ValueError(f"Song not found: {song_id}")

        paths = [
            p for g in song.generations
            for p in [g.mp3_path, g.wav_path] if p
        ]
        session.delete(song)
        session.flush()
    log.info("Hard-deleted song %s", song_id)
    return paths


def soft_delete_song(session: Session, song_id: str) -> datetime:
    """Mark a single song as soft-deleted."""
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    now = datetime.now(timezone.utc)
    song.deleted_at = now
    session.flush()
    log.info("Soft-deleted song %s", song_id)
    return now


def restore_song(session: Session, song_id: str) -> Song:
    """Clear deleted_at on a song. Raises if past the restore window or album is deleted."""
    song = (
        session.query(Song)
        .execution_options(include_deleted=True)
        .filter_by(id=song_id)
        .first()
    )
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    if song.deleted_at is None:
        return song
    deleted_at = song.deleted_at
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - deleted_at
    window = timedelta(days=get_settings().soft_delete_retention_days)
    if age > window:
        raise RestoreWindowExpiredError(
            f"Song {song_id} was deleted {age.days} days ago, "
            f"past the {window.days}-day restore window",
        )
    album = (
        session.query(Album)
        .execution_options(include_deleted=True)
        .filter_by(id=song.album_id)
        .first()
    )
    if album is None or album.deleted_at is not None:
        raise ValueError(f"Cannot restore song {song_id}: parent album is deleted")
    song.deleted_at = None
    session.flush()
    log.info("Restored song %s", song_id)
    return song


def rename_song(session: Session, song_id: str, title: str) -> Song:
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    song.title = title
    session.flush()
    log.info("Renamed song %s to %r", song_id, title)
    return song


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


def list_expired_songs(
    session: Session, cutoff: datetime, exclude_album_ids: list[str],
) -> list[Song]:
    """Return soft-deleted orphan songs (album not also expired) past cutoff."""
    query = (
        session.query(Song)
        .execution_options(include_deleted=True)
        .filter(Song.deleted_at.isnot(None), Song.deleted_at < cutoff)
    )
    if exclude_album_ids:
        query = query.filter(Song.album_id.notin_(exclude_album_ids))
    return query.all()


def get_song_by_slug(session: Session, slug: str) -> Song | None:
    return (
        session.query(Song)
        .options(
            joinedload(Song.generations).joinedload(Generation.version),
            joinedload(Song.album),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_song_sharing(session: Session, song_id: str) -> Song:
    song = enable_sharing(session, Song, song_id)
    picked = next((g for g in song.generations if g.is_picked), None)
    if picked:
        picked.is_kept = True
        session.flush()
    return song


def disable_song_sharing(session: Session, song_id: str) -> Song:
    return disable_sharing(session, Song, song_id)


def cleanup_song(session: Session, song_id: str) -> tuple[int, list[str]]:
    """Remove unpicked+unkept generations from a song. Returns (count, paths)."""
    gens = (
        session.query(Generation)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter(
            Generation.song_id == song_id,
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
