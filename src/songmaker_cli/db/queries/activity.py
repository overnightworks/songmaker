"""A person's own work on a song, and Home's Listen and Write that read it back.

Each person's own work on a song (an edit they saved and its kind, a listen
they started and whether it was outside a playlist) is recorded here, whoever
owns the song.

Listen and Write read the viewer's own actions alone, so nobody else's work
or listening ever moves them, and only what the viewer may open: live songs
on live, unarchived albums, as ``owner_filter`` decides whose.

- Listen holds albums and playlists. An album is dated by the viewer's newest
  listen outside a playlist on one of its songs; listens recorded before that
  fact existed cannot tell an album listen from a playlist listen and count
  for nothing. A playlist is dated by the viewer's newest listen from it, and
  numbers and resumes only its live entries: a take not archived, of a live
  song on a live, unarchived album the viewer may open.
- Write holds songs, each dated and named by the viewer's newest work on it:
  a saved edit of its recorded kind, a take that is not archived, or a
  message of their own to the co-writer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Final

from sqlalchemy import (
    ScalarSelect,
    Select,
    Subquery,
    and_,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, aliased, contains_eager, selectinload

from songmaker_cli.constants import LIBRARY_ITEM_ALBUM, LIBRARY_ITEM_PLAYLIST, SongWorkKind
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
from songmaker_cli.db.queries.library import visible_albums
from songmaker_cli.timestamps import utcnow

MUSICIAN_CHAT_ROLE: Final[str] = "user"


class SongWork(StrEnum):
    """What a person did on a song; each value names its time column."""

    EDITED = "edited_at"
    PLAYED = "played_at"
    ALBUM_PLAYED = "album_played_at"


_UPSERT_INSERT_BY_DIALECT: Final[dict[str, Callable]] = {
    "postgresql": postgresql.insert,
    "sqlite": sqlite.insert,
}


def record_song_edit(
    session: Session, *, user_id: str, song_id: str, kind: SongWorkKind,
) -> None:
    """Stamp the person's own latest edit on the song and what kind of edit it was."""
    _stamp_song_work(
        session, user_id=user_id, song_id=song_id, works=(SongWork.EDITED,), edit_kind=kind,
    )


def record_song_played(
    session: Session, *, user_id: str, song_id: str, in_playlist: bool,
) -> None:
    """Stamp the person's own latest listen on the song.

    A listen outside a playlist is an album listen too; a library-wide
    shuffle names no playlist, so it is one.
    """
    works = (SongWork.PLAYED,) if in_playlist else (SongWork.PLAYED, SongWork.ALBUM_PLAYED)
    _stamp_song_work(session, user_id=user_id, song_id=song_id, works=works)


def _stamp_song_work(
    session: Session,
    *,
    user_id: str,
    song_id: str,
    works: tuple[SongWork, ...],
    **details: str,
) -> None:
    """Stamp ``works`` at one moment with ``details``, keeping the row's other columns."""
    insert = _UPSERT_INSERT_BY_DIALECT[session.bind.dialect.name]
    now = utcnow()
    stamp = {work.value: now for work in works} | details
    session.execute(
        insert(UserSongWork)
        .values(user_id=user_id, song_id=song_id, **stamp)
        .on_conflict_do_update(index_elements=["user_id", "song_id"], set_=stamp),
    )


@dataclass(frozen=True)
class PlaceListen:
    """An album or playlist, when the viewer last listened in it, and to which song.

    ``song_number`` is that song's 1-based place among the album's live songs
    or the playlist's live entries. A playlist none of whose live entries
    holds its last-played song names none, and resumes from its start.
    """

    place: Album | Playlist
    played_at: datetime
    song: Song | None
    song_number: int | None
    entry_id: str | None = None

    @property
    def place_type(self) -> str:
        return LIBRARY_ITEM_ALBUM if isinstance(self.place, Album) else LIBRARY_ITEM_PLAYLIST


@dataclass(frozen=True)
class WorkedSong:
    """A song, the viewer's newest kind of work on it, and when that was."""

    song: Song
    work: SongWorkKind
    worked_at: datetime


