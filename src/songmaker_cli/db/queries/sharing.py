"""Generic sharing helpers for models using ShareMixin."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import ColumnElement, and_, func, or_
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.util import AliasedClass

from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    ShareMixin,
    Song,
)

log = logging.getLogger(__name__)

def enable_sharing[T: ShareMixin](session: Session, model_class: type[T], entity_id: str) -> T:
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


def disable_sharing[T: ShareMixin](session: Session, model_class: type[T], entity_id: str) -> T:
    entity = session.query(model_class).filter_by(id=entity_id).first()
    if not entity:
        raise ValueError(f"{model_class.__name__} not found: {entity_id}")
    entity.share_slug = None
    entity.is_shared = False
    session.flush()
    log.info("Disabled sharing for %s %s", model_class.__name__.lower(), entity_id)
    return entity


def is_playable_take(gen: Generation) -> bool:
    """A generation the public share page can actually play: non-archived,
    with a real (non-empty) mp3 file. The single owner of "is this take
    playable" -- both `_picked_generation` (sharing_api.py) and
    `songs_without_playable_take` below must agree with this, or a song can
    silently vanish from /shared/{slug} without the owner being warned."""
    return bool(gen.mp3_path) and not gen.is_archived


def playable_take_filter(
    entity: type[Generation] | AliasedClass = Generation,
) -> ColumnElement[bool]:
    """SQLAlchemy criteria mirroring `is_playable_take()`, for queries that
    can't load full Generation rows into Python."""
    return and_(
        entity.mp3_path.isnot(None),
        entity.mp3_path != "",
        entity.is_archived.is_(False),
    )


def shared_album_audio_filename_is_presented(
    session: Session,
    slug: str,
    filename: str,
) -> bool:
    return _shared_pick_audio_filename_is_presented(
        session,
        filename,
        share_condition=and_(
            Album.share_slug == slug,
            Album.is_shared.is_(True),
        ),
        album_join=(Album, Song.album_id == Album.id),
    )


def shared_song_audio_filename_is_presented(
    session: Session,
    slug: str,
    filename: str,
) -> bool:
    return _shared_pick_audio_filename_is_presented(
        session,
        filename,
        share_condition=and_(
            Song.share_slug == slug,
            Song.is_shared.is_(True),
        ),
    )


def _shared_pick_audio_filename_is_presented(
    session: Session,
    filename: str,
    *,
    share_condition: ColumnElement[bool],
    album_join: tuple[type[Album], ColumnElement[bool]] | None = None,
) -> bool:
    """Mirror the picked-or-latest-playable selection in the public share
    page without loading an album graph merely to authorize its audio URL."""
    candidate_generation = aliased(Generation)
    selected_picked_generation = aliased(Generation)
    song_has_playable_pick = (
        session.query(candidate_generation.id)
        .filter(
            candidate_generation.song_id == Generation.song_id,
            candidate_generation.is_picked.is_(True),
            playable_take_filter(candidate_generation),
        )
        .exists()
    )
    selected_playable_pick_id = (
        session.query(selected_picked_generation.id)
        .filter(
            selected_picked_generation.song_id == Generation.song_id,
            selected_picked_generation.is_picked.is_(True),
            playable_take_filter(selected_picked_generation),
        )
        .order_by(selected_picked_generation.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    latest_playable_generation_number = (
        session.query(func.max(candidate_generation.generation_number))
        .filter(
            candidate_generation.song_id == Generation.song_id,
            playable_take_filter(candidate_generation),
        )
        .scalar_subquery()
    )
    matching_generation_query = (
        session.query(Generation.mp3_path)
        .join(Song, Generation.song_id == Song.id)
        .filter(
            playable_take_filter(),
            or_(
                and_(
                    Generation.is_picked.is_(True),
                    Generation.id == selected_playable_pick_id,
                ),
                and_(
                    ~song_has_playable_pick,
                    Generation.generation_number == latest_playable_generation_number,
                ),
            ),
        )
    )
    if album_join is not None:
        matching_generation_query = matching_generation_query.join(*album_join)
    return matching_generation_query.filter(
        share_condition,
        Generation.mp3_path == filename,
    ).first() is not None


def shared_playlist_audio_filename_is_presented(
    session: Session,
    slug: str,
    filename: str,
) -> bool:
    """Whether the public playlist presents this playable entry's audio URL.

    Unlike album and song shares, a playlist presents every playable entry,
    rather than choosing a picked or latest fallback generation.
    """
    matching_filenames = (
        session.query(PlaylistEntry)
        .join(Playlist, PlaylistEntry.playlist_id == Playlist.id)
        .join(Generation, PlaylistEntry.generation_id == Generation.id)
        .with_entities(Generation.mp3_path)
        .filter(
            Playlist.share_slug == slug,
            Playlist.is_shared.is_(True),
            playable_take_filter(),
            Generation.mp3_path == filename,
        )
        .first()
    )
    return matching_filenames is not None


def songs_without_playable_take(session: Session, album_id: str) -> list[Song]:
    """Songs on the album with no playable take (see `is_playable_take`) --
    a song failing this check is silently absent from the /shared/{slug}
    payload."""
    has_take = (
        session.query(Generation.song_id)
        .filter(Generation.song_id == Song.id)
        .filter(playable_take_filter())
        .exists()
    )
    return (
        session.query(Song)
        .filter(Song.album_id == album_id)
        .filter(~has_take)
        .order_by(Song.track_number)
        .all()
    )
