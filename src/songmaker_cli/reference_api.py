"""Reference recording endpoints: the upload, its stored record and the owner's list."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_models import (
    ReferenceCountdownShownRequest,
    ReferenceListResponse,
    ReferenceRecordingResponse,
    ReferenceUsageResponse,
    ReferenceUsesResponse,
    StatusResponse,
)
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    REFERENCE_AUDIO_EXTENSIONS,
    REFERENCE_AUDIO_MAX_BYTES,
    AuditAction,
    ResourceType,
)
from songmaker_cli.db.models import REFERENCE_FILENAME_MAX_LENGTH, ReferenceRecording
from songmaker_cli.db.queries.auth import record_audit
from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.db.queries.reference_recordings import (
    ReferenceLinkCounts,
    acknowledge_countdown_shown,
    delete_reference_recording,
    get_countdown_publication,
    get_owned_reference_recording,
    keep_reference,
    list_owned_reference_recordings,
    owner_reference_usage,
    reference_link_counts,
    reference_uses,
    unkeep_reference,
)
from songmaker_cli.reference_audio import (
    REFERENCE_AUDIO_STORAGE_DETAIL,
    ReferenceAudioQuotaExceeded,
    ReferenceAudioRejected,
    ReferenceAudioStorageError,
    RemovalOutcome,
    is_owner_storage_path,
    reference_deletes_at,
    remove_reference_file,
    resolve_owned_reference_audio,
    store_reference_audio,
)
from songmaker_cli.settings import get_settings
from songmaker_cli.timestamps import utcnow

log = logging.getLogger(__name__)
router = APIRouter()

REFERENCE_IN_USE_DETAIL: Final = "Reference audio is in use."
INVALID_FILENAME_DETAIL: Final = "Invalid filename."
STALE_COUNTDOWN_EPOCH_DETAIL: Final = "The countdown epoch is no longer current."
_CONTROL_CHARACTER: Final = re.compile(r"[\x00-\x1f]")


class OpenedFileResponse(FileResponse):
    """A file response whose ``stat_result`` the caller took from the open file.

    Starlette then never names the path in an error. A file that vanishes or becomes
    unreadable after the headers went out ends the body here, logging the kind only. This
    holds while uvicorn offers no ``pathsend``; an upgrade that adds it needs a re-check.
    """

    def __init__(
        self, path: Path, *, stat_result: os.stat_result, media_type: str | None,
    ) -> None:
        super().__init__(path, stat_result=stat_result, media_type=media_type)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except OSError as exc:
            log.error(  # NOSONAR(S8572) A traceback would name the path.
                "Reference audio ended while it was sent: %s", type(exc).__name__,
            )


@router.get("/references")
def api_list_references(
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ReferenceListResponse:
    recordings = list_owned_reference_recordings(session, user.id)
    counts = reference_link_counts(session, [recording.id for recording in recordings])
    publication = get_countdown_publication(session)
    settings = get_settings()
    now = utcnow()
    items = [
        ReferenceRecordingResponse.from_orm(
            recording, counts[recording.id],
            reference_deletes_at(
                recording.unused_since, publication.published, now,
                settings.final_deletion_days, DAILY_CLEANUP_HOUR_UTC,
            ),
        )
        for recording in recordings
    ]
    return ReferenceListResponse(
        references=items,
        usage=ReferenceUsageResponse.from_orm(owner_reference_usage(session, user.id), settings),
        countdown_epoch=(
            publication.epoch if any(item.deletes_at is not None for item in items) else None
        ),
    )


@router.post(
    "/references/countdown-shown",
    status_code=204,
    responses={409: {"description": "The countdown epoch is no longer current"}},
)
def api_countdown_shown(
    body: ReferenceCountdownShownRequest,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    if not acknowledge_countdown_shown(session, body.epoch, utcnow()):
        raise HTTPException(409, STALE_COUNTDOWN_EPOCH_DETAIL)
    session.commit()
    return Response(status_code=204)


@router.get(
    "/references/{reference_id}/uses",
    responses={404: {"description": "Reference audio not found"}},
)
def api_reference_uses(
    reference_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> ReferenceUsesResponse:
    if get_owned_reference_recording(session, user.id, reference_id) is None:
        raise HTTPException(404)
    return ReferenceUsesResponse.from_orm(reference_uses(session, reference_id))


@router.get(
    "/references/{reference_id}/audio",
    response_class=FileResponse,
    responses={404: {"description": "Reference audio not found or not usable"}},
)
def api_reference_audio(
    reference_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    ctx: Annotated[AppContext, Depends(get_app_context)],
) -> FileResponse:
    recording = get_owned_reference_recording(session, user.id, reference_id)
    if recording is None:
        raise HTTPException(404)
    storage_path = recording.storage_path
    recording_id = recording.id
    session.commit()  # end the transaction: the pooled connection must not outlive the transfer
    try:
        audio_path = resolve_owned_reference_audio(ctx.audio_dir, user.id, storage_path)
        # FileResponse opens after it sent headers, so an unreadable file is refused here.
        with audio_path.open("rb") as audio:
            audio.read(1)
            stat_result = os.fstat(audio.fileno())
    except (ReferenceAudioRejected, OSError) as exc:
        log.error(  # NOSONAR(S8572) A traceback would carry the path, which this log never holds.
            "Reference audio unusable for user %s, reference %s: %s",
            user.id, recording_id, type(exc).__name__,
        )
        raise HTTPException(404) from None
    return OpenedFileResponse(
        audio_path, stat_result=stat_result, media_type=AUDIO_MEDIA_TYPES.get(audio_path.suffix),
    )


@router.delete(
    "/references/{reference_id}",
    status_code=204,
    responses={
        404: {"description": "Reference audio not found"},
        409: {"description": "Reference audio is in use"},
        500: {"description": "Reference audio storage could not be checked"},
    },
)
def api_delete_reference(
    reference_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
    ctx: Annotated[AppContext, Depends(get_app_context)],
) -> Response:
    recording = get_owned_reference_recording(session, user.id, reference_id, lock=True)
    if recording is None:
        raise HTTPException(404)
    recording_id = recording.id
    if not is_owner_storage_path(user.id, recording.storage_path):
        log.error("Reference %s of user %s kept: corrupt_path", recording_id, user.id)
        raise HTTPException(500, REFERENCE_AUDIO_STORAGE_DETAIL)
    try:
        storage_path = delete_reference_recording(session, recording)
    except IntegrityError:
        session.rollback()
        log.info("Reference %s of user %s kept: in_use", recording_id, user.id)
        raise HTTPException(409, REFERENCE_IN_USE_DETAIL) from None
    record_audit(session, user.id, AuditAction.DELETE, ResourceType.REFERENCE, recording_id)
    session.commit()
    outcome = remove_reference_file(ctx.audio_dir, user.id, storage_path)
    log.log(
        logging.WARNING if outcome is RemovalOutcome.FAILED else logging.INFO,
        "Reference %s of user %s deleted: file %s", recording_id, user.id, outcome.value,
    )
    return Response(status_code=204)


def _toggle_keep(
    reference_id: str, user: AuthenticatedUser, session: Session,
    action: Callable[[Session, str, str], ReferenceRecording | None],
) -> StatusResponse:
    if action(session, user.id, reference_id) is None:
        raise HTTPException(404)
    session.commit()
    return StatusResponse()


@router.post(
    "/references/{reference_id}/keep",
    responses={404: {"description": "Reference audio not found"}},
)
def api_keep_reference(
    reference_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> StatusResponse:
    return _toggle_keep(reference_id, user, session, keep_reference)


@router.post(
    "/references/{reference_id}/unkeep",
    responses={404: {"description": "Reference audio not found"}},
)
def api_unkeep_reference(
    reference_id: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db_session)],
) -> StatusResponse:
    return _toggle_keep(reference_id, user, session, unkeep_reference)


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
    if _CONTROL_CHARACTER.search(original_filename):
        raise HTTPException(400, INVALID_FILENAME_DETAIL)
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
        return ReferenceRecordingResponse.from_orm(
            recording, ReferenceLinkCounts(versions=0, takes=0), None,
        )
