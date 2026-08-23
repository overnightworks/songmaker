"""Generic sharing helpers for models using ShareMixin."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.constants import (
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_GENERATION,
    LIBRARY_ITEM_PLAYLIST,
    LIBRARY_ITEM_SONG,
    SHARE_INVENTORY_TYPES,
)
from songmaker_cli.db.models import Album, Generation, Playlist, ShareMixin, Song

log = logging.getLogger(__name__)

T = TypeVar("T", bound=ShareMixin)

SharedInventoryEntity = Album | Song | Generation | Playlist


@dataclass(frozen=True)
class SharedInventoryPage:
    items: list[SharedInventoryEntity]
    total: int
    filtered_total: int


def enable_sharing(session: Session, model_class: type[T], entity_id: str) -> T:
    entity = session.query(model_class).filter_by(id=entity_id).first()
    if not entity:
        raise ValueError(f"{model_class.__name__} not found: {entity_id}")
    if not entity.share_slug:
        entity.share_slug = str(uuid.uuid4())
    entity.is_shared = True
    session.flush()
    log.info(
        "Enabled sharing for %s %s (slug=%s)",
        model_class.__name__.lower(), entity_id, entity.share_slug,
    )
    return entity


def warm_generation_versions(session: Session, generation_ids: list[str]) -> None:
    """Populate `.version` on already-loaded `Generation` rows in one query.

    Share payload builders read `gen.version.lyrics`/`.audio_duration` for
    every picked generation on a page (an album's tracks, a playlist's
    entries). `Generation.version` lazy-loads by default, so without this
    warm-up each row would trigger its own SELECT. Re-querying the same
    generations with `Generation.version` joined populates the relationship
    on the instances already in the session's identity map, so the later
    `.version` access is free.
    """
    if not generation_ids:
        return
    session.query(Generation).options(joinedload(Generation.version)).filter(
        Generation.id.in_(generation_ids),
    ).all()


def disable_sharing(session: Session, model_class: type[T], entity_id: str) -> T:
    entity = session.query(model_class).filter_by(id=entity_id).first()
    if not entity:
        raise ValueError(f"{model_class.__name__} not found: {entity_id}")
    entity.share_slug = None
    entity.is_shared = False
    session.flush()
    log.info("Disabled sharing for %s %s", model_class.__name__.lower(), entity_id)
    return entity


def count_shared_inventory(session: Session, user_id: str) -> int:
    session.flush()
    return _count_shared_inventory(session, user_id)


def list_shared_inventory(
    session: Session,
    user_id: str,
    *,
    item_type: str | None = None,
    offset: int = 0,
    limit: int,
) -> SharedInventoryPage:
    session.flush()
    if item_type is not None and item_type not in SHARE_INVENTORY_TYPES:
        raise ValueError(f"Unknown share inventory type: {item_type}")
    total = _count_shared_inventory(session, user_id)
    items = _load_shared_entities(session, user_id, item_type)
    items.sort(key=lambda entity: (_inventory_type(entity), entity.id))
    items.sort(key=lambda entity: _aware(entity.created_at), reverse=True)
    return SharedInventoryPage(
        items=items[offset:offset + limit],
        total=total,
        filtered_total=len(items),
    )


def _count_shared_inventory(session: Session, user_id: str) -> int:
    return (
        _shared_albums_query(session, user_id).count()
        + _shared_songs_query(session, user_id).count()
        + _shared_generations_query(session, user_id).count()
        + _shared_playlists_query(session, user_id).count()
    )


def _load_shared_entities(
    session: Session,
    user_id: str,
    item_type: str | None,
) -> list[SharedInventoryEntity]:
    items: list[SharedInventoryEntity] = []
    if item_type is None or item_type == LIBRARY_ITEM_ALBUM:
        items.extend(_shared_albums_query(session, user_id).all())
    if item_type is None or item_type == LIBRARY_ITEM_SONG:
        items.extend(
            _shared_songs_query(session, user_id)
            .options(joinedload(Song.album))
            .all()
        )
    if item_type is None or item_type == LIBRARY_ITEM_GENERATION:
        items.extend(
            _shared_generations_query(session, user_id)
            .options(joinedload(Generation.song).joinedload(Song.album))
            .all()
        )
    if item_type is None or item_type == LIBRARY_ITEM_PLAYLIST:
        items.extend(_shared_playlists_query(session, user_id).all())
    return items


def _shared_albums_query(session: Session, user_id: str):
    return (
        session.query(Album)
        .filter(Album.created_by == user_id)
        .filter(Album.is_shared.is_(True))
        .filter(Album.share_slug.isnot(None))
    )


def _shared_songs_query(session: Session, user_id: str):
    return (
        session.query(Song)
        .join(Album, Song.album_id == Album.id)
        .filter(Album.created_by == user_id)
        .filter(Song.is_shared.is_(True))
        .filter(Song.share_slug.isnot(None))
    )


def _shared_generations_query(session: Session, user_id: str):
    return (
        session.query(Generation)
        .join(Song, Generation.song_id == Song.id)
        .join(Album, Song.album_id == Album.id)
        .filter(Album.created_by == user_id)
        .filter(Generation.is_shared.is_(True))
        .filter(Generation.share_slug.isnot(None))
    )


def _shared_playlists_query(session: Session, user_id: str):
    return (
        session.query(Playlist)
        .filter(Playlist.created_by == user_id)
        .filter(Playlist.is_shared.is_(True))
        .filter(Playlist.share_slug.isnot(None))
    )


def _inventory_type(entity: SharedInventoryEntity) -> str:
    if isinstance(entity, Album):
        return LIBRARY_ITEM_ALBUM
    if isinstance(entity, Song):
        return LIBRARY_ITEM_SONG
    if isinstance(entity, Generation):
        return LIBRARY_ITEM_GENERATION
    if isinstance(entity, Playlist):
        return LIBRARY_ITEM_PLAYLIST
    raise TypeError(f"Unsupported share inventory entity: {type(entity).__name__}")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
