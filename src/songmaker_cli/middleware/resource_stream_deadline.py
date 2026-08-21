"""Outer ASGI deadline for the authenticated resource-event stream."""

from __future__ import annotations

import asyncio

from songmaker_cli.constants import (
    RESOURCE_EVENT_STREAM_CONNECTION_SECONDS,
    RESOURCE_EVENT_STREAM_PATH,
)


class ResourceStreamDeadlineMiddleware:
    """Bound the complete ASGI exchange, including downstream proxy sends."""

    def __init__(
        self,
        app,
        deadline_seconds: float = RESOURCE_EVENT_STREAM_CONNECTION_SECONDS,
    ) -> None:
        self.app = app
        self.deadline_seconds = deadline_seconds

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") != RESOURCE_EVENT_STREAM_PATH:
            await self.app(scope, receive, send)
            return

        timeout = asyncio.timeout(self.deadline_seconds)
        try:
            async with timeout:
                await self.app(scope, receive, send)
        except TimeoutError:
            if not timeout.expired():
                raise
