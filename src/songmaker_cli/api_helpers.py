"""Shared helpers for API endpoint modules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from slugify import slugify as _slugify
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
from songmaker_cli.constants import (
    PAGE_ADMIN_DEFAULT_LIMIT,
    PAGE_ADMIN_MAX_LIMIT,
    PAGE_DEFAULT_LIMIT,
    PAGE_MAX_LIMIT,
    SETTING_CHAT_RATE_LIMIT,
    SETTING_GENERATION_RATE_LIMIT,
    SETTING_MAX_QUEUE_DEPTH,
    SETTING_MAX_USER_ACTIVE_JOBS,
    SETTING_SCORING_RATE_LIMIT,
    JobType,
)
from songmaker_cli.db.models import Album, Generation, Job, Song, User
from songmaker_cli.db.queries import (
    clear_stale_user_jobs,
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_job,
    get_album,
    get_generation,
    get_song,
    resolve_rate_limit,
)
from songmaker_cli.middleware import AuthenticatedUser

_RATE_LIMIT_LOCK_ID = 1
_ALBUM_ID_LOCK_ID = 2


def _begin_exclusive(session: Session, lock_id: int = _RATE_LIMIT_LOCK_ID) -> None:
    """Acquire an exclusive write lock for check-then-act sequences.

    PostgreSQL: advisory lock scoped to the transaction (auto-released on
    commit/rollback). Different lock_ids allow independent serialization.
    SQLite: BEGIN IMMEDIATE (global write lock, test databases only).
    """
    dialect = session.bind.dialect.name
    if dialect == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    else:
        session.execute(text("SELECT pg_advisory_xact_lock(:id)").bindparams(id=lock_id))


def check_redis_health(request) -> None:
    """Reject mutation requests when Redis is degraded (fail-closed)."""
    from songmaker_cli.constants import REDIS_DEGRADED_THRESHOLD
    from songmaker_cli.redis_client import SessionCache

    cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if cache and cache.consecutive_failures >= REDIS_DEGRADED_THRESHOLD:
        raise HTTPException(503, "Service temporarily degraded — try again shortly")


_ENV_RATE_LIMITS: dict[JobType, tuple[int, int, str]] = {
    JobType.GENERATE: (
        GENERATION_RATE_LIMIT_USER, GENERATION_RATE_LIMIT_ADMIN,
        SETTING_GENERATION_RATE_LIMIT,
    ),
    JobType.SCORE: (
        SCORING_RATE_LIMIT_USER, SCORING_RATE_LIMIT_ADMIN,
        SETTING_SCORING_RATE_LIMIT,
    ),
    JobType.CHAT: (
        CHAT_RATE_LIMIT_USER, CHAT_RATE_LIMIT_ADMIN,
        SETTING_CHAT_RATE_LIMIT,
    ),
}

_QUEUEABLE_JOB_TYPES = frozenset({JobType.GENERATE, JobType.SCORE})


def create_job_with_rate_limit(
    session: Session, user: AuthenticatedUser, job_type: JobType,
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
    assert not session.new and not session.dirty and not session.deleted, (
        "create_job_with_rate_limit: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    session.commit()
    _begin_exclusive(session)

    is_admin = user.role == ROLE_ADMIN
    clear_stale_user_jobs(session, user.id)

    if job_type in _QUEUEABLE_JOB_TYPES:
        max_queue = resolve_rate_limit(
            session, user.id, SETTING_MAX_QUEUE_DEPTH, MAX_QUEUE_DEPTH,
        )
        if count_total_queued_jobs(session) >= max_queue:
            session.rollback()
            raise HTTPException(429, "Queue is full. Try again later.")
        if not is_admin:
            max_active = resolve_rate_limit(
                session, user.id, SETTING_MAX_USER_ACTIVE_JOBS, MAX_USER_ACTIVE_JOBS,
            )
            if count_user_active_jobs(session, user.id, job_type) >= max_active:
                session.rollback()
                raise HTTPException(429, "You already have an active job. Wait for it to finish.")

    env_user, env_admin, setting_key = _ENV_RATE_LIMITS.get(job_type, (10, 100, ""))
    if is_admin:
        limit = env_admin
    else:
        limit = (
            resolve_rate_limit(session, user.id, setting_key, env_user)
            if setting_key else env_user
        )
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


def slugify(value: str) -> str:
    return _slugify(value) or "untitled"


def unique_album_id(session: Session, base_slug: str) -> str:
    """Atomically find a unique album ID, appending -2, -3, etc. if needed.

    Commits the current transaction before acquiring an exclusive lock.
    Same caveats as create_job_with_rate_limit — no prior uncommitted
    mutations besides auth-layer session renewal.
    """
    assert not session.new and not session.dirty and not session.deleted, (
        "unique_album_id: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    session.commit()
    _begin_exclusive(session, _ALBUM_ID_LOCK_ID)
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
    """Raise 400 if demoting/deactivating the last active admin.

    Uses SELECT ... FOR UPDATE on PostgreSQL to serialize concurrent
    admin role changes and prevent racing to zero admins.
    """
    query = session.query(User).filter_by(role="admin", is_active=True)
    if session.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    admin_count = query.count()
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


# ── Pagination ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageParams:
    offset: int
    limit: int


def _page_params(
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_DEFAULT_LIMIT, ge=1, le=PAGE_MAX_LIMIT),
) -> PageParams:
    return PageParams(offset=offset, limit=limit)


def _admin_page_params(
    offset: int = Query(0, ge=0),
    limit: int = Query(PAGE_ADMIN_DEFAULT_LIMIT, ge=1, le=PAGE_ADMIN_MAX_LIMIT),
) -> PageParams:
    return PageParams(offset=offset, limit=limit)


Pagination = Annotated[PageParams, Depends(_page_params)]
AdminPagination = Annotated[PageParams, Depends(_admin_page_params)]
