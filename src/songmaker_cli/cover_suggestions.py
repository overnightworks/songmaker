"""Cover-suggestion admission and filesystem ownership."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.constants import ALBUM_COVER_SUGGESTIONS_DIRNAME, JobType
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries import (
    count_cover_jobs_since,
    create_job,
    delete_album_cover_suggestions,
    get_album,
    has_active_cover_job,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

ALBUM_NOT_FOUND: Final = "Album not found"
COVER_SUGGESTIONS_ALREADY_RUNNING: Final = "Cover suggestions are already being generated"
DAILY_COVER_SUGGESTION_LIMIT_REACHED: Final = "Daily cover suggestion limit reached"
_COVER_SUGGESTIONS_LOCK_ID: Final = 7


class CoverSuggestionActor(Protocol):
    """The identity facts needed to authorize a cover request."""

    id: str
    role: str


class CoverSuggestionRequestError(Exception):
    """A request outcome the delivery surface maps to its own error protocol."""

    status_code: int


class CoverSuggestionAlbumNotFoundError(CoverSuggestionRequestError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__(ALBUM_NOT_FOUND)


class CoverSuggestionAlreadyRunningError(CoverSuggestionRequestError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__(COVER_SUGGESTIONS_ALREADY_RUNNING)


class CoverSuggestionDailyLimitReachedError(CoverSuggestionRequestError):
    status_code = 429

    def __init__(self) -> None:
        super().__init__(DAILY_COVER_SUGGESTION_LIMIT_REACHED)


@dataclass(frozen=True)
class CoverSuggestionRequest:
    """The durable work created by one accepted cover-suggestion request."""

    job: Job
    stale_suggestion_paths: list[str]


def request_cover_suggestions(
    session: Session, album_id: str, actor: CoverSuggestionActor,
) -> CoverSuggestionRequest:
    """Prepare one cover job after enforcing the album's request contract.

    The caller owns the transaction boundary and any delivery side effects.
    This keeps HTTP and future co-writer surfaces from reimplementing access,
    conflict, limit, and job-creation decisions.
    """
    album = get_album(session, album_id)
    if album is None or (
        actor.role != ROLE_ADMIN and album.created_by != actor.id
    ):
        raise CoverSuggestionAlbumNotFoundError()

    _lock_cover_suggestion_request(session)
    if has_active_cover_job(session, album.id):
        raise CoverSuggestionAlreadyRunningError()

    settings = get_settings()
    used_today = count_cover_jobs_since(session, album.id, _utc_day_start())
    if used_today >= settings.cover_suggestions_daily_limit:
        raise CoverSuggestionDailyLimitReachedError()

    stale_suggestion_paths = delete_album_cover_suggestions(session, album.id)
    job = create_job(session, JobType.COVER, user_id=actor.id, album_id=album.id)
    return CoverSuggestionRequest(job=job, stale_suggestion_paths=stale_suggestion_paths)


def _utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _lock_cover_suggestion_request(session: Session) -> None:
    """Serialize cover-job admission until the caller commits or rolls back."""
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(:id)").bindparams(
            id=_COVER_SUGGESTIONS_LOCK_ID,
        ),
    )


def suggestion_png_path(audio_dir: Path, album_id: str, suggestion_id: str) -> Path:
    relative_path = _expected_relative_path(album_id, suggestion_id)
    from songmaker_cli.audio_paths import canonical_audio_path

    return canonical_audio_path(audio_dir, relative_path)


def resolve_suggestion_png(
    audio_dir: Path, album_id: str, suggestion_id: str, stored_path: str,
) -> Path:
    expected_path = _expected_relative_path(album_id, suggestion_id)
    if stored_path != expected_path:
        raise FileNotFoundError(stored_path)
    from songmaker_cli.audio_paths import canonical_audio_path

    path = canonical_audio_path(audio_dir, stored_path)
    if not path.is_file():
        raise FileNotFoundError(stored_path)
    return path


def remove_cover_suggestion_files(audio_dir: Path, paths: list[str]) -> None:
    from fastapi import HTTPException

    from songmaker_cli.audio_paths import canonical_audio_path

    root = (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).resolve()
    for stored_path in paths:
        try:
            path = canonical_audio_path(audio_dir, stored_path)
        except HTTPException:
            log.warning("Cover suggestion path traversal denied: %r", stored_path)
            continue
        if not path.is_relative_to(root) or path.suffix != ".png":
            log.warning("Cover suggestion path outside suggestion root: %r", stored_path)
            continue
        if path.is_file():
            path.unlink()
        _remove_empty_parents(path.parent, root)


def remove_album_cover_suggestion_files(audio_dir: Path, album_id: str) -> None:
    from fastapi import HTTPException

    try:
        path = suggestion_png_path(audio_dir, album_id, "placeholder").parent
    except HTTPException:
        log.warning("Cover suggestion album traversal denied: %r", album_id)
        return
    root = (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).resolve()
    if path.is_relative_to(root) and path.is_dir():
        shutil.rmtree(path)


def _expected_relative_path(album_id: str, suggestion_id: str) -> str:
    relative_path = PurePosixPath(
        ALBUM_COVER_SUGGESTIONS_DIRNAME, album_id, f"{suggestion_id}.png",
    )
    if (
        len(relative_path.parts) != 3
        or relative_path.parts[0] != ALBUM_COVER_SUGGESTIONS_DIRNAME
        or ".." in relative_path.parts
        or relative_path.as_posix().startswith("/")
    ):
        from fastapi import HTTPException

        raise HTTPException(404, "Not Found")
    return relative_path.as_posix()


def _remove_empty_parents(path: Path, root: Path) -> None:
    while path != root and path.is_relative_to(root):
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent
