"""Query functions for playlists — CRUD, entries, sharing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable, Final

from sqlalchemy import ColumnElement, Exists, exists, select
from sqlalchemy.orm import Session, aliased, joinedload

from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
)
from songmaker_cli.db.queries.generations import lock_takes, lock_unarchived_generation
from songmaker_cli.db.queries.sharing import (
    disable_sharing,
    enable_sharing,
    is_playable_take,
    presented_take,
)

INITIAL_PLAYLIST_POSITION: Final[int] = 0
PLAYLIST_SKIP_NO_PLAYABLE: Final = "no_playable_take"
PLAYLIST_SKIP_MISSING_AUDIO: Final = "missing_audio"


@dataclass(frozen=True)
class PlaylistAddSkip:
    song_id: str
    title: str
    reason: str


@dataclass(frozen=True)
class PlaylistAddResult:
    entries: list[PlaylistEntry]
    skipped: list[PlaylistAddSkip]


@dataclass(frozen=True)
class _Candidate:
    """One song's take on its way to a playlist: the take to add, or why there is none."""

    song_id: str
    title: str
    take: Generation | None
    skip_reason: str | None


def list_playlists(session: Session, user_id: str) -> list[Playlist]:
    return (
        session.query(Playlist)
        .options(
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
        )
        .filter_by(created_by=user_id)
        .order_by(Playlist.title)
        .all()
    )


def get_playlist(session: Session, playlist_id: str) -> Playlist | None:
    return (
        session.query(Playlist)
        .options(
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.version),
        )
        .filter_by(id=playlist_id)
        .first()
    )


def playlist_holds_song_clause(
    playlist_id: ColumnElement[str] | str, song_id: ColumnElement[str] | str,
) -> Exists:
    """Whether the playlist holds any take of the song, as a SQL condition.

    Aliased so a caller correlating on its own entries or takes never binds
    the check to the rows its outer query already names.
    """
    entry = aliased(PlaylistEntry)
    take = aliased(Generation)
    return exists().where(
        entry.playlist_id == playlist_id,
        entry.generation_id == take.id,
        take.song_id == song_id,
    )


def playlist_holds_song(session: Session, playlist: Playlist, song: Song) -> bool:
    """Whether the playlist holds any take of the song."""
    return bool(session.scalar(select(playlist_holds_song_clause(playlist.id, song.id))))


def playlist_slug_taken(
    session: Session, slug: str, exclude_playlist_id: str | None = None,
) -> bool:
    """Whether a playlist holds this slug; the slug is global.

    Pass exclude_playlist_id when the playlist already owns a row, so a
    rename does not collide with itself.
    """
    query = session.query(Playlist).filter(Playlist.slug == slug)
    if exclude_playlist_id is not None:
        query = query.filter(Playlist.id != exclude_playlist_id)
    return query.first() is not None


def create_playlist(session: Session, title: str, user_id: str, slug: str) -> Playlist:
    """Create a playlist.

    ``slug`` must already be reserved (e.g. via unique_playlist_slug()) and
    is set on the row before its one flush, not after — the row's default
    slug='' would otherwise briefly exist under the global unique index and
    collide with a sibling that also has not been assigned a real slug yet.
    """
    playlist = Playlist(title=title, created_by=user_id, slug=slug)
    session.add(playlist)
    session.flush()
    return playlist


def delete_playlist(session: Session, playlist_id: str) -> None:
    playlist = session.query(Playlist).filter_by(id=playlist_id).first()
    if not playlist:
        raise ValueError(f"Playlist not found: {playlist_id}")
    session.delete(playlist)
    session.flush()


def update_playlist(session: Session, playlist_id: str, title: str, slug: str) -> Playlist:
    """Rename a playlist, moving its slug along in the same flush.

    ``slug`` (already reserved via unique_playlist_slug()) changes together
    with ``title`` in one write — a later, separate flush would briefly leave
    the row on its old slug, and a concurrent create could then reserve that
    slug out from under it (the #270 lesson, global rather than per-album).
    """
    playlist = session.query(Playlist).filter_by(id=playlist_id).first()
    if not playlist:
        raise ValueError(f"Playlist not found: {playlist_id}")
    playlist.title = title
    playlist.slug = slug
    session.flush()
    return playlist


def set_playlist_cover_key(
    session: Session, playlist_id: str, cover_key: str | None,
) -> Playlist:
    playlist = get_playlist(session, playlist_id)
    if not playlist:
        raise ValueError(f"Playlist not found: {playlist_id}")
    playlist.cover_key = cover_key
    session.flush()
    return playlist


def _lock_playlist_order(session: Session, playlist_id: str) -> None:
    """Hold the playlist's row until the transaction ends, so one writer at a time reads and
    shifts its positions.

    Taken before any take lock, so a writer that also locks takes never waits on a take while
    holding a take another writer needs.
    """
    session.execute(select(Playlist.id).where(Playlist.id == playlist_id).with_for_update())


def _next_position(session: Session, playlist_id: str) -> int:
    max_pos = (
        session.query(PlaylistEntry.position)
        .filter_by(playlist_id=playlist_id)
        .order_by(PlaylistEntry.position.desc())
        .first()
    )
    return (max_pos[0] + 1) if max_pos else INITIAL_PLAYLIST_POSITION


def _append_entry(session: Session, playlist_id: str, gen: Generation) -> PlaylistEntry:
    entry = PlaylistEntry(
        playlist_id=playlist_id, generation_id=gen.id,
        position=_next_position(session, playlist_id),
    )
    session.add(entry)
    gen.is_kept = True
    session.flush()
    return entry


def add_generation_to_playlist(
    session: Session, playlist_id: str, generation_id: str,
) -> PlaylistEntry:
    _lock_playlist_order(session, playlist_id)
    return _append_entry(session, playlist_id, lock_unarchived_generation(session, generation_id))


