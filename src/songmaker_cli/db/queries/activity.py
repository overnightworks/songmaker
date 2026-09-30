"""Where a musician last worked: one activity time per album and playlist.

Each person's own work on a song (an edit they saved, a listen they started)
is recorded here too, whoever owns the song.

A place is an album or a playlist. Its activity is the newest thing done
there, and it names the song that was. The musician's own places count
anyone's work on them; an album of someone else's (only an admin opens one)
counts the musician's own work alone. Every nullable term is
folded with ``coalesce`` and ``case`` rather than ``greatest``: SQLite has no
``greatest``, and its multi-argument ``max()`` returns NULL on any NULL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final

from sqlalchemy import ColumnElement, Select, Subquery, and_, case, exists, func, select, union_all
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, aliased, selectinload

from songmaker_cli.constants import LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_PLAYLIST
from songmaker_cli.db.models import (
    Album,
    ChatMessage,
    Conversation,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
    UserSongWork,
    aware_timestamp,
)
from songmaker_cli.db.queries.playlists import playlist_holds_song_clause
from songmaker_cli.timestamps import utcnow

CONTINUE_MAX_PLACES: Final[int] = 6

class SongWork(StrEnum):
    """What a person did on a song; each value names its time column."""

    EDITED = "edited_at"
    PLAYED = "played_at"


_UPSERT_INSERT_BY_DIALECT: Final[dict[str, Callable]] = {
    "postgresql": postgresql.insert,
    "sqlite": sqlite.insert,
}


def record_song_work(session: Session, *, user_id: str, song_id: str, work: SongWork) -> None:
    """Stamp the person's own latest ``work`` on the song, keeping their other kind."""
    insert = _UPSERT_INSERT_BY_DIALECT[session.bind.dialect.name]
    stamp = {work.value: utcnow()}
    session.execute(
        insert(UserSongWork)
        .values(user_id=user_id, song_id=song_id, **stamp)
        .on_conflict_do_update(index_elements=["user_id", "song_id"], set_=stamp),
    )


@dataclass(frozen=True)
class PlaceActivity:
    """An album or playlist, when it was last worked in, and the song that was."""

    place: Album | Playlist
    activity_at: datetime
    song: Song | None

    @property
    def place_type(self) -> str:
        return LIBRARY_ITEM_ALBUM if isinstance(self.place, Album) else LIBRARY_ITEM_PLAYLIST


def list_place_activity(
    session: Session, *, viewer_id: str, owner_id: str | None, limit: int | None,
) -> list[PlaceActivity]:
    """Return the viewer's places, most recently worked in first.

    ``owner_id`` is whose albums the viewer may open, ``None`` for every
    album, as ``owner_filter`` decides. The viewer's own albums and playlists
    are always places; someone else's album is one only while the viewer may
    open it and has worked in it. ``limit=None`` returns every place. Ties
    fall back to album before playlist, then id. Reading the leading
    ``limit`` places of each kind is enough before merging: a place behind
    that cutoff already has ``limit`` places of its own kind ahead of it.
    """
    places = [
        *_owned_album_activity(session, user_id=viewer_id, limit=limit),
        *_playlist_activity(session, user_id=viewer_id, limit=limit),
    ]
    viewer_opens_every_album = owner_id is None
    if viewer_opens_every_album:
        places += _foreign_album_activity(session, viewer_id=viewer_id, limit=limit)
    places.sort(key=_newest_first)
    return places if limit is None else places[:limit]


