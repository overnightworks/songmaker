"""Reimport API endpoint — upload MP3/WAV files for an existing song."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import check_song_access
from songmaker_cli.api_models import GenerationResponse
from songmaker_cli.app_context import AppContext, get_app_context, get_db_session
from songmaker_cli.db.queries import get_generation
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.reimport import reimport_files
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_CONTENT_TYPES = frozenset({
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "application/octet-stream",
})


def _validate_upload(file: UploadFile, label: str) -> None:
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(422, f"Invalid {label} content type: {content_type}")


@router.post("/songs/{song_id}/reimport")
async def api_reimport(
    song_id: str,
    mp3: UploadFile | None = None,
    wav: UploadFile | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
    ctx: AppContext = Depends(get_app_context),
) -> GenerationResponse:
    if not mp3 and not wav:
        raise HTTPException(422, "At least one file (mp3 or wav) is required")

    check_song_access(session, song_id, user)

    if mp3:
        _validate_upload(mp3, "mp3")
    if wav:
        _validate_upload(wav, "wav")

    max_upload_bytes = get_settings().max_upload_body_bytes
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        mp3_path: Path | None = None
        wav_path: Path | None = None

        if mp3:
            mp3_path = tmp_path / "upload.mp3"
            content = await mp3.read(max_upload_bytes + 1)
            if len(content) > max_upload_bytes:
                raise HTTPException(413, "MP3 file too large")
            mp3_path.write_bytes(content)

        if wav:
            wav_path = tmp_path / "upload.wav"
            content = await wav.read(max_upload_bytes + 1)
            if len(content) > max_upload_bytes:
                raise HTTPException(413, "WAV file too large")
            wav_path.write_bytes(content)

        gen_id = reimport_files(
            session, ctx.audio_dir, user.id, song_id,
            mp3_file=mp3_path, wav_file=wav_path,
        )

    session.commit()
    gen = get_generation(session, gen_id)
    return GenerationResponse.from_orm(gen)
