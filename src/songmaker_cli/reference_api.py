"""Reference recording endpoints: the upload and its stored record."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_models import ReferenceRecordingResponse
from songmaker_cli.app_context import AppContext, get_app_context
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import REFERENCE_AUDIO_EXTENSIONS, REFERENCE_AUDIO_MAX_BYTES
from songmaker_cli.db.models import REFERENCE_FILENAME_MAX_LENGTH
from songmaker_cli.db.queries.reference_recordings import get_owned_reference_recording
from songmaker_cli.reference_audio import (
    ReferenceAudioQuotaExceeded,
    ReferenceAudioStorageError,
    store_reference_audio,
)
from songmaker_cli.settings import get_settings

router = APIRouter()


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
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
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

    with ctx.db() as session:
        recording = get_owned_reference_recording(session, user.id, stored.id)
        return ReferenceRecordingResponse.from_orm(recording)
