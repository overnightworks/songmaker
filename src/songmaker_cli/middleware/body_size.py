"""Raw ASGI middleware: reject requests exceeding the body size limit."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from songmaker_cli.settings import get_settings


class _BodyTooLarge(Exception):
    pass


def is_reimport_path(path: str) -> bool:
    return path.endswith("/reimport")


def is_large_upload_path(path: str) -> bool:
    if path == "/api/audio/upload":
        return True
    parts = path.split("/")
    return (
        len(parts) == 5
        and parts[1] == "api"
        and parts[2] == "loras"
        and parts[4] == "samples"
    )


def body_limit_for_path(path: str) -> int:
    settings = get_settings()
    if is_reimport_path(path):
        return settings.max_reimport_body_bytes
    if is_large_upload_path(path):
        return settings.max_upload_body_bytes
    return settings.max_request_body_bytes


class BodySizeLimitMiddleware:
    def __init__(self, app):  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit = body_limit_for_path(path)

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
