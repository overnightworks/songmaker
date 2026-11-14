"""The signed-in person's own audio file endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from webauth.admission import AppRole
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.mcp import Exclusion, exclude_route
from songmaker_cli.api_helpers import audio_file_response, raise_audio_file_http_error
from songmaker_cli.app_context import AppContext, get_app_context
from songmaker_cli.audio_paths import AudioFileNotFoundError, resolve_audio_path
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import AUDIO_FILE_NOT_FOUND

router = APIRouter()


@router.get(
    "/audio/{owner_id}/{filename}",
    responses={404: {"description": "Audio file not found"}},
    openapi_extra=exclude_route(Exclusion.BROWSER_ONLY),
)
async def get_audio(
    owner_id: str,
    filename: str,
    user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ctx: Annotated[AppContext, Depends(get_app_context)],
) -> FileResponse:
    if user.role != AppRole.ADMIN and owner_id != user.id:
        raise HTTPException(404, AUDIO_FILE_NOT_FOUND)  # unread: media

    try:
        audio_path = resolve_audio_path(ctx.audio_dir, f"{owner_id}/{filename}")
    except AudioFileNotFoundError as exc:
        raise_audio_file_http_error(exc, public=False)
    return audio_file_response(audio_path)
