"""Cover-suggestion admission and filesystem ownership."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Final

from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import Actor, can_access_album
from songmaker_cli.audio_paths import AudioPathRejectedError, canonical_audio_path, confined_under
from songmaker_cli.constants import ALBUM_COVER_SUGGESTIONS_DIRNAME
from songmaker_cli.db.advisory_locks import AdvisoryLock, lock_until_transaction_ends
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.auth import lock_session_row
from songmaker_cli.db.queries.jobs import count_cover_jobs_since, create_job, has_active_cover_job
from songmaker_cli.job_types import JobType
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

ALBUM_NOT_FOUND: Final = "Album not found"
COVER_SUGGESTIONS_ALREADY_RUNNING: Final = "Cover suggestions are already being generated"
DAILY_COVER_SUGGESTION_LIMIT_REACHED: Final = "Daily cover suggestion limit reached"
SESSION_ENDED: Final = "Log in again to suggest covers."


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


class CoverSuggestionSessionEndedError(CoverSuggestionRequestError):
    status_code = 401

    def __init__(self) -> None:
        super().__init__(SESSION_ENDED)


def request_cover_suggestions(
    session: Session, album_id: str, actor: Actor,
    *, session_id: str | None, require_owner: bool = False,
) -> Job:
    """Prepare one single-image cover job after enforcing the album's request contract.

    Earlier suggestions stay pending: each request adds one image beside them.

    The caller owns the transaction boundary and any delivery side effects.
    This keeps HTTP and future co-writer surfaces from reimplementing access,
    conflict, limit, and job-creation decisions.
    """
    album = get_album(session, album_id)
    if album is None or not can_access_album(album, actor, require_owner=require_owner):
        raise CoverSuggestionAlbumNotFoundError()

    lock_until_transaction_ends(session, AdvisoryLock.COVER_SUGGESTIONS)
    if has_active_cover_job(session, album.id):
        raise CoverSuggestionAlreadyRunningError()

    settings = get_settings()
    used_today = count_cover_jobs_since(session, album.id, utc_day_start())
    if used_today >= settings.cover_suggestions_daily_limit:
        raise CoverSuggestionDailyLimitReachedError()

    if session_id is not None and not lock_session_row(session, session_id):
        raise CoverSuggestionSessionEndedError()

    return create_job(
        session, JobType.COVER, user_id=actor.id, album_id=album.id, session_id=session_id,
    )


def utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def suggestion_png_path(audio_dir: Path, album_id: str, suggestion_id: str) -> Path:
    relative_path = _expected_relative_path(album_id, suggestion_id)

    return canonical_audio_path(audio_dir, relative_path)


def resolve_suggestion_png(
    audio_dir: Path, album_id: str, suggestion_id: str, stored_path: str,
) -> Path:
    expected_path = _expected_relative_path(album_id, suggestion_id)
    if stored_path != expected_path:
        raise FileNotFoundError(stored_path)

    path = canonical_audio_path(audio_dir, stored_path)
    if not path.is_file():
        raise FileNotFoundError(stored_path)
    return path


def remove_cover_suggestion_files(audio_dir: Path, paths: list[str]) -> None:

    root = (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).resolve()
    for stored_path in paths:
        try:
            path = canonical_audio_path(audio_dir, stored_path)
        except AudioPathRejectedError:
            log.warning("Cover suggestion path traversal denied: %r", stored_path)
            continue
        if confined_under(root, path) is None or path.suffix != ".png":
            log.warning("Cover suggestion path outside suggestion root: %r", stored_path)
            continue
        if path.is_file():
            path.unlink()
        _remove_empty_parents(path.parent, root)


def remove_album_cover_suggestion_files(audio_dir: Path, album_id: str) -> None:
    try:
        path = suggestion_png_path(audio_dir, album_id, "placeholder").parent
    except AudioPathRejectedError:
        log.warning("Cover suggestion album traversal denied: %r", album_id)
        return
    root = (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).resolve()
    confined = confined_under(root, path)
    if confined is not None and confined.is_dir():
        shutil.rmtree(confined)


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
        raise AudioPathRejectedError("cover suggestion path is not a direct child of its album")
    return relative_path.as_posix()


def _remove_empty_parents(path: Path, root: Path) -> None:
    while path != root and path.is_relative_to(root):
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent
