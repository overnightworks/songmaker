"""Personal library index — title search with keyset pagination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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
from songmaker_cli.library_cursor import LibraryCursor

_SONG_LIST_OPTIONS = (
    joinedload(Song.versions),
    joinedload(Song.generations),
    joinedload(Song.album),
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


def apply_library_sort(query, model, sort: str | None):
    if sort is None:
        return query
    if sort == LIBRARY_SORT_TITLE:
        return query.order_by(func.lower(model.title).asc(), model.id.asc())
    if sort == LIBRARY_SORT_OLDEST:
        return query.order_by(model.created_at.asc(), model.id.asc())
    if sort == LIBRARY_SORT_NEWEST:
        return query.order_by(model.created_at.desc(), model.id.desc())
    raise ValueError(f"Unknown library sort: {sort}")


def search_library(
    session: Session,
    *,
    user_id: str,
    q: str,
    sort: str,
    limit: int,
    after: LibraryCursor | None = None,
) -> LibrarySearchPage:
    fetch_limit = limit + 1
    albums = _matching_albums(
        session, user_id=user_id, q=q, sort=sort, after=after, limit=fetch_limit,
    )
    songs = _matching_songs(
        session, user_id=user_id, q=q, sort=sort, after=after, limit=fetch_limit,
    )
    merged = _merge_hits(albums, songs, sort)
    unique = _dedupe_hits(merged)
    has_more = len(unique) > limit
    return LibrarySearchPage(items=unique[:limit], has_more=has_more)


def _matching_albums(
    session: Session,
    *,
    user_id: str,
    q: str,
    sort: str,
    after: LibraryCursor | None,
    limit: int,
) -> list[Album]:
    query = (
        session.query(Album)
        .filter(Album.created_by == user_id)
        .filter(Album.is_archived.is_(False))
        .filter(title_matches(Album.title, q))
    )
    keyset = _keyset_clause(Album, sort, after, LIBRARY_ITEM_ALBUM)
    if keyset is not None:
        query = query.filter(keyset)
    query = apply_library_sort(query, Album, sort)
    return query.limit(limit).all()


def _matching_songs(
    session: Session,
    *,
    user_id: str,
    q: str,
    sort: str,
    after: LibraryCursor | None,
    limit: int,
) -> list[Song]:
    query = (
        session.query(Song)
        .options(*_SONG_LIST_OPTIONS)
        .join(Album)
        .filter(Album.created_by == user_id)
        .filter(Album.is_archived.is_(False))
        .filter(title_matches(Song.title, q))
    )
    keyset = _keyset_clause(Song, sort, after, LIBRARY_ITEM_SONG)
    if keyset is not None:
        query = query.filter(keyset)
    query = apply_library_sort(query, Song, sort)
    return query.limit(limit).all()


def _keyset_clause(model, sort: str, cursor: LibraryCursor | None, item_type: str):
    if cursor is None:
        return None
    same_type = item_type == cursor.item_type
    type_after = item_type > cursor.item_type
    if sort == LIBRARY_SORT_TITLE:
        return _ascending_keyset_clause(
            func.lower(model.title), cursor.sort_value, model.id, cursor.id, same_type, type_after,
        )
    timestamp = _parse_sort_datetime(cursor.sort_value)
    if sort == LIBRARY_SORT_OLDEST:
        return _ascending_keyset_clause(
            model.created_at, timestamp, model.id, cursor.id, same_type, type_after,
        )
    if sort == LIBRARY_SORT_NEWEST:
        return _descending_keyset_clause(
            model.created_at, timestamp, model.id, cursor.id, same_type, type_after,
        )
    raise ValueError(f"Unknown library sort: {sort}")


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
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _hit_type(hit: Album | Song) -> str:
    return LIBRARY_ITEM_ALBUM if isinstance(hit, Album) else LIBRARY_ITEM_SONG


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _hit_before(left: Album | Song, right: Album | Song, sort: str) -> bool:
    left_type = _hit_type(left)
    right_type = _hit_type(right)
    if sort == LIBRARY_SORT_TITLE:
        left_title = left.title.lower()
        right_title = right.title.lower()
        if left_title != right_title:
            return left_title < right_title
        if left_type != right_type:
            return left_type < right_type
        return left.id < right.id
    left_ts = _aware(left.created_at)
    right_ts = _aware(right.created_at)
    if sort == LIBRARY_SORT_OLDEST:
        if left_ts != right_ts:
            return left_ts < right_ts
        if left_type != right_type:
            return left_type < right_type
        return left.id < right.id
    if sort != LIBRARY_SORT_NEWEST:
        raise ValueError(f"Unknown library sort: {sort}")
    if left_ts != right_ts:
        return left_ts > right_ts
    if left_type != right_type:
        return left_type < right_type
    return left.id > right.id


def _merge_hits(
    albums: list[Album], songs: list[Song], sort: str,
) -> list[Album | Song]:
    merged: list[Album | Song] = []
    i = 0
    j = 0
    while i < len(albums) and j < len(songs):
        if _hit_before(albums[i], songs[j], sort):
            merged.append(albums[i])
            i += 1
        else:
            merged.append(songs[j])
            j += 1
    merged.extend(albums[i:])
    merged.extend(songs[j:])
    return merged


def _dedupe_hits(hits: list[Album | Song]) -> list[Album | Song]:
    seen: set[tuple[str, str]] = set()
    unique: list[Album | Song] = []
    for hit in hits:
        key = (_hit_type(hit), hit.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique
