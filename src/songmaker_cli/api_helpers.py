"""Shared helpers for API endpoint modules."""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from songmaker_cli.auth import (
    CHAT_RATE_LIMIT_ADMIN,
    CHAT_RATE_LIMIT_USER,
    GENERATION_RATE_LIMIT_ADMIN,
    GENERATION_RATE_LIMIT_USER,
    MAX_QUEUE_DEPTH,
    MAX_USER_ACTIVE_JOBS,
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
    SCORING_RATE_LIMIT_ADMIN,
    SCORING_RATE_LIMIT_USER,
)
from songmaker_cli.db.models import Album, Generation, Job, Song, User
from songmaker_cli.db.queries import (
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_job,
    get_album,
    get_generation,
    get_song,
)
from songmaker_cli.middleware import AuthenticatedUser


def _begin_exclusive(session: Session) -> None:
    """Acquire an exclusive write lock via SERIALIZABLE isolation.

    SQLite branch exists only for test databases (production uses PostgreSQL).
    """
    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    else:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))


_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "generate": (GENERATION_RATE_LIMIT_USER, GENERATION_RATE_LIMIT_ADMIN),
    "score": (SCORING_RATE_LIMIT_USER, SCORING_RATE_LIMIT_ADMIN),
    "chat": (CHAT_RATE_LIMIT_USER, CHAT_RATE_LIMIT_ADMIN),
}


def create_job_with_rate_limit(
    session: Session, user: AuthenticatedUser, job_type: str,
) -> Job:
    """Atomically check rate limits and create a job under BEGIN IMMEDIATE.

    Prevents TOCTOU races where two concurrent requests both pass the rate
    limit check before either creates a job.

    The initial commit() closes the implicit transaction opened by the auth
    dependency (session renewal, IP/UA audit records) so that BEGIN IMMEDIATE
    can acquire an exclusive write lock.  This means auth-layer mutations are
    committed even when the rate limit rejects the request — that is correct
    because session renewal and audit logging must persist regardless.

    Callers must not perform any additional mutations between dependency
    injection and this function; such mutations would be committed
    unconditionally by the commit() here.
    """
    session.commit()
    _begin_exclusive(session)

    is_admin = user.role == ROLE_ADMIN

    if job_type in ("generate", "score"):
        if count_total_queued_jobs(session) >= MAX_QUEUE_DEPTH:
            session.rollback()
            raise HTTPException(429, "Queue is full. Try again later.")
        if not is_admin and count_user_active_jobs(session, user.id) >= MAX_USER_ACTIVE_JOBS:
            session.rollback()
            raise HTTPException(429, "You already have an active job. Wait for it to finish.")

    user_limit, admin_limit = _RATE_LIMITS.get(job_type, (10, 100))
    limit = admin_limit if is_admin else user_limit
    count = count_user_jobs_in_window(session, user.id, job_type, RATE_LIMIT_WINDOW_SECONDS)
    if count >= limit:
        session.rollback()
        raise HTTPException(429, f"Rate limit reached ({limit}/{job_type}s per hour).")

    return create_job(session, job_type, user_id=user.id)


def gen_params_to_dict(params: object | None) -> dict | None:
    """Convert GenerationParams to a plain dict for DB storage, dropping None values."""
    if params is None:
        return None
    return params.to_dict() or None


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe ASCII slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "untitled"


def unique_album_id(session: Session, base_slug: str) -> str:
    """Atomically find a unique album ID, appending -2, -3, etc. if needed.

    Commits the current transaction before acquiring an exclusive lock.
    Same caveats as create_job_with_rate_limit — no prior uncommitted
    mutations besides auth-layer session renewal.
    """
    session.commit()
    _begin_exclusive(session)
    candidate = base_slug
    counter = 1
    while get_album(session, candidate):
        counter += 1
        candidate = f"{base_slug}-{counter}"
    return candidate


def owner_filter(user: AuthenticatedUser) -> str | None:
    if user.role == ROLE_ADMIN:
        return None
    return user.id


def check_album_access(album: Album | None, user: AuthenticatedUser) -> Album:
    if not album:
        raise HTTPException(404, "Album not found")
    if user.role != ROLE_ADMIN and album.created_by != user.id:
        raise HTTPException(404, "Album not found")
    return album


def check_song_access(
    session: Session, song_id: str, user: AuthenticatedUser,
) -> Song:
    """Load a song and verify ownership. Returns the song or raises 404."""
    song = get_song(session, song_id)
    if not song:
        raise HTTPException(404, "Song not found")
    if user.role != ROLE_ADMIN:
        album = song.album
        if not album or album.created_by != user.id:
            raise HTTPException(404, "Song not found")
    return song


def check_generation_access(
    session: Session, gen_id: str, user: AuthenticatedUser,
) -> Generation:
    """Load a generation and verify ownership. Returns the generation or raises 404."""
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, "Generation not found")
    if user.role != ROLE_ADMIN:
        album = gen.song.album if gen.song else None
        if not album or album.created_by != user.id:
            raise HTTPException(404, "Generation not found")
    return gen


_log = logging.getLogger(__name__)


def ensure_not_last_admin(session: Session, user_id: str) -> None:
    """Raise 400 if demoting/deactivating the last active admin."""
    admin_count = session.query(User).filter_by(role="admin", is_active=True).count()
    if admin_count <= 1:
        user = session.get(User, user_id)
        if user and user.role == "admin":
            raise HTTPException(400, "Cannot remove the last active admin")


def cleanup_generation_files(audio_dir: Path, paths: list[str]) -> None:
    from songmaker_cli.db.queries.generations import delete_generation_files

    for rel_path in paths:
        try:
            delete_generation_files(audio_dir, rel_path)
        except Exception:
            _log.warning("Orphaned file after delete: %s", rel_path)