def add_song_to_playlist(
    session: Session, playlist_id: str, song_id: str,
) -> PlaylistEntry | None:
    song = (
        session.query(Song)
        .options(joinedload(Song.generations))
        .filter_by(id=song_id)
        .first()
    )
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    playable = presented_take(song.generations)
    if playable is None:
        return None
    return add_generation_to_playlist(session, playlist_id, playable.id)


def add_album_to_playlist(
    session: Session,
    playlist_id: str,
    album_id: str,
    is_readable: Callable[[Generation], bool],
) -> PlaylistAddResult:
    album = (
        session.query(Album)
        .options(
            joinedload(Album.songs)
            .joinedload(Song.generations),
        )
        .filter_by(id=album_id)
        .first()
    )
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    songs = sorted(album.songs, key=lambda item: (item.track_number, item.id))
    return _append_candidates(session, playlist_id, [
        _candidate(song, presented_take(song.generations), is_readable) for song in songs
    ])


def add_playlist_entries_to_playlist(
    session: Session,
    playlist_id: str,
    source_entries: Sequence[PlaylistEntry],
    is_readable: Callable[[Generation], bool],
) -> PlaylistAddResult:
    """Append the playable takes of the source entries, in their order, to the playlist.

    The caller passes the entries its source view shows; an entry the view hides is neither
    added nor reported.
    """
    return _append_candidates(session, playlist_id, [
        _entry_candidate(entry, is_readable) for entry in source_entries
    ])


def _entry_candidate(
    entry: PlaylistEntry, is_readable: Callable[[Generation], bool],
) -> _Candidate:
    take = entry.generation
    return _candidate(take.song, take if is_playable_take(take) else None, is_readable)


def _candidate(
    song: Song, take: Generation | None, is_readable: Callable[[Generation], bool],
) -> _Candidate:
    if take is None:
        return _Candidate(song.id, song.title, None, PLAYLIST_SKIP_NO_PLAYABLE)
    if not is_readable(take):
        return _Candidate(song.id, song.title, None, PLAYLIST_SKIP_MISSING_AUDIO)
    return _Candidate(song.id, song.title, take, None)


def _append_candidates(
    session: Session, playlist_id: str, candidates: Sequence[_Candidate],
) -> PlaylistAddResult:
    """Lock the playlist, then the candidates' takes in id order, then append each one still
    playable, in order.

    A take archived or deleted before its lock is granted is skipped like one that was
    never playable.
    """
    _lock_playlist_order(session, playlist_id)
    locked = {
        gen.id: gen
        for gen in lock_takes(
            session,
            Generation.id.in_([item.take.id for item in candidates if item.take is not None]),
        )
    }
    entries: list[PlaylistEntry] = []
    skipped: list[PlaylistAddSkip] = []
    for item in candidates:
        gen = locked.get(item.take.id) if item.take is not None else None
        if gen is None or gen.is_archived:
            skipped.append(PlaylistAddSkip(
                song_id=item.song_id, title=item.title,
                reason=item.skip_reason or PLAYLIST_SKIP_NO_PLAYABLE,
            ))
            continue
        entries.append(_append_entry(session, playlist_id, gen))
    return PlaylistAddResult(entries=entries, skipped=skipped)


def _locked_entry(session: Session, playlist_id: str, entry_id: str) -> PlaylistEntry:
    """Reads the entry after the lock wait, never a position another writer has since shifted."""
    entry = session.scalars(
        select(PlaylistEntry)
        .where(PlaylistEntry.id == entry_id, PlaylistEntry.playlist_id == playlist_id)
        .execution_options(populate_existing=True)
    ).one_or_none()
    if entry is None:
        raise ValueError(f"Playlist entry not found: {entry_id}")
    return entry


def remove_from_playlist(
    session: Session, playlist_id: str, entry_id: str,
) -> None:
    _lock_playlist_order(session, playlist_id)
    entry = _locked_entry(session, playlist_id, entry_id)
    removed_pos = entry.position
    session.delete(entry)
    session.query(PlaylistEntry).filter(
        PlaylistEntry.playlist_id == playlist_id,
        PlaylistEntry.position > removed_pos,
    ).update({"position": PlaylistEntry.position - 1})
    session.flush()


def reorder_playlist_entry(
    session: Session, playlist_id: str, entry_id: str, new_position: int,
) -> None:
    """Move an entry to ``new_position``; a position past the last entry means the last place."""
    _lock_playlist_order(session, playlist_id)
    entry = _locked_entry(session, playlist_id, entry_id)

    old_pos = entry.position
    new_position = min(new_position, _next_position(session, playlist_id) - 1)
    if old_pos == new_position:
        return

    if new_position < old_pos:
        session.query(PlaylistEntry).filter(
            PlaylistEntry.playlist_id == playlist_id,
            PlaylistEntry.position >= new_position,
            PlaylistEntry.position < old_pos,
        ).update({"position": PlaylistEntry.position + 1})
    else:
        session.query(PlaylistEntry).filter(
            PlaylistEntry.playlist_id == playlist_id,
            PlaylistEntry.position > old_pos,
            PlaylistEntry.position <= new_position,
        ).update({"position": PlaylistEntry.position - 1})

    entry.position = new_position
    session.flush()


def get_playlist_by_slug(session: Session, slug: str) -> Playlist | None:
    return (
        session.query(Playlist)
        .options(
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.version),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_playlist_sharing(session: Session, playlist_id: str) -> Playlist:
    return enable_sharing(session, Playlist, playlist_id)


def disable_playlist_sharing(session: Session, playlist_id: str) -> Playlist:
    return disable_sharing(session, Playlist, playlist_id)
