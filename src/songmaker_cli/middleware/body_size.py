"""Raw ASGI middleware: reject requests exceeding the body size limit."""

from __future__ import annotations

import os

from fastapi.responses import JSONResponse

MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", 1_048_576))
MAX_UPLOAD_BODY_BYTES = int(os.environ.get("MAX_UPLOAD_BODY_BYTES", 52_428_800))


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app):  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_upload = path.endswith("/reimport")
        limit = MAX_UPLOAD_BODY_BYTES if is_upload else MAX_REQUEST_BODY_BYTES

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
        rejected = False

        async def guarded_receive():  # type: ignore[no-untyped-def]
            nonlocal received, rejected
            msg = await receive()
            if msg.get("type") == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    rejected = True
                    raise _BodyTooLarge
            return msg

        try:
            await self.app(scope, guarded_receive, send)
        except _BodyTooLarge:
            resp = JSONResponse({"detail": "Request body too large"}, status_code=413)
            await resp(scope, receive, send)
