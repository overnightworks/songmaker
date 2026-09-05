"""Shared helpers for API endpoint modules."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, NoReturn
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Query, Request
from slugify import slugify as _slugify
from sqlalchemy import text
from sqlalchemy.orm import Session

from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.audio_paths import AudioFileNotFoundError
from songmaker_cli.auth import (
    RATE_LIMIT_WINDOW_SECONDS,
    ROLE_ADMIN,
)
from songmaker_cli.constants import (
    AUDIO_FILE_NOT_FOUND,
    HTTP_NOT_FOUND,
    LIBRARY_QUERY_REQUIRED,
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
    LimiterFailurePolicy,
)
from songmaker_cli.db.models import (
    ALBUM_SLUG_MAX_LENGTH,
    LORA_SLUG_MAX_LENGTH,
    PLAYLIST_SLUG_MAX_LENGTH,
    SONG_SLUG_MAX_LENGTH,
    Album,
    Generation,
    Job,
    Playlist,
    Song,
    User,
    UserLora,
    UserLoraSample,
)
from songmaker_cli.db.queries import (
    count_total_queued_jobs,
    count_user_active_jobs,
    count_user_jobs_in_window,
    create_job,
    get_album,
    get_generation,
    get_song,
    list_worker_identities,
    recover_stale_jobs_by_age_and_type,
    resolve_rate_limit,
)
from songmaker_cli.middleware import AuthenticatedUser
from songmaker_cli.redis_client import RedisRateLimiter
from songmaker_cli.settings import get_settings
from songmaker_cli.worker_liveness import read_worker_liveness

if TYPE_CHECKING:
    from redis import Redis

_RATE_LIMIT_LOCK_ID = 1
_ALBUM_ID_LOCK_ID = 2
_LORA_SLUG_LOCK_ID = 3
_SESSION_CAP_LOCK_ID = 4
_SONG_SLUG_LOCK_ID = 5
_PLAYLIST_SLUG_LOCK_ID = 6
COVER_SUGGESTIONS_LOCK_ID = 7
_LORA_CAPACITY_LOCK_ID = 8

SONG_NOT_FOUND_DETAIL: Final = "Song not found"
LORA_NOT_FOUND_DETAIL: Final = "LoRA not found"
LORA_SAMPLE_NOT_FOUND_DETAIL: Final = "LoRA sample not found"
GENERATION_NOT_FOUND_DETAIL: Final = "Generation not found"

_UNBOUNDED_SLUG_LENGTH = 0
_SLUG_COUNTER_SUFFIX_BUDGET = 20
_SONG_SLUG_BASE_MAX_LENGTH = SONG_SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET
_PLAYLIST_SLUG_BASE_MAX_LENGTH = PLAYLIST_SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET
_ALBUM_SLUG_BASE_MAX_LENGTH = ALBUM_SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET
_LORA_SLUG_BASE_MAX_LENGTH = LORA_SLUG_MAX_LENGTH - _SLUG_COUNTER_SUFFIX_BUDGET


def raise_audio_file_http_error(
    error: AudioFileNotFoundError,
    *,
    public: bool,
) -> NoReturn:
    """Map a missing stored audio file at the caller's HTTP boundary."""
    detail = HTTP_NOT_FOUND if public else AUDIO_FILE_NOT_FOUND
    raise HTTPException(404, detail) from error


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


