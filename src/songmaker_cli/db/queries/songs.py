"""Query functions for songs — CRUD, move, archive, sharing."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload, selectinload

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
CONTINUE_MAX_ITEMS: Final[int] = 6


@dataclass(frozen=True)
class ContinueCandidate:
    """An owned song or album together with its Continue-row activity time."""

    item: Album | Song
    activity_at: datetime


def list_continue_candidates(
    session: Session,
    *,
    user_id: str,
    limit: int = CONTINUE_MAX_ITEMS,
) -> list[ContinueCandidate]:
    """Return the user's newest song and album candidates for Continue.

    A song's activity is its newer edit or listen. Albums do not persist an
    activity column, so theirs is the newest activity among their live songs,
    falling back to ``created_at`` for an empty album. Fetching the leading
    ``limit`` entries of each kind is sufficient before merging: an entry
    behind that cutoff already has at least ``limit`` entries of its own kind
    ahead of it.
    """
    song_activity = case(
        (Song.last_played_at > Song.updated_at, Song.last_played_at),
        else_=Song.updated_at,
    )
    songs = (
        session.query(Song)
        .options(joinedload(Song.album))
        .join(Album)
        .filter(
            Album.created_by == user_id,
            Album.is_archived.is_(False),
        )
        .order_by(song_activity.desc(), Song.id.asc())
        .limit(limit)
        .all()
    )
    song_candidates = [
        ContinueCandidate(
            item=song,
            activity_at=max(song.updated_at, song.last_played_at or song.updated_at),
        )
        for song in songs
    ]

    album_activity = func.coalesce(func.max(song_activity), Album.created_at)
    album_rows = (
        session.query(Album, album_activity.label("activity_at"))
        .outerjoin(Song)
        .filter(
            Album.created_by == user_id,
            Album.is_archived.is_(False),
        )
        .group_by(Album.id)
        .order_by(album_activity.desc(), Album.id.asc())
        .limit(limit)
        .all()
    )
    album_candidates = [
        ContinueCandidate(item=album, activity_at=activity_at)
        for album, activity_at in album_rows
    ]

    return sorted(
        [*song_candidates, *album_candidates],
        key=_continue_sort_key,
    )[:limit]


def record_song_listen(session: Session, song: Song) -> Song:
    """Persist the server time at which an owner started listening to a song."""
    song.last_played_at = datetime.now(timezone.utc)
    session.flush()
    return song


def _continue_sort_key(candidate: ContinueCandidate) -> tuple[float, str, str]:
    activity_at = candidate.activity_at
    if activity_at.tzinfo is None:
        activity_at = activity_at.replace(tzinfo=timezone.utc)
    item_type = "album" if isinstance(candidate.item, Album) else "song"
    return (-activity_at.timestamp(), item_type, candidate.item.id)


def list_songs(
    session: Session,
    album_id: str | None = None,
    user_id: str | None = None,
    light: bool = True,
    with_generations: bool = False,
    offset: int = 0,
    limit: int | None = None,
    q: str | None = None,
    sort: str | None = None,
    exclude_archived_albums: bool = False,
) -> list[Song]:
    if light:
        light_options = [
            joinedload(Song.versions),
            joinedload(Song.album),
        ]
        if with_generations:
            # A separate bulk query for all matched songs' generations, not
            # a per-song joinedload — the caller needs the full relationship
            # (e.g. the library queue pool), not just a count, so
            # selectinload() rather than the count_generations_by_song()
            # aggregate used by the summary response path.
            #
            # generation.version and generation.song (+ .song.album) must be
            # joinedload()ed here rather than left to the back_populates
            # backref: once the returned Song list itself goes out of scope
            # downstream, its entries are only weakly referenced by the
            # session, and a bare Generation.song/.version access after that
            # falls back to one lazy query per generation -- silently
            # reintroducing the N+1 this option exists to remove.
            light_options.append(
                selectinload(Song.generations).options(
                    joinedload(Generation.version),
                    joinedload(Generation.song).joinedload(Song.album),
                ),
            )
        query = session.query(Song).options(*light_options)
    else:
        query = session.query(Song).options(
            selectinload(Song.versions),
            selectinload(Song.generations).selectinload(Generation.scores),
            selectinload(Song.generations).joinedload(Generation.rating),
            selectinload(Song.generations).joinedload(Generation.src_generation),
            selectinload(Song.generations).joinedload(Generation.version),
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


def count_generations_by_song(
    session: Session, song_ids: Sequence[str],
) -> dict[str, int]:
    """Count generations per song, grouped.

    One aggregate query rather than touching each song's (unloaded)
    ``generations`` relationship — keeps the song list response free of an
    N+1 lazy-load per row. Mirrors count_picked_songs_by_album().
    """
    if not song_ids:
        return {}
    rows = (
        session.query(Generation.song_id, func.count(Generation.id))
        .filter(Generation.song_id.in_(song_ids))
        .group_by(Generation.song_id)
        .all()
    )
    return dict(rows)


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
    # versions, generations, and generations.scores are all sibling/nested
    # collections off one Song -- joinedload()ing more than one of them
    # produces a SQL cross join (versions x generations x scores), returning
    # one row per combination with the lyrics text and score JSON (whisper
    # transcript included) repeated on every row (#331 Finding 1: a
    # 12-version/25-generation/7-score song returned 2,100 rows for one
    # fetch). selectinload() issues one flat batched query per collection
    # instead. rating/src_generation/version stay joinedload()ed off the
    # generations selectinload -- they're scalar (one row per generation),
    # so chaining them there adds columns, not cross-joined rows. This
    # function always returns a single Song kept alive by the caller's own
    # reference for as long as it's used, so the weak-identity-map pitfall
    # in list_songs() (#340) -- where a *list* of parents going out of scope
    # silently turns a back-populate access into a lazy query per row --
    # does not apply here. SongResponse.from_orm does read gen.version, but
    # that's the forward relation (Generation -> Version), populated
    # directly in the same generations-selectin row via the joinedload
    # above -- not an identity-map lookup, so it's unaffected by parent
    # lifetime either way. Nothing on this path reads the Generation.song
    # back-populate, which is the direction #340's pitfall actually depends
    # on (see tests/test_song_api.py for the query-count proof).
    query = session.query(Song).options(
        selectinload(Song.versions),
        selectinload(Song.generations).selectinload(Generation.scores),
        selectinload(Song.generations).joinedload(Generation.rating),
        selectinload(Song.generations)
        .joinedload(Generation.src_generation)
        .joinedload(Generation.version),
        selectinload(Song.generations).joinedload(Generation.version),
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
    slug: str,
    lyrics: str = "",
    prompt: str = "",
    bpm: int = 0,
    audio_duration: int = 180,
    key_scale: str = "",
    vocal_language: str = "",
    generation_params: dict | None = None,
) -> Song:
    """Create a song and its first version.

    ``slug`` must already be reserved (e.g. via unique_song_slug()) and is
    set on the row before its first flush, not after — the row's default
    slug='' would otherwise briefly exist under album_id's unique index and
    collide with a sibling that also has not been assigned a real slug yet.
    """
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
        track_number=track_number, slug=slug,
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

    song.updated_at = datetime.now(timezone.utc)

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


def rename_song(session: Session, song_id: str, title: str, slug: str) -> Song:
    """Rename a song, moving its slug along in the same flush.

    ``slug`` (already reserved via unique_song_slug()) changes together
    with the title so both change atomically in one flush — setting it in
    a later, separate flush would briefly leave the row on its old slug,
    next to whatever sibling has just claimed it.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    song.title = title
    song.slug = slug
    session.flush()
    log.info("Renamed song %s to %r", song_id, title)
    return song


def move_song(session: Session, song_id: str, new_album_id: str, slug: str) -> Song:
    """Move a song to another album, re-slugging in the same flush.

    ``slug`` (already reserved via unique_song_slug() against the target
    album) moves together with the album_id change in one flush — the
    song's old slug may already be taken by a sibling in the target album,
    and a separate later flush would briefly collide with it.
    """
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
    song.slug = slug
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
