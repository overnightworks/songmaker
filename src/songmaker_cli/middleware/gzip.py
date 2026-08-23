"""Raw ASGI middleware: gzip-compress API/HTML responses, never audio.

Starlette's `GZipMiddleware` decides purely from the `Accept-Encoding`
request header and the response size -- it has no notion of `Content-Type`.
Left unguarded, it would re-compress already-lossy-compressed audio bytes
(MP3/WAV served from `/audio/*`, the share routes' `.../audio/*`, and the
queue-stream `.../audio` endpoints), wasting CPU and adding latency for
zero size benefit. This module wraps it with a path check so those routes
bypass compression entirely.
"""

from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


def is_audio_response_path(path: str) -> bool:
    """True for endpoints that serve audio file bytes, not JSON/HTML.

    `/audio/{owner_id}/{filename}`, every `/shared/**/audio/{filename}`
    share route, and the `.../queue-streams/{id}/audio` endpoints all
    contain an `/audio/` segment or end in `/audio`. `/api/audio/upload`
    also matches; its response is a small JSON body, so skipping
    compression there is harmless, not incorrect.
    """
    return "/audio/" in path or path.endswith("/audio")


class SelectiveGZipMiddleware:
    """Gzip JSON/HTML responses; skip Starlette's GZipMiddleware for audio."""

    def __init__(self, app: ASGIApp, minimum_size: int) -> None:
        self.app = app
        self.gzip_app = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or is_audio_response_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        await self.gzip_app(scope, receive, send)