def list_place_listens(
    session: Session, *, viewer_id: str, owner_id: str | None, limit: int,
) -> list[PlaceListen]:
    """Return the places the viewer listened in, most recent listen first.

    ``owner_id`` is whose albums the viewer may open, ``None`` for every
    album, as ``owner_filter`` decides; playlists are always the viewer's
    own, and name only songs on albums the viewer may open. Ties fall back
    to album before playlist, then id. Reading the leading ``limit`` places
    of each kind is enough before merging: a place behind that cutoff
    already has ``limit`` places of its own kind ahead of it.
    """
    listens = [
        *_album_listens(session, viewer_id=viewer_id, owner_id=owner_id, limit=limit),
        *_playlist_listens(session, viewer_id=viewer_id, owner_id=owner_id, limit=limit),
    ]
    listens.sort(key=_most_recent_listen_first)
    return listens[:limit]


def list_worked_songs(
    session: Session, *, viewer_id: str, owner_id: str | None, limit: int,
) -> list[WorkedSong]:
    """Return the songs the viewer worked on last, most recent work first, ties by song id.

    ``owner_id`` is whose albums the viewer may open, as for
    ``list_place_listens``.
    """
    newest_work = _newest_own_work_per_song(viewer_id)
    query = visible_albums(
        session.query(Song, newest_work.c.at, newest_work.c.work)
        .join(newest_work, and_(newest_work.c.song_id == Song.id, newest_work.c.rank == 1))
        .join(Song.album)
        .options(contains_eager(Song.album)),
        owner_id,
    )
    rows = query.order_by(newest_work.c.at.desc(), Song.id.asc()).limit(limit).all()
    return [
        WorkedSong(song=song, work=SongWorkKind(work), worked_at=_in_utc(worked_at))
        for song, worked_at, work in rows
    ]


def _album_listens(
    session: Session, *, viewer_id: str, owner_id: str | None, limit: int,
) -> list[PlaceListen]:
    newest_listen = _newest_album_listen_per_album(viewer_id)
    query = visible_albums(
        session.query(Album, newest_listen.c.played_at, Song, _song_number_in_album())
        .join(newest_listen, and_(newest_listen.c.album_id == Album.id, newest_listen.c.rank == 1))
        .join(Song, Song.id == newest_listen.c.song_id),
        owner_id,
    )
    rows = query.order_by(newest_listen.c.played_at.desc(), Album.id.asc()).limit(limit).all()
    return [
        _listen(album, played_at, song, song_number)
        for album, played_at, song, song_number in rows
    ]


def _playlist_listens(
    session: Session, *, viewer_id: str, owner_id: str | None, limit: int,
) -> list[PlaceListen]:
    live_song_place = _first_live_place_per_song(viewer_id, owner_id)
    query = (
        session.query(Playlist, Song, live_song_place.c.song_number, live_song_place.c.entry_id)
        .options(
            selectinload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
        )
        .outerjoin(
            live_song_place,
            and_(
                live_song_place.c.playlist_id == Playlist.id,
                live_song_place.c.song_id == Playlist.last_played_song_id,
            ),
        )
        .outerjoin(Song, Song.id == live_song_place.c.song_id)
        .filter(Playlist.created_by == viewer_id, Playlist.last_played_at.is_not(None))
        .order_by(Playlist.last_played_at.desc(), Playlist.id.asc())
        .limit(limit)
    )
    return [
        _listen(playlist, playlist.last_played_at, song, song_number, entry_id)
        for playlist, song, song_number, entry_id in query.all()
    ]


def _newest_album_listen_per_album(viewer_id: str) -> Subquery:
    """The viewer's listens outside a playlist on each album's songs, newest first.

    The viewer's indexed ``user_id`` filters the listens before any song is
    joined.
    """
    return (
        select(
            UserSongWork.song_id,
            Song.album_id,
            UserSongWork.album_played_at.label("played_at"),
            func.row_number().over(
                partition_by=Song.album_id,
                order_by=(UserSongWork.album_played_at.desc(), UserSongWork.song_id.asc()),
            ).label("rank"),
        )
        .select_from(UserSongWork)
        .join(Song, Song.id == UserSongWork.song_id)
        .where(UserSongWork.user_id == viewer_id, UserSongWork.album_played_at.is_not(None))
        .subquery()
    )


def _song_number_in_album() -> ScalarSelect[int]:
    """The song's 1-based place among its album's live songs, in track order."""
    earlier = aliased(Song)
    return (
        select(func.count())
        .select_from(earlier)
        .where(
            earlier.album_id == Song.album_id,
            or_(
                earlier.track_number < Song.track_number,
                and_(earlier.track_number == Song.track_number, earlier.id <= Song.id),
            ),
        )
        .scalar_subquery()
    )


