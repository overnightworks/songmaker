"""Outer ASGI deadline for the authenticated resource-event stream."""

from __future__ import annotations

import asyncio
from typing import Final

from songmaker_cli.constants import (
    RESOURCE_EVENT_STREAM_CONNECTION_SECONDS,
    RESOURCE_EVENT_STREAM_PATH,
)

_SYNTHETIC_TERMINAL_SEND_TIMEOUT_SECONDS: Final = 1.0


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
        response_started = False
        response_completed = False

        async def observed_send(message) -> None:
            nonlocal response_started, response_completed

            await send(message)
            if message["type"] == "http.response.start":
                response_started = True
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                response_completed = True

        try:
            async with timeout:
                await self.app(scope, receive, observed_send)
        except TimeoutError:
            if not timeout.expired():
                raise
            if not response_started or response_completed:
                return
            try:
                async with asyncio.timeout(_SYNTHETIC_TERMINAL_SEND_TIMEOUT_SECONDS):
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b"",
                            "more_body": False,
                        }
                    )
            except OSError:
                return
