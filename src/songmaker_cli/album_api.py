"""Album API endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    Pagination,
    check_album_access,
    cleanup_generation_files,
    owner_filter,
    page_has_more,
    parse_optional_search_query,
    resolve_public_base_url,
    unique_album_id,
)
from songmaker_cli.api_models import (
    AlbumCreateRequest,
    AlbumResponse,
    AlbumUpdateRequest,
    CleanupResponse,
    CoverSuggestionSelectionRequest,
    CoverSuggestionsResponse,
    JobResponse,
    LibrarySort,
    PaginatedResponse,
    ShareResponse,
    StatusResponse,
)
from songmaker_cli.api_models.songs import UnplayableSongSummary
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.arq_pool import get_arq_pool, is_music_worker_healthy
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    COVER_MAX_BYTES,
    COVER_NOT_FOUND,
    COVER_SUGGESTION_NOT_FOUND,
    COVER_VARIANT_DETAIL,
    COVER_VERSION_QUERY,
    AuditAction,
    JobFunction,
    JobStatus,
    ResourceType,
)
from songmaker_cli.cover_suggestions import (
    CoverSuggestionRequestError,
    remove_cover_suggestion_files,
    request_cover_suggestions,
    resolve_suggestion_png,
)
from songmaker_cli.covers import (
    COVER_RESPONSE_HEADERS,
    CoverRejectedError,
    cover_media_type,
    remove_album_cover_files,
    resolve_cover_file,
    write_album_cover,
)
from songmaker_cli.db.models import Album
from songmaker_cli.db.queries import (
    UNSET,
    RestoreWindowExpiredError,
    archive_album,
    cleanup_album,
    count_albums,
    count_cover_jobs_since,
    count_picked_songs_by_album,
    count_songs_by_album,
    create_album,
    delete_album_cover_suggestions,
    disable_album_sharing,
    enable_album_sharing,
    get_album,
    get_album_cover_suggestion,
    get_last_cover_job_for_album,
    list_album_cover_suggestions,
    list_albums,
    record_audit,
    restore_album,
    set_album_cover_key,
    soft_delete_album,
    unarchive_album,
    update_album,
    update_job_status,
)
from songmaker_cli.db.queries.sharing import songs_without_playable_take
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter()


def _single_album_response(session: Session, album: Album) -> AlbumResponse:
    """Build an AlbumResponse for one album, fetching its counts fresh.

    Each aggregate call is scoped to a single-element id list -- the same
    aggregate query api_list_albums batches across a whole page, just
    invoked for one album instead of many.
    """
    picked_counts = count_picked_songs_by_album(session, [album.id])
    song_counts = count_songs_by_album(session, [album.id])
    return AlbumResponse.from_orm(
        album,
        song_count=song_counts.get(album.id, 0),
        picked_count=picked_counts.get(album.id, 0),
    )


@router.get("/albums")
def api_list_albums(
    page: Pagination,
    q: str | None = Query(None),
    sort: LibrarySort | None = Query(None),
    archived: bool = Query(False),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> PaginatedResponse[AlbumResponse]:
    query = parse_optional_search_query(q)
    uid = owner_filter(user)
    total = count_albums(session, user_id=uid, q=query, archived=archived)
    albums = list_albums(
        session, user_id=uid, offset=page.offset, limit=page.limit,
        q=query, sort=sort, archived=archived,
    )
    picked_counts = count_picked_songs_by_album(session, [a.id for a in albums])
    song_counts = count_songs_by_album(session, [a.id for a in albums])
    items = [
        AlbumResponse.from_orm(
            a, song_count=song_counts.get(a.id, 0), picked_count=picked_counts.get(a.id, 0),
        )
        for a in albums
    ]
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
    return _single_album_response(session, album)


@router.post("/albums")
def api_create_album(
    data: AlbumCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    title = data.title.strip()
    if not title:
        raise HTTPException(422, "Title is required")
    album_id = unique_album_id(session, title)
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
    return AlbumResponse.from_orm(album, song_count=0, picked_count=0)


@router.put("/albums/{album_id}")
def api_update_album(
    album_id: str, req: AlbumUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    """Update album title, subtitle, and/or year.

    Each field is independently optional: a field absent from the request
    body is left unchanged, letting the header commit one edited field at a
    time (as EditableTitle already does for title). A request with no
    fields at all is a no-op -- no audit row, no commit.
    """
    album = get_album(session, album_id)
    check_album_access(album, user)
    fields_set = req.model_fields_set
    if not fields_set:
        return _single_album_response(session, album)

    title: str | None = None
    if "title" in fields_set:
        title = req.title.strip() if req.title else ""
        if not title:
            raise HTTPException(422, "Title is required")

    subtitle = (req.subtitle or "").strip() if "subtitle" in fields_set else UNSET
    year = (str(req.year) if req.year is not None else "") if "year" in fields_set else UNSET

    try:
        album = update_album(session, album_id, title=title, subtitle=subtitle, year=year)
    except ValueError:
        raise HTTPException(404, "Album not found")
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.ALBUM, album_id)
    session.commit()
    return _single_album_response(session, album)


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
    return _single_album_response(session, restored)


@router.post("/albums/{album_id}/archive")
def api_archive_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    """Hide the album from the default library, search, and mix/pool.

    A visibility flag, not a soft-delete: songs and any existing share
    links stay intact (see get_album_by_slug) and the album remains
    reachable directly by ID until unarchive_album reverses it.
    """
    album = get_album(session, album_id)
    check_album_access(album, user)
    album = archive_album(session, album_id)
    record_audit(session, user.id, AuditAction.ARCHIVE, ResourceType.ALBUM, album_id)
    session.commit()
    return _single_album_response(session, album)


@router.post("/albums/{album_id}/unarchive")
def api_unarchive_album(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    album = unarchive_album(session, album_id)
    record_audit(session, user.id, AuditAction.UNARCHIVE, ResourceType.ALBUM, album_id)
    session.commit()
    return _single_album_response(session, album)


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
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ShareResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    base_url = resolve_public_base_url()
    album = enable_album_sharing(session, album_id)
    missing = songs_without_playable_take(session, album_id)
    record_audit(session, user.id, AuditAction.SHARE, ResourceType.ALBUM, album_id)
    session.commit()
    return ShareResponse(
        share_url=f"{base_url}/share/{album.share_slug}",
        share_slug=album.share_slug,
        songs_without_playable_take=[
            UnplayableSongSummary(id=song.id, title=song.title) for song in missing
        ],
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

@router.get("/albums/{album_id}/cover")
async def api_get_album_cover(
    album_id: str,
    variant: str = Query(COVER_VARIANT_DETAIL),
    v: str | None = Query(None, alias=COVER_VERSION_QUERY),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    if v is not None and v != album.cover_key:
        raise HTTPException(404, COVER_NOT_FOUND)
    try:
        path = resolve_cover_file(ctx.audio_dir, album.id, album.cover_key, variant)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except FileNotFoundError:
        raise HTTPException(404, COVER_NOT_FOUND)
    return FileResponse(
        path,
        media_type=cover_media_type(variant, album.cover_key or ""),
        headers=COVER_RESPONSE_HEADERS,
    )


@router.post("/albums/{album_id}/cover")
async def api_upload_album_cover(
    album_id: str,
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    payload = await file.read(COVER_MAX_BYTES + 1)
    try:
        cover_key = write_album_cover(ctx.audio_dir, album.id, payload)
    except CoverRejectedError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    album = set_album_cover_key(session, album.id, cover_key)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.ALBUM, album.id)
    session.commit()
    return _single_album_response(session, album)


def _utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.post(
    "/albums/{album_id}/cover-suggestions",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Album not found"},
        status.HTTP_409_CONFLICT: {"description": "Cover suggestions are already running"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Daily suggestion limit reached"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Cover suggestions are unavailable"},
    },
)
async def api_create_cover_suggestions(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> JobResponse:
    session.commit()
    try:
        request = request_cover_suggestions(session, album_id, user)
        if not await is_music_worker_healthy():
            raise HTTPException(503, "Worker not running")
        session.commit()
    except CoverSuggestionRequestError as exc:
        session.rollback()
        raise HTTPException(exc.status_code, str(exc)) from exc
    except HTTPException:
        session.rollback()
        raise
    remove_cover_suggestion_files(ctx.audio_dir, request.stale_suggestion_paths)
    try:
        await get_arq_pool().enqueue_job(
            JobFunction.COVER,
            request.job.id,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
        )
    except (ConnectionError, RuntimeError):
        update_job_status(
            session,
            request.job.id,
            JobStatus.FAILED,
            error="Job queue unavailable",
            error_type="queue_unavailable",
        )
        session.commit()
        raise HTTPException(503, "Job queue unavailable")
    return JobResponse.from_orm(request.job)


@router.get("/albums/{album_id}/cover-suggestions")
def api_list_cover_suggestions(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> CoverSuggestionsResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    settings = get_settings()
    return CoverSuggestionsResponse.from_orm(
        job=get_last_cover_job_for_album(session, album.id),
        suggestions=list_album_cover_suggestions(session, album.id),
        used_today=count_cover_jobs_since(session, album.id, _utc_day_start()),
        daily_limit=settings.cover_suggestions_daily_limit,
    )


@router.get("/albums/{album_id}/cover-suggestions/{suggestion_id}")
def api_get_cover_suggestion(
    album_id: str,
    suggestion_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> FileResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    suggestion = get_album_cover_suggestion(session, album.id, suggestion_id)
    if suggestion is None:
        raise HTTPException(404, COVER_SUGGESTION_NOT_FOUND)
    try:
        path = resolve_suggestion_png(ctx.audio_dir, album.id, suggestion.id, suggestion.png_path)
    except (FileNotFoundError, HTTPException):
        raise HTTPException(404, COVER_SUGGESTION_NOT_FOUND) from None
    return FileResponse(path, media_type="image/png", headers=COVER_RESPONSE_HEADERS)


@router.put("/albums/{album_id}/cover")
def api_select_album_cover_suggestion(
    album_id: str,
    data: CoverSuggestionSelectionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    suggestion = get_album_cover_suggestion(session, album.id, data.suggestion_id)
    if suggestion is None:
        raise HTTPException(404, COVER_SUGGESTION_NOT_FOUND)
    try:
        payload = resolve_suggestion_png(
            ctx.audio_dir, album.id, suggestion.id, suggestion.png_path,
        ).read_bytes()
        cover_key = write_album_cover(ctx.audio_dir, album.id, payload)
    except (FileNotFoundError, HTTPException):
        raise HTTPException(404, COVER_SUGGESTION_NOT_FOUND) from None
    except CoverRejectedError as exc:
        raise HTTPException(422, str(exc)) from exc
    album = set_album_cover_key(session, album.id, cover_key)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.ALBUM, album.id)
    session.commit()
    return _single_album_response(session, album)


@router.delete("/albums/{album_id}/cover-suggestions")
def api_delete_cover_suggestions(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    paths = delete_album_cover_suggestions(session, album.id)
    session.commit()
    remove_cover_suggestion_files(ctx.audio_dir, paths)
    return StatusResponse()


@router.delete("/albums/{album_id}/cover")
def api_delete_album_cover(
    album_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> AlbumResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    album = set_album_cover_key(session, album.id, None)
    record_audit(session, user.id, AuditAction.UPDATE, ResourceType.ALBUM, album.id)
    session.commit()
    remove_album_cover_files(ctx.audio_dir, album.id)
    return _single_album_response(session, album)