def _first_live_place_per_song(viewer_id: str, owner_id: str | None) -> Subquery:
    """Each song a live entry of the viewer's playlists holds, at its first such place."""
    live_entries = _numbered_live_entries(viewer_id, owner_id)
    ranked_entries = select(
        live_entries,
        func.row_number().over(
            partition_by=(live_entries.c.playlist_id, live_entries.c.song_id),
            order_by=live_entries.c.place,
        ).label("rank"),
    ).subquery()
    return select(
        ranked_entries.c.playlist_id,
        ranked_entries.c.song_id,
        ranked_entries.c.entry_id,
        ranked_entries.c.place.label("song_number"),
    ).where(ranked_entries.c.rank == 1).subquery()


def _numbered_live_entries(viewer_id: str, owner_id: str | None) -> Subquery:
    """The live entries of the viewer's playlists, numbered 1-based in playlist order.

    An entry is live while its take is not archived and its song is live on
    a live, unarchived album the viewer may open. Numbering only live
    entries keeps a removed entry from moving any later song's place.
    """
    return visible_albums(
        select(
            PlaylistEntry.playlist_id,
            PlaylistEntry.id.label("entry_id"),
            Generation.song_id,
            func.row_number().over(
                partition_by=PlaylistEntry.playlist_id,
                order_by=(PlaylistEntry.position.asc(), PlaylistEntry.id.asc()),
            ).label("place"),
        )
        .select_from(PlaylistEntry)
        .join(Playlist, Playlist.id == PlaylistEntry.playlist_id)
        .join(Generation, Generation.id == PlaylistEntry.generation_id)
        .join(Song, Song.id == Generation.song_id)
        .join(Album, Album.id == Song.album_id)
        .where(Playlist.created_by == viewer_id, Generation.is_archived.is_(False)),
        owner_id,
    ).subquery()


def _newest_own_work_per_song(viewer_id: str) -> Subquery:
    """Each song's work of the viewer's own, newest first, ties by kind."""
    own_work = union_all(
        _own_edits(viewer_id),
        _newest_own_take_per_song(viewer_id),
        _newest_own_message_per_song(viewer_id),
    ).subquery()
    return select(
        own_work,
        func.row_number().over(
            partition_by=own_work.c.song_id,
            order_by=(own_work.c.at.desc(), own_work.c.work.asc()),
        ).label("rank"),
    ).subquery()


def _own_edits(viewer_id: str) -> Select:
    """The viewer's latest saved edit on each song, of its recorded kind.

    An edit saved before kinds were recorded has none and reads as ``EDITED``.
    """
    return select(
        UserSongWork.song_id,
        UserSongWork.edited_at.label("at"),
        func.coalesce(UserSongWork.edit_kind, SongWorkKind.EDITED.value).label("work"),
    ).where(UserSongWork.user_id == viewer_id, UserSongWork.edited_at.is_not(None))


def _newest_own_take_per_song(viewer_id: str) -> Select:
    """The newest take the viewer made on each song and has not archived.

    A take made before its maker was recorded names no one and counts for
    no one here.
    """
    return (
        select(
            Generation.song_id,
            func.max(Generation.created_at).label("at"),
            literal(SongWorkKind.TAKE.value).label("work"),
        )
        .where(Generation.created_by == viewer_id, Generation.is_archived.is_(False))
        .group_by(Generation.song_id)
    )


def _newest_own_message_per_song(viewer_id: str) -> Select:
    """The newest message the viewer wrote to the co-writer on each song.

    The co-writer's replies are not the viewer's work and never count.
    """
    return (
        select(
            ChatMessage.song_id,
            func.max(ChatMessage.created_at).label("at"),
            literal(SongWorkKind.COWRITER.value).label("work"),
        )
        .join(Conversation, ChatMessage.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == viewer_id,
            ChatMessage.song_id.is_not(None),
            ChatMessage.role == MUSICIAN_CHAT_ROLE,
        )
        .group_by(ChatMessage.song_id)
    )


def _listen(
    place: Album | Playlist, played_at: datetime, song: Song | None, song_number: int | None,
    entry_id: str | None = None,
) -> PlaceListen:
    return PlaceListen(
        place=place, played_at=_in_utc(played_at), song=song, song_number=song_number,
        entry_id=entry_id,
    )


def _in_utc(moment: datetime) -> datetime:
    return aware_timestamp(moment).astimezone(timezone.utc)


def _most_recent_listen_first(listen: PlaceListen) -> tuple[float, str, str]:
    return (-listen.played_at.timestamp(), listen.place_type, listen.place.id)
