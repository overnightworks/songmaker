"""Job status, streaming, and cancellation API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import get_cached_limiter
from songmaker_cli.api_models import JobResponse
from songmaker_cli.app_context import AppContext, get_db_session
from songmaker_cli.auth import ROLE_ADMIN
from songmaker_cli.constants import (
    JOB_ACTIVE_STATUSES,
    JOB_STREAM_CONNECTION_SECONDS,
    JOB_STREAM_LEASE_SECONDS,
    JOB_STREAM_LIMIT_DETAIL,
    JOB_STREAM_LIMITER_UNAVAILABLE,
    JOB_TERMINAL_STATUSES,
    REDIS_JOB_STREAM_LEASE_GLOBAL_KEY,
    REDIS_JOB_STREAM_LEASE_USER_PREFIX,
    SSE_HEARTBEAT_COMMENT,
    SSE_HEARTBEAT_SECONDS,
    SSE_POLL_INTERVAL_SECONDS,
    AuditAction,
    JobStatus,
    LimiterFailurePolicy,
    ResourceType,
)
from songmaker_cli.db.models import Job
from songmaker_cli.db.queries import get_job, get_queue_position, record_audit, update_job_status
from songmaker_cli.middleware import AuthenticatedUser, get_current_user
from songmaker_cli.redis_client import RedisConcurrentLeaseLimiter
from songmaker_cli.settings import get_settings

router = APIRouter()
log = logging.getLogger(__name__)

_LEASE_RELEASE_TASKS: set[asyncio.Task[None]] = set()

# The job SSE stream fails closed, same as the resource-event stream's lease
# (see resource_event_api.py): an unenforced concurrency lease could let a
# runaway client open unbounded streams. Enforced by hand in
# _acquire_job_stream_lease's try/except below, not via api_helpers'
# enforce_rate_limit -- see that function's own docstring for why.
_JOB_STREAM_LEASE_FAILURE_POLICY = LimiterFailurePolicy.FAIL_CLOSED


@router.get(
    "/jobs/{job_id}",
    responses={404: {"description": "Job does not exist"}},
)
def api_get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    return JobResponse.from_orm(job, queue_position=get_queue_position(session, job))


@router.get(
    "/jobs/{job_id}/stream",
    responses={
        404: {"description": "Job does not exist"},
        429: {"description": "Too many open job streams"},
        503: {"description": "Job stream limiter is unavailable"},
    },
)
def api_stream_job(job_id: str, request: Request) -> StreamingResponse:
    # No `Depends()` at all here on purpose (#331 Findings 1/2, review
    # round 2, 2026-09-02): the first attempt only dropped
    # `Depends(get_db_session)` from this function's own signature, but
    # `Depends(get_current_user)` itself takes `Depends(get_db_session)` --
    # a yield dependency FastAPI keeps open until the whole *response* is
    # done, which for a StreamingResponse is the full stream lifetime. That
    # still pinned a pool connection one level up, and adding a second
    # short-lived session on top of the still-held one made a tight pool
    # (e.g. pool_size=1) fail admission outright.
    #
    # Fix: follow resource_event_api.py's api_stream_resource_events
    # exactly -- no request-scoped dependency at all. This is a plain
    # (non-async) `def`, so FastAPI thread-offloads the whole handler body
    # (unlike an `async def`, whose body runs directly on the loop); auth
    # and the access check run as plain function calls against ONE
    # short-lived `ctx.db()` session that closes before the lease is
    # acquired or the StreamingResponse is even constructed -- nothing left
    # tied to the response lifecycle holds a connection.
    ctx: AppContext = request.app.state.ctx
    with ctx.db() as session:
        user = get_current_user(request, session)
        _check_job_access(session, job_id, user)
        session.commit()
    limiter, lease_token = _acquire_job_stream_lease(request, user.id)
    return StreamingResponse(
        _leased_job_event_generator(ctx, limiter, lease_token, user.id, job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _fetch_job_response(ctx: AppContext, job_id: str) -> JobResponse | None:
    """Synchronous DB read for one poll -- always run via asyncio.to_thread.

    #331 Finding 2: this used to run directly on the event loop once per
    second per open stream (psycopg2 is blocking), so N waiting generations
    meant N blocking round trips per second on the loop, and an exhausted
    connection pool could stall it for up to 30s. asyncio.to_thread() moves
    the blocking call off the loop, matching resource_event_api.py's
    _read_event_page/_read_event_page_before split. Opens and closes its
    own session (never Depends(get_db_session) -- see api_stream_job), so
    no connection is held between polls or across the sleep.
    """
    with ctx.db() as db_session:
        job = get_job(db_session, job_id)
        if not job:
            return None
        return JobResponse.from_orm(
            job,
            queue_position=get_queue_position(db_session, job),
        )


async def _fetch_job_response_before(
    ctx: AppContext, job_id: str, deadline: float,
) -> JobResponse | None:
    """Bound one poll to the remaining stream lifetime.

    #331 Finding 2 (review 2026-09-01): a bare `await
    asyncio.to_thread(_fetch_job_response, ...)` can still block past the
    stream's own deadline if it starts right before the wall and then waits
    on an exhausted DB pool (up to `pool_timeout`, 30s) -- a 60s deadline
    could become 90s. Wrapping it in `asyncio.wait_for(remaining)` bounds
    it the same way resource_event_api.py's `_read_event_page_before` does;
    a timeout here returns None and the generator closes the stream, same
    as a job that has disappeared -- both cases want the connection closed
    so the frontend's already-handled EventSource reconnect picks it back
    up.
    """
    remaining = deadline - monotonic()
    if remaining <= 0:
        return None
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_job_response, ctx, job_id),
            timeout=remaining,
        )
    except TimeoutError:
        return None


async def _job_event_generator(ctx: AppContext, job_id: str) -> AsyncGenerator[str, None]:
    previous_status: str | None = None
    previous_progress: float | None = None
    previous_queue_reason: str | None = None
    previous_queue_position: int | None = None
    deadline = monotonic() + JOB_STREAM_CONNECTION_SECONDS
    last_emit = monotonic()
    while monotonic() < deadline:
        response = await _fetch_job_response_before(ctx, job_id, deadline)
        if response is None:
            return

        status_changed = (
            response.status != previous_status
            or response.progress != previous_progress
            or response.queue_reason != previous_queue_reason
            or response.queue_position != previous_queue_position
        )
        if status_changed:
            previous_status = response.status
            previous_progress = response.progress
            previous_queue_reason = response.queue_reason
            previous_queue_position = response.queue_position
            yield f"data: {json.dumps(response.model_dump())}\n\n"
            last_emit = monotonic()
        elif monotonic() - last_emit >= SSE_HEARTBEAT_SECONDS:
            yield SSE_HEARTBEAT_COMMENT
            last_emit = monotonic()

        if response.status in JOB_TERMINAL_STATUSES:
            return

        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(SSE_POLL_INTERVAL_SECONDS, remaining))


def _get_job_stream_lease_limiter(request: Request) -> RedisConcurrentLeaseLimiter:
    def _build() -> RedisConcurrentLeaseLimiter:
        ctx: AppContext = request.app.state.ctx
        settings = get_settings()
        return RedisConcurrentLeaseLimiter(
            ctx.redis,
            scope_prefix=REDIS_JOB_STREAM_LEASE_USER_PREFIX,
            global_key=REDIS_JOB_STREAM_LEASE_GLOBAL_KEY,
            max_per_scope=settings.job_stream_lease_max_per_user,
            max_global=settings.job_stream_lease_max_global,
            lease_seconds=JOB_STREAM_LEASE_SECONDS,
        )
    return get_cached_limiter(request, "_job_stream_lease_limiter", _build)


def _acquire_job_stream_lease(
    request: Request,
    user_id: str,
) -> tuple[RedisConcurrentLeaseLimiter, str]:
    try:
        limiter = _get_job_stream_lease_limiter(request)
        token = limiter.acquire(user_id)
    except Exception as exc:
        log.warning("Job stream limiter unavailable")
        raise HTTPException(503, JOB_STREAM_LIMITER_UNAVAILABLE) from exc
    if token is None:
        raise HTTPException(
            429,
            JOB_STREAM_LIMIT_DETAIL,
            headers={"Retry-After": "5"},
        )
    return limiter, token


async def _release_job_stream_lease(
    limiter: RedisConcurrentLeaseLimiter,
    user_id: str,
    lease_token: str,
) -> None:
    try:
        await asyncio.to_thread(limiter.release, user_id, lease_token)
    except Exception:
        log.warning("Job stream lease release failed")


def _schedule_job_stream_lease_release(
    limiter: RedisConcurrentLeaseLimiter,
    user_id: str,
    lease_token: str,
) -> None:
    task = asyncio.create_task(_release_job_stream_lease(limiter, user_id, lease_token))
    _LEASE_RELEASE_TASKS.add(task)
    task.add_done_callback(_LEASE_RELEASE_TASKS.discard)


async def _leased_job_event_generator(
    ctx: AppContext,
    limiter: RedisConcurrentLeaseLimiter,
    lease_token: str,
    user_id: str,
    job_id: str,
) -> AsyncGenerator[str, None]:
    try:
        async for frame in _job_event_generator(ctx, job_id):
            yield frame
    finally:
        _schedule_job_stream_lease_release(limiter, user_id, lease_token)


@router.post(
    "/jobs/{job_id}/cancel",
    responses={
        404: {"description": "Job does not exist"},
        409: {"description": "Job is not queued or running"},
    },
)
def api_cancel_job(
    job_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> JobResponse:
    job = _check_job_access(session, job_id, user)
    if job.status not in JOB_ACTIVE_STATUSES:
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    if not update_job_status(session, job_id, JobStatus.CANCELLED):
        raise HTTPException(409, "Only queued or running jobs can be cancelled")
    record_audit(session, user.id, AuditAction.CANCEL, ResourceType.JOB, job_id)
    session.commit()
    from songmaker_cli.cover_runner import abort_web_cover_job

    abort_web_cover_job(request.app, job_id)
    job = get_job(session, job_id)
    return JobResponse.from_orm(job)


def _check_job_access(session: Session, job_id: str, user: AuthenticatedUser) -> Job:
    job = get_job(session, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if user.role != ROLE_ADMIN and job.user_id != user.id:
        raise HTTPException(404, "Job not found")
    return job