def _owned_album_activity(
    session: Session, *, user_id: str, limit: int | None,
) -> list[PlaceActivity]:
    newest_song = _newest_song_per_owned_album(user_id)
    activity_at = func.coalesce(newest_song.c.activity_at, Album.created_at)
    query = (
        session.query(Album, activity_at, Song)
        .outerjoin(
            newest_song,
            and_(newest_song.c.album_id == Album.id, newest_song.c.rank == 1),
        )
        .outerjoin(Song, Song.id == newest_song.c.song_id)
        .filter(
            Album.created_by == user_id,
            Album.is_archived.is_(False),
            Album.deleted_at.is_(None),
        )
        .order_by(activity_at.desc(), Album.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return [_place(album, at, song) for album, at, song in query.all()]


def _foreign_album_activity(
    session: Session, *, viewer_id: str, limit: int | None,
) -> list[PlaceActivity]:
    """Other people's albums the viewer worked in, dated by that work alone."""
    newest_song = _newest_song_per_foreign_album(viewer_id)
    query = (
        session.query(Album, newest_song.c.activity_at, Song)
        .join(
            newest_song,
            and_(newest_song.c.album_id == Album.id, newest_song.c.rank == 1),
        )
        .join(Song, Song.id == newest_song.c.song_id)
        .filter(Album.is_archived.is_(False), Album.deleted_at.is_(None))
        .order_by(newest_song.c.activity_at.desc(), Album.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return [_place(album, at, song) for album, at, song in query.all()]


def _playlist_activity(
    session: Session, *, user_id: str, limit: int | None,
) -> list[PlaceActivity]:
    newest_entry = _newest_live_entry_per_playlist()
    song_id = case(
        (_holds_its_last_played_song(), Playlist.last_played_song_id),
        else_=newest_entry.c.song_id,
    )
    activity_at = _latest_of(
        Playlist.updated_at,
        Playlist.last_played_at,
        newest_entry.c.added_at,
        Playlist.created_at,
    )
    query = (
        session.query(Playlist, activity_at, Song)
        .options(
            selectinload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
        )
        .outerjoin(
            newest_entry,
            and_(newest_entry.c.playlist_id == Playlist.id, newest_entry.c.rank == 1),
        )
        .outerjoin(Song, Song.id == song_id)
        .filter(Playlist.created_by == user_id)
        .order_by(activity_at.desc(), Playlist.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return [_place(playlist, at, song) for playlist, at, song in query.all()]


def _newest_song_per_owned_album(user_id: str) -> Subquery:
    """Each live song of the user's albums with anyone's activity, ranked newest first."""
    newest_take = (
        select(Generation.song_id, func.max(Generation.created_at).label("at"))
        .group_by(Generation.song_id)
        .subquery()
    )
    newest_own_message = _newest_own_message_per_song(user_id).subquery()
    song_activity = (
        select(
            Song.id.label("song_id"),
            Song.album_id.label("album_id"),
            _latest_of(
                Song.updated_at,
                Song.last_played_at,
                newest_take.c.at,
                newest_own_message.c.at,
            ).label("activity_at"),
        )
        .join(Album, Song.album_id == Album.id)
        .outerjoin(newest_take, newest_take.c.song_id == Song.id)
        .outerjoin(newest_own_message, newest_own_message.c.song_id == Song.id)
        .where(Album.created_by == user_id, Song.deleted_at.is_(None))
        .subquery()
    )
    return _ranked_newest_first_per_album(song_activity)


def _newest_song_per_foreign_album(viewer_id: str) -> Subquery:
    """Each live song of someone else's album with the viewer's own newest work on it.

    Every source is filtered by the viewer's indexed ``user_id`` before any
    song or album is joined.
    """
    own_work = union_all(
        select(UserSongWork.song_id, UserSongWork.edited_at.label("at"))
        .where(UserSongWork.user_id == viewer_id),
        select(UserSongWork.song_id, UserSongWork.played_at.label("at"))
        .where(UserSongWork.user_id == viewer_id),
        _newest_own_take_per_song(viewer_id),
        _newest_own_message_per_song(viewer_id),
    ).subquery()
    newest_own_work = (
        select(own_work.c.song_id, func.max(own_work.c.at).label("at"))
        .where(own_work.c.at.is_not(None))
        .group_by(own_work.c.song_id)
        .subquery()
    )
    song_activity = (
        select(
            Song.id.label("song_id"),
            Song.album_id.label("album_id"),
            newest_own_work.c.at.label("activity_at"),
        )
        .select_from(newest_own_work)
        .join(Song, Song.id == newest_own_work.c.song_id)
        .join(Album, Song.album_id == Album.id)
        .where(Album.created_by.is_distinct_from(viewer_id), Song.deleted_at.is_(None))
        .subquery()
    )
    return _ranked_newest_first_per_album(song_activity)


def _newest_own_take_per_song(user_id: str) -> Select:
    """The newest take the user made on each song.

    A take made before its maker was recorded names no one and counts for
    no one here.
    """
    return (
        select(Generation.song_id, func.max(Generation.created_at).label("at"))
        .where(Generation.created_by == user_id)
        .group_by(Generation.song_id)
    )


def _newest_own_message_per_song(user_id: str) -> Select:
    """The newest message on each song in the user's own co-writer conversations."""
    return (
        select(ChatMessage.song_id, func.max(ChatMessage.created_at).label("at"))
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id, ChatMessage.song_id.is_not(None))
        .group_by(ChatMessage.song_id)
    )


def _ranked_newest_first_per_album(song_activity: Subquery) -> Subquery:
    return select(
        song_activity,
        func.row_number().over(
            partition_by=song_activity.c.album_id,
            order_by=(song_activity.c.activity_at.desc(), song_activity.c.song_id.asc()),
        ).label("rank"),
    ).subquery()


def _newest_live_entry_per_playlist() -> Subquery:
    """Entries whose song is live, ranked newest-added first per playlist.

    The join to ``Song`` is explicit: the global soft-delete filter does not
    reach an entry subquery that never names the song.
    """
    return (
        select(
            PlaylistEntry.playlist_id,
            PlaylistEntry.added_at,
            Generation.song_id,
            func.row_number().over(
                partition_by=PlaylistEntry.playlist_id,
                order_by=(PlaylistEntry.added_at.desc(), PlaylistEntry.position.desc()),
            ).label("rank"),
        )
        .join(Generation, PlaylistEntry.generation_id == Generation.id)
        .join(Song, Generation.song_id == Song.id)
        .where(Song.deleted_at.is_(None))
        .subquery()
    )


def _holds_its_last_played_song() -> ColumnElement[bool]:
    """Whether the playlist still holds a take of the live song it was last played from.

    The song is aliased so the correlated check never binds to the ``Song``
    the outer query joins for the song line.
    """
    last_played = aliased(Song)
    last_played_is_live = exists().where(
        last_played.id == Playlist.last_played_song_id,
        last_played.deleted_at.is_(None),
    )
    return and_(
        playlist_holds_song_clause(Playlist.id, Playlist.last_played_song_id),
        last_played_is_live,
    )


def _latest_of(
    anchor: ColumnElement[datetime], *terms: ColumnElement[datetime],
) -> ColumnElement[datetime]:
    """The latest of a never-NULL anchor and any number of nullable terms."""
    latest = anchor
    for term in terms:
        candidate = func.coalesce(term, anchor)
        latest = case((candidate > latest, candidate), else_=latest)
    return latest


def _place(place: Album | Playlist, activity_at: datetime, song: Song | None) -> PlaceActivity:
    return PlaceActivity(
        place=place,
        activity_at=aware_timestamp(activity_at).astimezone(timezone.utc),
        song=song,
    )


def _newest_first(activity: PlaceActivity) -> tuple[float, str, str]:
    return (-activity.activity_at.timestamp(), activity.place_type, activity.place.id)
