"""Authenticated per-user resource invalidation stream."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from songmaker_cli.api_models.resource_events import (
    GenerationCreatedEvent,
    ResourceHeartbeatEvent,
    ResourceHelloEvent,
    ResourceResyncEvent,
)
from songmaker_cli.app_context import AppContext, get_app_context
from songmaker_cli.constants import (
    LAST_EVENT_ID_INVALID,
    RESOURCE_EVENT_HEARTBEAT_SECONDS,
    RESOURCE_EVENT_KIND_GENERATION_CREATED,
    RESOURCE_EVENT_POLL_SECONDS,
    RESOURCE_EVENT_TYPE_HEARTBEAT,
    RESOURCE_EVENT_TYPE_HELLO,
    RESOURCE_EVENT_TYPE_RESYNC,
    SSE_MEDIA_TYPE,
)
from songmaker_cli.db.queries.resource_events import (
    get_oldest_retained_sequence,
    get_user_high_water_mark,
    has_retention_gap,
    list_user_events_after,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

router = APIRouter()

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def parse_last_event_id(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    if not raw.isdigit():
        raise HTTPException(400, LAST_EVENT_ID_INVALID)
    return int(raw)


def format_sse(event: str, payload: dict, event_id: int | None = None) -> str:
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(payload)}")
    return "\n".join(lines) + "\n\n"


@router.get("/resource-events/stream")
async def api_stream_resource_events(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    ctx: AppContext = Depends(get_app_context),
) -> StreamingResponse:
    last_event_id = parse_last_event_id(request.headers.get("last-event-id"))
    with ctx.db() as session:
        high_water_mark = get_user_high_water_mark(session, user.id)
        oldest = get_oldest_retained_sequence(session, user.id)
    return StreamingResponse(
        _resource_event_generator(
            ctx, user.id, last_event_id, high_water_mark, oldest,
        ),
        media_type=SSE_MEDIA_TYPE,
        headers=_SSE_HEADERS,
    )


async def _resource_event_generator(
    ctx: AppContext,
    user_id: str,
    last_event_id: int | None,
    high_water_mark: int,
    oldest: int | None,
) -> AsyncGenerator[str, None]:
    yield format_sse(
        RESOURCE_EVENT_TYPE_HELLO,
        ResourceHelloEvent(high_water_mark=high_water_mark).model_dump(),
    )
    if last_event_id is None:
        cursor = high_water_mark
    elif has_retention_gap(last_event_id, oldest, high_water_mark):
        yield format_sse(
            RESOURCE_EVENT_TYPE_RESYNC,
            ResourceResyncEvent(high_water_mark=high_water_mark).model_dump(),
            event_id=high_water_mark,
        )
        cursor = high_water_mark
    else:
        cursor = last_event_id

    last_heartbeat = time.monotonic()
    try:
        while True:
            with ctx.db() as db_session:
                events = list_user_events_after(db_session, user_id, cursor)
            for event in events:
                payload = GenerationCreatedEvent.from_orm(event)
                yield format_sse(
                    RESOURCE_EVENT_KIND_GENERATION_CREATED,
                    payload.model_dump(),
                    event_id=event.sequence,
                )
                cursor = event.sequence
                last_heartbeat = time.monotonic()
            now = time.monotonic()
            if now - last_heartbeat >= RESOURCE_EVENT_HEARTBEAT_SECONDS:
                yield format_sse(
                    RESOURCE_EVENT_TYPE_HEARTBEAT,
                    ResourceHeartbeatEvent().model_dump(),
                )
                last_heartbeat = now
            await asyncio.sleep(RESOURCE_EVENT_POLL_SECONDS)
    except asyncio.CancelledError:
        return
