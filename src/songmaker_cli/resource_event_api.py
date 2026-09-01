"""Authenticated, replayable resource invalidation stream."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from songmaker_cli.api_helpers import get_cached_limiter
from songmaker_cli.api_models import (
    GenerationCreatedResourceEvent,
    ResourceHelloEvent,
    ResourceResyncEvent,
)
from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import (
    LAST_EVENT_ID_INVALID,
    POSTGRES_BIGINT_MAX,
    REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY,
    REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX,
    REDIS_RL_RESOURCE_STREAM_PREFIX,
    RESOURCE_EVENT_STREAM_CAPACITY_UNAVAILABLE,
    RESOURCE_EVENT_STREAM_CONNECTION_SECONDS,
    RESOURCE_EVENT_STREAM_LEASE_SECONDS,
    RESOURCE_EVENT_STREAM_LIMIT_DETAIL,
    RESOURCE_EVENT_STREAM_LIMITER_UNAVAILABLE,
    RESOURCE_EVENT_STREAM_MAX_GLOBAL,
    RESOURCE_EVENT_STREAM_MAX_PER_USER,
    RESOURCE_EVENT_STREAM_OPEN_WINDOW_SECONDS,
    RESOURCE_EVENT_STREAM_PAGE_SIZE,
    RESOURCE_EVENT_STREAM_PATH,
    RESOURCE_EVENT_STREAM_POLL_SECONDS,
    SSE_HEARTBEAT_COMMENT,
    SSE_HEARTBEAT_SECONDS,
    LimiterFailurePolicy,
    ResourceEventKind,
)
from songmaker_cli.db.queries import (
    get_oldest_resource_event_sequence,
    get_resource_event_high_water_mark,
    list_resource_events_after,
)
from songmaker_cli.middleware import get_current_user
from songmaker_cli.redis_client import RedisConcurrentLeaseLimiter, RedisRateLimiter
from songmaker_cli.settings import get_settings

router = APIRouter()
log = logging.getLogger(__name__)

_LEASE_RELEASE_TASKS: set[asyncio.Task[None]] = set()

_ROUTE_PATH = RESOURCE_EVENT_STREAM_PATH.removeprefix("/api")
_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "X-Accel-Buffering": "no",
}
_AHEAD_BIGINT_SENTINEL = POSTGRES_BIGINT_MAX + 1


@dataclass(frozen=True)
class ResourceEventPage:
    high_water_mark: int
    events: tuple[GenerationCreatedResourceEvent, ...]


def parse_last_event_id(raw: str | None) -> int | None:
    """Parse the browser cursor without overflowing PostgreSQL BIGINT."""
    if raw is None or raw == "":
        return None
    if not raw.isascii() or not raw.isdecimal():
        raise HTTPException(400, LAST_EVENT_ID_INVALID)

    canonical = raw.lstrip("0") or "0"
    max_bigint = str(POSTGRES_BIGINT_MAX)
    if len(canonical) > len(max_bigint) or (
        len(canonical) == len(max_bigint) and canonical > max_bigint
    ):
        return _AHEAD_BIGINT_SENTINEL
    return int(canonical)


def has_replay_gap(
    last_event_id: int,
    high_water_mark: int,
    oldest_retained: int | None,
) -> bool:
    return last_event_id > high_water_mark or (
        last_event_id < high_water_mark
        and (oldest_retained is None or last_event_id < oldest_retained - 1)
    )


def format_sse(event: str, payload: BaseModel, *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    data = json.dumps(payload.model_dump(mode="json"), separators=(",", ":"))
    lines.append(f"data: {data}")
    return "\n".join(lines) + "\n\n"


def _read_event_page(
    ctx: AppContext,
    user_id: str,
    cursor: int,
    through: int | None,
) -> ResourceEventPage:
    with ctx.db() as session:
        high_water_mark = get_resource_event_high_water_mark(session, user_id)
        upper_bound = high_water_mark if through is None else through
        events = list_resource_events_after(
            session,
            user_id,
            cursor,
            through=upper_bound,
            limit=RESOURCE_EVENT_STREAM_PAGE_SIZE,
        )
        payloads = tuple(GenerationCreatedResourceEvent.from_event(event) for event in events)
    return ResourceEventPage(high_water_mark=high_water_mark, events=payloads)


async def _read_event_page_before(
    ctx: AppContext,
    user_id: str,
    cursor: int,
    through: int | None,
    deadline: float,
) -> ResourceEventPage | None:
    remaining = deadline - monotonic()
    if remaining <= 0:
        return None
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_read_event_page, ctx, user_id, cursor, through),
            timeout=remaining,
        )
    except TimeoutError:
        return None


def _is_contiguous(
    events: tuple[GenerationCreatedResourceEvent, ...],
    cursor: int,
) -> bool:
    expected = cursor + 1
    for event in events:
        if int(event.sequence) != expected:
            return False
        expected += 1
    return True


async def _resource_event_generator(
    ctx: AppContext,
    user_id: str,
    last_event_id: int | None,
    high_water_mark: int,
    oldest_retained: int | None,
) -> AsyncGenerator[str, None]:
    deadline = monotonic() + RESOURCE_EVENT_STREAM_CONNECTION_SECONDS
    fresh = last_event_id is None
    yield format_sse(
        "hello",
        ResourceHelloEvent.from_high_water_mark(high_water_mark),
        event_id=high_water_mark if fresh else last_event_id,
    )

    cursor = high_water_mark if last_event_id is None else last_event_id
    replay_through = None if fresh else high_water_mark
    resync_sent = False
    last_emit = monotonic()

    if not fresh and has_replay_gap(cursor, high_water_mark, oldest_retained):
        if monotonic() >= deadline:
            return
        yield format_sse(
            "resync",
            ResourceResyncEvent.from_high_water_mark(high_water_mark),
            event_id=high_water_mark,
        )
        cursor = high_water_mark
        replay_through = None
        resync_sent = True
        last_emit = monotonic()

    while monotonic() < deadline:
        page = await _read_event_page_before(
            ctx,
            user_id,
            cursor,
            replay_through,
            deadline,
        )
        if page is None:
            return

        target_high = replay_through if replay_through is not None else page.high_water_mark
        gap_found = cursor < target_high and (
            not page.events or not _is_contiguous(page.events, cursor)
        )
        if gap_found:
            if resync_sent or monotonic() >= deadline:
                return
            yield format_sse(
                "resync",
                ResourceResyncEvent.from_high_water_mark(target_high),
                event_id=target_high,
            )
            cursor = target_high
            replay_through = None
            resync_sent = True
            last_emit = monotonic()
            continue

        if page.events:
            for event in page.events:
                if monotonic() >= deadline:
                    return
                yield format_sse(
                    ResourceEventKind.GENERATION_CREATED,
                    event,
                    event_id=int(event.sequence),
                )
                cursor = int(event.sequence)
                last_emit = monotonic()
            if replay_through is not None and cursor >= replay_through:
                replay_through = None
            continue

        if replay_through is not None:
            replay_through = None

        now = monotonic()
        if now >= deadline:
            return
        if now - last_emit >= SSE_HEARTBEAT_SECONDS:
            yield SSE_HEARTBEAT_COMMENT
            last_emit = monotonic()

        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(RESOURCE_EVENT_STREAM_POLL_SECONDS, remaining))


# The resource-event SSE stream fails closed: it holds a DB connection for
# its whole (long) lifetime, so an unenforced connection lease could starve
# the pool. Unlike the simple is_allowed limiters, this policy is enforced
# by _acquire_stream_lease's own try/except below (open-limiter check and
# lease acquisition share one failure path), not by api_helpers.enforce_rate_limit.
_STREAM_LEASE_FAILURE_POLICY = LimiterFailurePolicy.FAIL_CLOSED


def _get_open_limiter(request: Request) -> RedisRateLimiter:
    def _build() -> RedisRateLimiter:
        ctx: AppContext = request.app.state.ctx
        settings = get_settings()
        return RedisRateLimiter(
            ctx.redis,
            REDIS_RL_RESOURCE_STREAM_PREFIX,
            settings.resource_event_stream_open_limit,
            RESOURCE_EVENT_STREAM_OPEN_WINDOW_SECONDS,
        )
    return get_cached_limiter(request, "_resource_stream_open_limiter", _build)


def _get_lease_limiter(request: Request) -> RedisConcurrentLeaseLimiter:
    def _build() -> RedisConcurrentLeaseLimiter:
        ctx: AppContext = request.app.state.ctx
        settings = get_settings()
        pool_capacity = settings.database_pool_size + settings.database_max_overflow
        spare_capacity = pool_capacity - 1
        if spare_capacity <= 0:
            raise HTTPException(503, RESOURCE_EVENT_STREAM_CAPACITY_UNAVAILABLE)
        global_limit = min(RESOURCE_EVENT_STREAM_MAX_GLOBAL, spare_capacity)
        return RedisConcurrentLeaseLimiter(
            ctx.redis,
            scope_prefix=REDIS_RESOURCE_STREAM_LEASE_USER_PREFIX,
            global_key=REDIS_RESOURCE_STREAM_LEASE_GLOBAL_KEY,
            max_per_scope=min(RESOURCE_EVENT_STREAM_MAX_PER_USER, global_limit),
            max_global=global_limit,
            lease_seconds=RESOURCE_EVENT_STREAM_LEASE_SECONDS,
        )
    return get_cached_limiter(request, "_resource_stream_lease_limiter", _build)


def _acquire_stream_lease(
    request: Request,
    user_id: str,
) -> tuple[RedisConcurrentLeaseLimiter, str]:
    """Check the open-connection rate limit, then acquire a lease.

    Enforces ``_STREAM_LEASE_FAILURE_POLICY`` (FAIL_CLOSED): either the
    limiter itself erroring out, or the limiter deliberately saying no,
    rejects the request rather than letting an unmetered stream through.
    """
    try:
        if not _get_open_limiter(request).is_allowed(user_id):
            raise HTTPException(
                429,
                RESOURCE_EVENT_STREAM_LIMIT_DETAIL,
                headers={"Retry-After": str(RESOURCE_EVENT_STREAM_OPEN_WINDOW_SECONDS)},
            )
        limiter = _get_lease_limiter(request)
        token = limiter.acquire(user_id)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Resource stream limiter unavailable")
        raise HTTPException(503, RESOURCE_EVENT_STREAM_LIMITER_UNAVAILABLE) from exc
    if token is None:
        raise HTTPException(
            429,
            RESOURCE_EVENT_STREAM_LIMIT_DETAIL,
            headers={"Retry-After": "5"},
        )
    return limiter, token


async def _release_stream_lease(
    limiter: RedisConcurrentLeaseLimiter,
    user_id: str,
    lease_token: str,
) -> None:
    try:
        await asyncio.to_thread(limiter.release, user_id, lease_token)
    except Exception:
        log.warning("Resource stream lease release failed")


def _schedule_stream_lease_release(
    limiter: RedisConcurrentLeaseLimiter,
    user_id: str,
    lease_token: str,
) -> None:
    task = asyncio.create_task(_release_stream_lease(limiter, user_id, lease_token))
    _LEASE_RELEASE_TASKS.add(task)
    task.add_done_callback(_LEASE_RELEASE_TASKS.discard)


async def _leased_resource_event_generator(
    ctx: AppContext,
    limiter: RedisConcurrentLeaseLimiter,
    lease_token: str,
    user_id: str,
    last_event_id: int | None,
    high_water_mark: int,
    oldest_retained: int | None,
) -> AsyncGenerator[str, None]:
    try:
        async for frame in _resource_event_generator(
            ctx,
            user_id,
            last_event_id,
            high_water_mark,
            oldest_retained,
        ):
            yield frame
    finally:
        _schedule_stream_lease_release(limiter, user_id, lease_token)


@router.get(_ROUTE_PATH)
def api_stream_resource_events(request: Request) -> StreamingResponse:
    ctx: AppContext = request.app.state.ctx
    with ctx.db() as session:
        user = get_current_user(request, session)
        high_water_mark = get_resource_event_high_water_mark(session, user.id)
        oldest_retained = get_oldest_resource_event_sequence(session, user.id)
        session.commit()

    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    limiter, lease_token = _acquire_stream_lease(request, user.id)
    return StreamingResponse(
        _leased_resource_event_generator(
            ctx,
            limiter,
            lease_token,
            user.id,
            last_event_id,
            high_water_mark,
            oldest_retained,
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
