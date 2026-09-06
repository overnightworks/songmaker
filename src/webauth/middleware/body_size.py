"""Raw ASGI middleware: reject requests exceeding their body size budget."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from webauth.policies import BodySizePolicy


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Stop an oversized body at the door, and again while it streams in."""

    def __init__(self, app, policy: BodySizePolicy):  # type: ignore[no-untyped-def]
        self.app = app
        self._policy = policy

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._policy.max_bytes(scope.get("path", ""), scope.get("method", ""))

        headers = {k.lower(): v for k, v in (
            (k.decode("latin-1"), v.decode("latin-1"))
            for k, v in scope.get("headers", [])
        )}
        cl = headers.get("content-length")
        if cl:
            try:
                if int(cl) > limit:
                    resp = JSONResponse({"detail": "Request body too large"}, status_code=413)
                    await resp(scope, receive, send)
                    return
            except ValueError:
                pass

        received = 0

        async def guarded_receive():  # type: ignore[no-untyped-def]
            nonlocal received
            msg = await receive()
            if msg.get("type") == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return msg

        try:
            await self.app(scope, guarded_receive, send)
        except _BodyTooLarge:
            resp = JSONResponse({"detail": "Request body too large"}, status_code=413)
            await resp(scope, receive, send)
