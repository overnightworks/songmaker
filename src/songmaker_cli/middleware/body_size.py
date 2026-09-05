"""Raw ASGI middleware: reject requests exceeding the body size limit."""

from __future__ import annotations

from fastapi.responses import JSONResponse

from songmaker_cli.settings import get_settings


class _BodyTooLarge(Exception):
    pass


def is_large_upload_path(path: str, method: str = "POST") -> bool:
    if path == "/api/audio/upload":
        return True
    parts = path.split("/")
    if len(parts) != 5 or parts[1] != "api" or not parts[3]:
        return False
    resource = parts[2]
    action = parts[4]
    if resource == "loras" and action == "samples":
        return True
    if resource == "songs" and action == "reimport":
        return True
    if resource == "albums" and action == "cover" and method.upper() == "POST":
        return True
    if resource == "playlists" and action == "cover" and method.upper() == "POST":
        return True
    if resource == "songs" and action == "cover":
        return True
    return False


def body_limit_for_path(path: str, method: str = "POST") -> int:
    settings = get_settings()
    if not is_large_upload_path(path, method):
        return settings.max_request_body_bytes
    parts = path.split("/")
    action = parts[4] if len(parts) > 4 else ""
    if action == "cover":
        return settings.max_cover_upload_body_bytes
    if action == "reimport":
        return settings.max_reimport_body_bytes
    return settings.max_upload_body_bytes


class BodySizeLimitMiddleware:
    def __init__(self, app):  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit = body_limit_for_path(path, scope.get("method", ""))

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
