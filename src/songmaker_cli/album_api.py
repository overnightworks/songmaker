"""Album API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    Pagination,
    check_album_access,
    cleanup_generation_files,
    owner_filter,
    page_has_more,
    parse_optional_search_query,
    slugify,
    unique_album_id,
)
from songmaker_cli.api_models import (
    AlbumCreateRequest,
    AlbumResponse,
    CleanupResponse,
    LibrarySort,
    PaginatedResponse,
    ShareResponse,
    StatusResponse,
    TitleUpdateRequest,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.queries import (
    RestoreWindowExpiredError,
    cleanup_album,
    count_albums,
    create_album,
    disable_album_sharing,
    enable_album_sharing,
    get_album,
    list_albums,
    record_audit,
    rename_album,
    restore_album,
    soft_delete_album,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/albums")
def api_list_albums(
    page: Pagination,
    q: str | None = Query(None),
    sort: LibrarySort | None = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PaginatedResponse[AlbumResponse]:
    query = parse_optional_search_query(q)
    uid = owner_filter(user)
    total = count_albums(session, user_id=uid, q=query)
    albums = list_albums(
        session, user_id=uid, offset=page.offset, limit=page.limit,
        q=query, sort=sort,
    )
    items = [AlbumResponse.from_orm(a) for a in albums]
    return PaginatedResponse(
        items=items,
        total=total, offset=page.offset, limit=page.limit,
        has_more=page_has_more(offset=page.offset, fetched=len(items), total=total),
    )


@router.get("/albums/{album_id}")
def api_get_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    return AlbumResponse.from_orm(album)


@router.post("/albums")
def api_create_album(
    data: AlbumCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
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
        record_audit(session, user.id, AuditAction.CREATE, ResourceType.ALBUM, album_id)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, f"Album ID conflict for '{title}'. Try a different title.")
    return AlbumResponse.from_orm(album)


@router.put("/albums/{album_id}/title")
def api_rename_album(
    album_id: str, req: TitleUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    title = req.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    try:
        album = rename_album(session, album_id, title)
    except ValueError:
        raise HTTPException(404, "Album not found")
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.ALBUM, album_id)
    session.commit()
    return AlbumResponse.from_orm(album)


@router.delete("/albums/{album_id}")
def api_delete_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    soft_delete_album(session, album_id)
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.ALBUM, album_id)
    session.commit()
    return StatusResponse()


@router.post("/albums/{album_id}/restore")
def api_restore_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    album = get_album(session, album_id, include_deleted_rows=True)
    check_album_access(album, user)
    try:
        restored = restore_album(session, album_id)
    except RestoreWindowExpiredError as e:
        raise HTTPException(410, str(e))
    record_audit(session, user.id, AuditAction.RESTORE, ResourceType.ALBUM, album_id)
    session.commit()
    return AlbumResponse.from_orm(restored)


@router.post("/albums/{album_id}/cleanup")
def api_cleanup_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> CleanupResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    count, paths = cleanup_album(session, album_id)
    record_audit(
        session, user.id, AuditAction.CLEANUP, ResourceType.ALBUM,
        album_id, f"deleted={count}",
    )
    session.commit()
    cleanup_generation_files(ctx.audio_dir, paths)
    return CleanupResponse(deleted=count)


@router.post("/albums/{album_id}/share")
def api_share_album(
    album_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    album = enable_album_sharing(session, album_id)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.ALBUM, album_id)
    session.commit()
    base_url = str(request.base_url).rstrip("/")
    return ShareResponse(
        share_url=f"{base_url}/share/{album.share_slug}",
        share_slug=album.share_slug,
    )


@router.delete("/albums/{album_id}/share")
def api_unshare_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    disable_album_sharing(session, album_id)
    record_audit(session, user.id, AuditAction.UNSHARE, ResourceType.ALBUM, album_id)
    session.commit()
    return StatusResponse()
