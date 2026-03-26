"""Song and Version API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import (
    check_album_access,
    check_song_access,
    gen_params_to_dict,
    owner_filter,
)
from songmaker_cli.api_models import (
    SongCreateRequest,
    SongResponse,
    SongSummaryResponse,
    SongUpdateRequest,
    StatusResponse,
    VersionResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.db.queries import (
    create_song,
    delete_version,
    get_album,
    list_songs,
    record_audit,
    update_song,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

router = APIRouter()


@router.get("/songs")
def api_list_songs(
    album_id: str | None = Query(None),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[SongSummaryResponse]:
    return [
        SongSummaryResponse.from_orm(s)
        for s in list_songs(session, album_id=album_id, user_id=owner_filter(user), light=True)
    ]


@router.get("/songs/{song_id}")
def api_get_song(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    song = check_song_access(session, song_id, user)
    return SongResponse.from_orm(song)


@router.post("/songs")
def api_create_song(
    req: SongCreateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    album = get_album(session, req.album_id)
    check_album_access(album, user)
    song = create_song(
        session, title=req.title, album_id=req.album_id,
        lyrics=req.lyrics, prompt=req.prompt, bpm=req.bpm,
        duration=req.duration, key=req.key, language=req.language,
        generation_params=gen_params_to_dict(req.generation_params),
    )
    record_audit(session, user.id, "create", "song", song.id)
    session.commit()
    return SongResponse.from_orm(song)


@router.put("/songs/{song_id}")
def api_update_song(
    song_id: str, req: SongUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> SongResponse:
    check_song_access(session, song_id, user)
    kwargs: dict = dict(
        lyrics=req.lyrics, prompt=req.prompt,
        bpm=req.bpm, duration=req.duration, key=req.key,
    )
    if "generation_params" in req.model_fields_set:
        kwargs["generation_params"] = gen_params_to_dict(req.generation_params)
    try:
        version = update_song(session, song_id, **kwargs)
    except ValueError:
        raise HTTPException(404, "Song not found")
    record_audit(session, user.id, "update", "song", song_id)
    session.commit()
    return SongResponse.from_orm(version.song)


@router.get("/songs/{song_id}/versions")
def api_song_versions(
    song_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> list[VersionResponse]:
    song = check_song_access(session, song_id, user)
    return [VersionResponse.from_orm(v) for v in reversed(song.versions)]


@router.delete("/versions/{version_id}")
def api_delete_version(
    version_id: str,
    delete_generations: bool = Query(False),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> StatusResponse:
    from songmaker_cli.db.models import Version as VersionModel

    ver = session.query(VersionModel).filter_by(id=version_id).first()
    if not ver:
        raise HTTPException(404, "Version not found")
    check_song_access(session, ver.song_id, user)
    try:
        delete_version(
            session, version_id,
            delete_generations=delete_generations,
            output_dir=ctx.output_dir,
        )
    except ValueError:
        raise HTTPException(404, "Version not found")
    record_audit(session, user.id, "delete", "version", version_id)
    session.commit()
    return StatusResponse()
