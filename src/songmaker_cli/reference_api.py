"""Reference recording endpoints: the upload, its stored record and the owner's list."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_models import ReferenceRecordingResponse
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    REFERENCE_AUDIO_EXTENSIONS,
    REFERENCE_AUDIO_MAX_BYTES,
)
from songmaker_cli.db.models import REFERENCE_FILENAME_MAX_LENGTH
from songmaker_cli.db.queries.reference_recordings import (
    get_owned_reference_recording,
    list_owned_reference_recordings,
)
from songmaker_cli.reference_audio import (
    ReferenceAudioQuotaExceeded,
    ReferenceAudioRejected,
    ReferenceAudioStorageError,
    resolve_owned_reference_audio,
    store_reference_audio,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/references")
def api_list_references(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[ReferenceRecordingResponse]:
    return [
        ReferenceRecordingResponse.from_orm(recording)
        for recording in list_owned_reference_recordings(session, user.id)
    ]


@router.get("/references/{reference_id}/audio", response_class=FileResponse)
def api_reference_audio(
    reference_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    ctx: Annotated[AppContext, Depends(get_app_context)],
) -> FileResponse:
    recording = get_owned_reference_recording(session, user.id, reference_id)
    if recording is None:
        raise HTTPException(404)
    try:
        audio_path = resolve_owned_reference_audio(
            ctx.audio_dir, user.id, recording.storage_path,
        )
    except ReferenceAudioRejected as exc:
        log.error(
            "Reference audio unusable for user %s, reference %s: %s",
            user.id, reference_id, type(exc).__name__,
        )
        raise HTTPException(404) from None
    return FileResponse(audio_path, media_type=AUDIO_MEDIA_TYPES.get(audio_path.suffix))


@router.post(
    "/references",
    responses={
        400: {"description": "Reference audio upload is invalid"},
        409: {"description": "Reference audio storage limit reached"},
        500: {"description": "Reference audio storage could not be checked"},
    },
)
async def api_upload_reference(
    file: UploadFile,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ctx: Annotated[AppContext, Depends(get_app_context)],
) -> ReferenceRecordingResponse:
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    original_filename = Path(file.filename).name
    if len(original_filename) > REFERENCE_FILENAME_MAX_LENGTH:
        raise HTTPException(
            400, f"Filename too long (max {REFERENCE_FILENAME_MAX_LENGTH} characters)",
        )
    ext = Path(original_filename).suffix.lower()
    if ext not in REFERENCE_AUDIO_EXTENSIONS:
        accepted = ", ".join(sorted(REFERENCE_AUDIO_EXTENSIONS))
        raise HTTPException(400, f"Unsupported format '{ext}'. Accepted: {accepted}")

    content = await file.read()
    if len(content) > REFERENCE_AUDIO_MAX_BYTES:
        max_mb = REFERENCE_AUDIO_MAX_BYTES // 1024 // 1024
        raise HTTPException(400, f"File too large (max {max_mb}MB)")
    if len(content) < 100:
        raise HTTPException(400, "File is empty or too small")

    try:
        stored = await run_in_threadpool(
            store_reference_audio,
            ctx.db,
            ctx.audio_dir,
            user.id,
            ext,
            content,
            get_settings(),
            original_filename,
        )
    except ReferenceAudioQuotaExceeded as exc:
        raise HTTPException(409, str(exc)) from exc
    except ReferenceAudioStorageError as exc:
        raise HTTPException(500, str(exc)) from exc

    return await run_in_threadpool(_stored_reference_response, ctx, user.id, stored.id)


def _stored_reference_response(
    ctx: AppContext, user_id: str, recording_id: str,
) -> ReferenceRecordingResponse:
    with ctx.db() as session:
        recording = get_owned_reference_recording(session, user_id, recording_id)
        return ReferenceRecordingResponse.from_orm(recording)