def lock_lora_capacity(session: Session) -> None:
    """Start the transaction that serializes voice creation and training enqueueing.

    Both capacity checks share one transaction-scoped advisory lock on
    PostgreSQL (and SQLite's test-only ``BEGIN IMMEDIATE`` fallback).  Like
    ``create_job_with_rate_limit``, commit the auth dependency's possible
    renewal/audit mutations before taking the lock; callers must not have
    made application mutations yet.
    """
    assert not session.new and not session.dirty and not session.deleted, (
        "lock_lora_capacity: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    session.commit()
    _begin_exclusive(session, _LORA_CAPACITY_LOCK_ID)


def check_redis_health(request) -> None:
    """Reject mutation requests when Redis is degraded (fail-closed)."""
    from songmaker_cli.constants import REDIS_DEGRADED_THRESHOLD
    from songmaker_cli.redis_client import SessionCache

    cache: SessionCache | None = getattr(request.app.state, "session_cache", None)
    if cache and cache.consecutive_failures >= REDIS_DEGRADED_THRESHOLD:
        raise HTTPException(503, "Service temporarily degraded — try again shortly")


_PUBLIC_BASE_URL_SCHEMES = frozenset({"http", "https"})

# A netloc urlsplit hands back verbatim even when it is nonsense: e.g.
# "http://https://host" splits into scheme="http", netloc="https:" -- a
# non-empty netloc that is not a host. Requiring the whole netloc to match a
# plain hostname (or bracketed IPv6) with an optional numeric port closes
# that gap; credentials ("user:pass@host") are rejected the same way, since
# a public base address has no business carrying any.
_PUBLIC_BASE_URL_HOSTNAME = (
    r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*"
)
_PUBLIC_BASE_URL_IPV6 = r"\[[0-9A-Fa-f:]+\]"
_PUBLIC_BASE_URL_NETLOC_RE = re.compile(
    rf"^(?:{_PUBLIC_BASE_URL_HOSTNAME}|{_PUBLIC_BASE_URL_IPV6})(?::[0-9]{{1,5}})?$",
)


def resolve_public_base_url() -> str:
    """The one owner of "what address am I reachable at from outside".

    Every share endpoint (album/song/generation/playlist) calls this instead
    of trusting ``request.base_url``. ``base_url`` reflects the scheme of the
    literal ASGI transport — always ``http`` behind a TLS-terminating proxy
    (Cloudflare Tunnel today), because ``run_server()`` intentionally runs
    uvicorn with ``proxy_headers=False`` (see #328 and ``auth.py``) so no
    second, unaudited trust decision rewrites it. A deployment's public
    address does not change per request, so there is nothing to negotiate at
    request time: it is validated configuration, the same way
    ``TRUSTED_PROXIES`` and ``ALLOWED_HOSTS`` are.

    Callers must call this *before* mutating anything: it is the first thing
    a share endpoint does, ahead of ``enable_*_sharing()`` and the commit
    that follows it, so a resource is never flipped public on a request that
    goes on to fail here (#339).

    Raises ``HTTPException(500)`` — named, not a half-built link — when
    ``PUBLIC_BASE_URL`` is unset, is not an absolute ``http(s)`` URL with a
    plain ``host[:port]``, or carries a path (a subdirectory deployment is
    not supported — silently dropping the path would build exactly the
    half-link this function exists to prevent). A query string or fragment
    is discarded rather than rejected: neither belongs in an origin, and
    dropping them is unambiguous, unlike a path.
    """
    raw = get_settings().public_base_url.strip()
    if not raw:
        raise HTTPException(
            500,
            "PUBLIC_BASE_URL is not configured — cannot build a share link "
            "without knowing the address this server is reachable at.",
        )
    parsed = urlsplit(raw)
    if parsed.scheme not in _PUBLIC_BASE_URL_SCHEMES or not _PUBLIC_BASE_URL_NETLOC_RE.match(
        parsed.netloc
    ):
        raise HTTPException(
            500,
            f"PUBLIC_BASE_URL={raw!r} is not an absolute http:// or https:// URL "
            "with a plain host[:port].",
        )
    if parsed.path not in ("", "/"):
        raise HTTPException(
            500,
            f"PUBLIC_BASE_URL={raw!r} carries a path ({parsed.path!r}). Configure "
            "the bare origin (scheme://host[:port]) — a subdirectory deployment "
            "is not supported here.",
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _job_type_rate_limits(job_type: JobType) -> tuple[int, int, str]:
    """Return (user_limit, admin_limit, db_setting_key) for a job type."""
    settings = get_settings()
    if job_type == JobType.GENERATE:
        return (
            settings.generation_rate_limit_user,
            settings.generation_rate_limit_admin,
            SETTING_GENERATION_RATE_LIMIT,
        )
    if job_type == JobType.SCORE:
        return (
            settings.scoring_rate_limit_user,
            settings.scoring_rate_limit_admin,
            SETTING_SCORING_RATE_LIMIT,
        )
    if job_type == JobType.CHAT:
        return (
            settings.chat_rate_limit_user,
            settings.chat_rate_limit_admin,
            SETTING_CHAT_RATE_LIMIT,
        )
    raise ValueError(f"Unknown job type for rate limiting: {job_type}")


_QUEUEABLE_JOB_TYPES = frozenset({JobType.GENERATE, JobType.SCORE})


def create_job_with_rate_limit(
    session: Session,
    user: AuthenticatedUser,
    job_type: JobType,
    song_id: str | None = None,
    *,
    redis: Redis,
) -> Job:
    """Atomically check rate limits and create a job under BEGIN IMMEDIATE.

    Prevents TOCTOU races where two concurrent requests both pass the rate
    limit check before either creates a job.

    Liveness is observed before the initial commit and exclusive write lock so
    Redis round trips do not extend the serialized section. The initial commit
    closes the implicit transaction opened by the auth
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
    worker_ids = [worker.id for worker in list_worker_identities(session)]
    worker_liveness = read_worker_liveness(redis, worker_ids)
    session.commit()
    _begin_exclusive(session)

    is_admin = user.role == ROLE_ADMIN
    settings = get_settings()
    max_queue_depth = resolve_rate_limit(
        session, user.id, SETTING_MAX_QUEUE_DEPTH, settings.max_queue_depth,
    )
    recover_stale_jobs_by_age_and_type(
        session,
        user_id=user.id,
        worker_liveness=worker_liveness,
        max_queue_depth=max_queue_depth,
    )

    if job_type in _QUEUEABLE_JOB_TYPES:
        if count_total_queued_jobs(session) >= max_queue_depth:
            session.rollback()
            raise HTTPException(429, "Queue is full. Try again later.")
        if not is_admin:
            max_active = resolve_rate_limit(
                session, user.id, SETTING_MAX_USER_ACTIVE_JOBS, settings.max_user_active_jobs,
            )
            if count_user_active_jobs(session, user.id, job_type) >= max_active:
                session.rollback()
                raise HTTPException(429, "You already have an active job. Wait for it to finish.")

    env_user, env_admin, setting_key = _job_type_rate_limits(job_type)
    env_default = env_admin if is_admin else env_user
    limit = resolve_rate_limit(session, user.id, setting_key, env_default)
    count = count_user_jobs_in_window(session, user.id, job_type, RATE_LIMIT_WINDOW_SECONDS)
    if count >= limit:
        session.rollback()
        raise HTTPException(429, f"Rate limit reached ({limit}/{job_type}s per hour).")

    return create_job(session, job_type, user_id=user.id, song_id=song_id)


def gen_params_to_json(params: BaseGenerationParams | None) -> dict | None:
    """Serialize a BaseGenerationParams to a JSON-storable dict, dropping
    None values. Returns ``None`` for an entirely-empty model so callers
    that gate on ``is None`` can distinguish "user didn't set anything"
    from "user explicitly cleared every field"."""
    if params is None:
        return None
    dumped = {k: v for k, v in params.model_dump().items() if v is not None}
    return dumped or None


def slugify(value: str, max_length: int = _UNBOUNDED_SLUG_LENGTH) -> str:
    """Turn a human title into a URL-safe slug, never empty."""
    return _slugify(value, max_length=max_length) or "untitled"


def _acquire_unique_slug(
    session: Session,
    caller: str,
    lock_id: int,
    base_slug: str,
    is_taken: Callable[[str], bool],
) -> str:
    """Serialize the search for a free slug, appending -2, -3, etc. if needed.

    Commits the current transaction before acquiring an exclusive lock, so
    the check-then-act sequence cannot interleave with a competing request.
    Same caveats as create_job_with_rate_limit — no prior uncommitted
    mutations besides auth-layer session renewal, because the commit() below
    would persist them unconditionally.
    """
    assert not session.new and not session.dirty and not session.deleted, (
        f"{caller}: session has uncommitted mutations — "
        "the commit() below would persist them unconditionally"
    )
    session.commit()
    _begin_exclusive(session, lock_id)
    candidate = base_slug
    counter = 1
    while is_taken(candidate):
        counter += 1
        candidate = f"{base_slug}-{counter}"
    return candidate


def unique_album_id(session: Session, title: str) -> str:
    """Find an album ID unique across all albums, including deleted ones."""
    def is_taken(candidate: str) -> bool:
        return get_album(session, candidate, include_deleted_rows=True) is not None

    base_slug = slugify(title, max_length=_ALBUM_SLUG_BASE_MAX_LENGTH)
    return _acquire_unique_slug(
        session, "unique_album_id", _ALBUM_ID_LOCK_ID, base_slug, is_taken,
    )


def unique_lora_slug(session: Session, user_id: str, name: str) -> str:
    """Find a LoRA slug unique within one user's LoRAs."""
    def is_taken(candidate: str) -> bool:
        return (
            session.query(UserLora)
            .filter(UserLora.user_id == user_id, UserLora.slug == candidate)
            .first()
        ) is not None

    base_slug = slugify(name, max_length=_LORA_SLUG_BASE_MAX_LENGTH)
    return _acquire_unique_slug(
        session, "unique_lora_slug", _LORA_SLUG_LOCK_ID, base_slug, is_taken,
    )


def unique_lora_slug_under_capacity_lock(
    session: Session, user_id: str, name: str,
) -> str:
    """Find a free LoRA slug while ``lock_lora_capacity`` is held.

    This deliberately does not acquire another lock or commit: creation must
    keep its slug choice and per-musician capacity check in one transaction.
    """
    base_slug = slugify(name, max_length=_LORA_SLUG_BASE_MAX_LENGTH)
    candidate = base_slug
    counter = 1
    while (
        session.query(UserLora)
        .filter(UserLora.user_id == user_id, UserLora.slug == candidate)
        .first()
        is not None
    ):
        counter += 1
        candidate = f"{base_slug}-{counter}"
    return candidate


def unique_song_slug(
    session: Session,
    album_id: str,
    title: str,
    exclude_song_id: str | None = None,
) -> str:
    """Derive a song slug from its title, unique within its album.

    The address is hierarchical, so /album/a/intro and /album/b/intro are
    different songs — uniqueness is scoped to album_id, never global.
    Soft-deleted songs keep holding their slug so a restore cannot collide
    with a song created in the meantime. Pass exclude_song_id when the song
    already owns a row, so a rename or a move does not collide with itself.
    """
    def is_taken(candidate: str) -> bool:
        query = (
            session.query(Song)
            .execution_options(include_deleted=True)
            .filter(Song.album_id == album_id, Song.slug == candidate)
        )
        if exclude_song_id is not None:
            query = query.filter(Song.id != exclude_song_id)
        return query.first() is not None

    base_slug = slugify(title, max_length=_SONG_SLUG_BASE_MAX_LENGTH)
    return _acquire_unique_slug(
        session, "unique_song_slug", _SONG_SLUG_LOCK_ID, base_slug, is_taken,
    )


def unique_playlist_slug(
    session: Session,
    title: str,
    exclude_playlist_id: str | None = None,
) -> str:
    """Derive a playlist slug from its title, unique across all playlists.

    Playlists have no album to scope by — like an album's own id, the slug
    is global (the album precedent from #268). Pass exclude_playlist_id when
    the playlist already owns a row, so a rename does not collide with itself.
    """
    def is_taken(candidate: str) -> bool:
        query = session.query(Playlist).filter(Playlist.slug == candidate)
        if exclude_playlist_id is not None:
            query = query.filter(Playlist.id != exclude_playlist_id)
        return query.first() is not None

    base_slug = slugify(title, max_length=_PLAYLIST_SLUG_BASE_MAX_LENGTH)
    return _acquire_unique_slug(
        session, "unique_playlist_slug", _PLAYLIST_SLUG_LOCK_ID, base_slug, is_taken,
    )


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
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    if user.role != ROLE_ADMIN:
        album = song.album
        if not album or album.created_by != user.id:
            raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    return song


def check_song_access_including_deleted(
    session: Session, song_id: str, user: AuthenticatedUser,
) -> Song:
    """Load a song (even soft-deleted) and verify ownership.

    Used by restore endpoints where the global filter would otherwise
    hide the soft-deleted row. The parent album is also loaded with
    include_deleted so cascade-deleted albums still pass ownership check.
    """
    song = get_song(session, song_id, include_deleted_rows=True)
    if not song:
        raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    if user.role != ROLE_ADMIN:
        album = get_album(session, song.album_id, include_deleted_rows=True)
        if not album or album.created_by != user.id:
            raise HTTPException(404, SONG_NOT_FOUND_DETAIL)
    return song


def check_lora_access(lora: UserLora | None, user: AuthenticatedUser) -> UserLora:
    if not lora:
        raise HTTPException(404, LORA_NOT_FOUND_DETAIL)
    if lora.user_id != user.id:
        raise HTTPException(404, LORA_NOT_FOUND_DETAIL)
    return lora


def check_lora_ready_for_generation(
    session: Session, user_lora_id: str | None, user: AuthenticatedUser,
) -> UserLora | None:
    """Validate a user_lora_id referenced by a generation request.

    Returns the LoRA row if ``user_lora_id`` is set and OK.
    Raises 404 if not owned / not found, 422 if deleted or not READY.
    Returns None when ``user_lora_id`` is None (no LoRA requested).
    """
    from songmaker_cli.constants import LoraStatus
    from songmaker_cli.db.queries import get_user_lora

    if not user_lora_id:
        return None
    lora = get_user_lora(session, user_lora_id, include_deleted_rows=True)
    if not lora:
        raise HTTPException(404, LORA_NOT_FOUND_DETAIL)
    if lora.user_id != user.id:
        raise HTTPException(404, LORA_NOT_FOUND_DETAIL)
    if lora.deleted_at is not None:
        raise HTTPException(422, "LoRA is deleted")
    if lora.status != LoraStatus.READY:
        raise HTTPException(
            422, f"LoRA is not ready (status={lora.status})",
        )
    return lora


def check_lora_sample_access(
    sample: UserLoraSample | None, user: AuthenticatedUser,
) -> UserLoraSample:
    if not sample:
        raise HTTPException(404, LORA_SAMPLE_NOT_FOUND_DETAIL)
    parent = sample.user_lora
    if not parent:
        raise HTTPException(404, LORA_SAMPLE_NOT_FOUND_DETAIL)
    if parent.user_id != user.id:
        raise HTTPException(404, LORA_SAMPLE_NOT_FOUND_DETAIL)
    return sample


def check_generation_access(
    session: Session, gen_id: str, user: AuthenticatedUser,
) -> Generation:
    """Load a generation and verify ownership. Returns the generation or raises 404."""
    gen = get_generation(session, gen_id)
    if not gen:
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    if user.role != ROLE_ADMIN:
        album = gen.song.album if gen.song else None
        if not album or album.created_by != user.id:
            raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
    return gen


def check_own_generation_access(
    session: Session, gen_id: str, user: AuthenticatedUser,
) -> Generation:
    """Load a generation and require its album to belong to the caller.

    Unlike the general generation access helper, this intentionally does not
    grant administrators access to another musician's take. Callers use it
    where a take becomes private source material rather than an administrative
    resource.
    """
    gen = check_generation_access(session, gen_id, user)
    album = gen.song.album if gen.song else None
    if not album or album.created_by != user.id:
        raise HTTPException(404, GENERATION_NOT_FOUND_DETAIL)
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


# ── Rate limiting ────────────────────────────────────────────────────

def get_cached_limiter[LimiterT](
    request: Request,
    state_attr: str,
    build: Callable[[], LimiterT],
) -> LimiterT:
    """Return the limiter cached on ``request.app.state``, building it via
    ``build`` on first use.

    One limiter instance lives per FastAPI app process (cached on
    ``app.state`` rather than a module global, so tests that create a fresh
    app per case get a fresh limiter too), avoiding the Redis connection
    setup ``build`` does on every request.
    """
    limiter = getattr(request.app.state, state_attr, None)
    if limiter is None:
        limiter = build()
        setattr(request.app.state, state_attr, limiter)
    return limiter


def enforce_rate_limit(
    limiter: RedisRateLimiter,
    key: str,
    *,
    policy: LimiterFailurePolicy,
    reject_detail: str,
    retry_after_seconds: int,
    unavailable_log_message: str,
    unavailable_detail: str | None = None,
) -> None:
    """Check ``limiter.is_allowed(key)`` and enforce the result as a 429.

    ``policy`` names what happens when the limiter's Redis backend itself
    errors out: FAIL_OPEN logs and lets the request through, FAIL_CLOSED
    logs and rejects it with 503 (``unavailable_detail`` defaults to
    ``reject_detail`` if not given separately).
    """
    try:
        allowed = limiter.is_allowed(key)
    except Exception as exc:
        _log.warning(unavailable_log_message)
        if policy is LimiterFailurePolicy.FAIL_OPEN:
            return
        raise HTTPException(503, unavailable_detail or reject_detail) from exc
    if not allowed:
        raise HTTPException(
            429, reject_detail,
            headers={"Retry-After": str(retry_after_seconds)},
        )


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


def page_has_more(*, offset: int, fetched: int, total: int) -> bool:
    return offset + fetched < total


def parse_optional_search_query(q: str | None) -> str | None:
    if q is None:
        return None
    stripped = q.strip()
    if not stripped:
        raise HTTPException(422, LIBRARY_QUERY_REQUIRED)
    return stripped


def parse_required_search_query(q: str) -> str:
    stripped = q.strip()
    if not stripped:
        raise HTTPException(422, LIBRARY_QUERY_REQUIRED)
    return stripped
