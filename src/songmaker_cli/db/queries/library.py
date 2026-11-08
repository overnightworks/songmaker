"""Personal library index — title search with keyset pagination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from songmaker_cli.constants import (
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
    LIKE_ESCAPE_CHAR,
)
from songmaker_cli.db.models import Album, Song
from songmaker_cli.timestamps import aware_timestamp

_SONG_LIST_OPTIONS = (
    joinedload(Song.versions),
    joinedload(Song.generations),
    joinedload(Song.album),
)


@dataclass(frozen=True)
class LibraryCursor:
    q: str
    sort: str
    item_type: str
    sort_value: str
    id: str


def cursor_from_hit(hit: Album | Song, *, q: str, sort: str) -> LibraryCursor:
    if sort == LIBRARY_SORT_TITLE:
        sort_value = hit.title.lower()
    else:
        sort_value = hit.created_at.isoformat()
    return LibraryCursor(
        q=q,
        sort=sort,
        item_type=_hit_type(hit),
        sort_value=sort_value,
        id=hit.id,
    )


@dataclass(frozen=True)
class LibrarySearchPage:
    items: list[Album | Song]
    has_more: bool


def like_contains_pattern(raw: str) -> str:
    escaped = (
        raw.replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR + LIKE_ESCAPE_CHAR)
        .replace("%", LIKE_ESCAPE_CHAR + "%")
        .replace("_", LIKE_ESCAPE_CHAR + "_")
    )
    return f"%{escaped}%"


def title_matches(column, q: str):
    return column.ilike(like_contains_pattern(q), escape=LIKE_ESCAPE_CHAR)


# Keyed by sort so an unknown sort raises KeyError instead of falling back to another order.
_SORT_ASCENDING = {
    LIBRARY_SORT_TITLE: True,
    LIBRARY_SORT_OLDEST: True,
    LIBRARY_SORT_NEWEST: False,
}


def _sort_key(model, sort: str):
    return func.lower(model.title) if sort == LIBRARY_SORT_TITLE else model.created_at


def apply_library_sort(query, model, sort: str):
    key = _sort_key(model, sort)
    if _SORT_ASCENDING[sort]:
        return query.order_by(key.asc(), model.id.asc())
    return query.order_by(key.desc(), model.id.desc())


def search_library(
    session: Session,
    *,
    owner_id: str | None,
    q: str,
    sort: str,
    limit: int,
    after: LibraryCursor | None = None,
) -> LibrarySearchPage:
    fetch_limit = limit + 1
    albums = _matching_albums(
        session, owner_id=owner_id, q=q, sort=sort, after=after, limit=fetch_limit,
    )
    songs = _matching_songs(
        session, owner_id=owner_id, q=q, sort=sort, after=after, limit=fetch_limit,
    )
    merged = _merge_hits(albums, songs, sort)
    return LibrarySearchPage(items=merged[:limit], has_more=len(merged) > limit)


def _matching_albums(
    session: Session,
    *,
    owner_id: str | None,
    q: str,
    sort: str,
    after: LibraryCursor | None,
    limit: int,
) -> list[Album]:
    query = visible_albums(
        session.query(Album).filter(title_matches(Album.title, q)), owner_id,
    )
    keyset = _keyset_clause(Album, sort, after, LIBRARY_ITEM_ALBUM)
    if keyset is not None:
        query = query.filter(keyset)
    query = apply_library_sort(query, Album, sort)
    return query.limit(limit).all()


def _matching_songs(
    session: Session,
    *,
    owner_id: str | None,
    q: str,
    sort: str,
    after: LibraryCursor | None,
    limit: int,
) -> list[Song]:
    query = visible_albums(
        session.query(Song)
        .options(*_SONG_LIST_OPTIONS)
        .join(Album)
        .filter(title_matches(Song.title, q)),
        owner_id,
    )
    keyset = _keyset_clause(Song, sort, after, LIBRARY_ITEM_SONG)
    if keyset is not None:
        query = query.filter(keyset)
    query = apply_library_sort(query, Song, sort)
    return query.limit(limit).all()


def visible_albums(query, owner_id: str | None):
    """Narrow ``query`` to unarchived albums the viewer may open, as ``owner_filter`` decides."""
    query = query.filter(Album.is_archived.is_(False))
    if owner_id is None:
        return query
    return query.filter(Album.created_by == owner_id)


def _keyset_clause(model, sort: str, cursor: LibraryCursor | None, item_type: str):
    if cursor is None:
        return None
    same_type = item_type == cursor.item_type
    type_after = item_type > cursor.item_type
    ascending = _SORT_ASCENDING[sort]
    if sort == LIBRARY_SORT_TITLE:
        value = cursor.sort_value
    else:
        value = _parse_sort_datetime(cursor.sort_value)
    clause = _ascending_keyset_clause if ascending else _descending_keyset_clause
    return clause(_sort_key(model, sort), value, model.id, cursor.id, same_type, type_after)


def _ascending_keyset_clause(key, value, model_id, cursor_id, same_type: bool, type_after: bool):
    if type_after:
        return or_(key > value, key == value)
    if same_type:
        return or_(key > value, and_(key == value, model_id > cursor_id))
    return key > value


def _descending_keyset_clause(key, value, model_id, cursor_id, same_type: bool, type_after: bool):
    if type_after:
        return or_(key < value, key == value)
    if same_type:
        return or_(key < value, and_(key == value, model_id < cursor_id))
    return key < value


def _parse_sort_datetime(value: str) -> datetime:
    return aware_timestamp(datetime.fromisoformat(value))


def _hit_type(hit: Album | Song) -> str:
    return LIBRARY_ITEM_ALBUM if isinstance(hit, Album) else LIBRARY_ITEM_SONG


def _hit_key(hit: Album | Song, sort: str):
    return hit.title.lower() if sort == LIBRARY_SORT_TITLE else hit.created_at


def _album_first(album: Album, song: Song, sort: str) -> bool:
    album_key = _hit_key(album, sort)
    song_key = _hit_key(song, sort)
    if _SORT_ASCENDING[sort]:
        return album_key <= song_key
    return album_key >= song_key


def _merge_hits(
    albums: list[Album], songs: list[Song], sort: str,
) -> list[Album | Song]:
    merged: list[Album | Song] = []
    i = 0
    j = 0
    while i < len(albums) and j < len(songs):
        if _album_first(albums[i], songs[j], sort):
            merged.append(albums[i])
            i += 1
        else:
            merged.append(songs[j])
            j += 1
    merged.extend(albums[i:])
    merged.extend(songs[j:])
    return merged
