"""Album API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import check_album_access, owner_filter, slugify, unique_album_id
from songmaker_cli.api_models import (
    AlbumCreateRequest,
    AlbumResponse,
    CleanupResponse,
)
from songmaker_cli.config import get_output_dir
from songmaker_cli.db.engine import get_db_session
from songmaker_cli.db.queries import (
    cleanup_album,
    create_album,
    get_album,
    list_albums,
    record_audit,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

log = logging.getLogger(__name__)

router = APIRouter()

_get_session = get_db_session


@router.get("/albums")
def api_list_albums(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> list[AlbumResponse]:
    return [AlbumResponse.from_orm(a) for a in list_albums(session, user_id=owner_filter(user))]


@router.get("/albums/{album_id}")
def api_get_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    return AlbumResponse.from_orm(album)


@router.post("/albums")
def api_create_album(
    data: AlbumCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> AlbumResponse:
    title = data.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    album_id = unique_album_id(session, slugify(title))
    try:
        album = create_album(
            session, album_id, title,
            artist=data.artist,
            created_by=user.id,
        )
        record_audit(session, user.id, "create", "album", album_id)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, f"Album ID conflict for '{title}'. Try a different title.")
    return AlbumResponse.from_orm(album)


@router.post("/albums/{album_id}/cleanup")
def api_cleanup_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(_get_session),
) -> CleanupResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    count = cleanup_album(session, album_id, output_dir=get_output_dir())
    record_audit(session, user.id, "cleanup", "album", album_id, f"deleted={count}")
    session.commit()
    return CleanupResponse(deleted=count)
