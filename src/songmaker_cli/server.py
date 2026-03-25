"""Songmaker server — FastAPI backend for the web UI.

Serves the SvelteKit frontend, audio files, and REST API backed by SQLite.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.config import find_project_root, set_output_dir
from songmaker_cli.constants import OUTPUT_ROOT

log = logging.getLogger(__name__)

DB_FILENAME = "songmaker.db"


MAX_REQUEST_BODY_BYTES = int(os.environ.get("MAX_REQUEST_BODY_BYTES", 1_048_576))


class BodySizeLimitMiddleware:
    """Raw ASGI middleware: reject requests exceeding the body size limit.

    Checks Content-Length for fast rejection, then wraps the ASGI receive
    channel to track bytes as they stream in — aborting with 413 if the
    limit is exceeded, without buffering the entire body into memory first.
    """

    def __init__(self, app):  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in (
            (k.decode("latin-1"), v.decode("latin-1"))
            for k, v in scope.get("headers", [])
        )}
        cl = headers.get("content-length")
        if cl:
            try:
                if int(cl) > MAX_REQUEST_BODY_BYTES:
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
                if received > MAX_REQUEST_BODY_BYTES:
                    rejected = True
                    raise _BodyTooLarge
            return msg

        try:
            await self.app(scope, guarded_receive, send)
        except _BodyTooLarge:
            resp = JSONResponse({"detail": "Request body too large"}, status_code=413)
            await resp(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        forwarded = request.headers.get("x-forwarded-proto", "")
        if forwarded == "https" or request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = datetime.now()
        response = await call_next(request)
        ip = request.client.host if request.client else "unknown"
        log.info(
            "ACCESS %s %s %s %d (%.0fms)",
            ip, request.method, request.url.path,
            response.status_code,
            (datetime.now() - start).total_seconds() * 1000,
        )
        return response


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


_FORM_CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
})


ALLOWED_HOSTS: frozenset[str] = frozenset(
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
)

_LOCALHOST_PATTERN = re.compile(r"^(localhost|127\.0\.0\.1)(:\d+)?$")


def _is_allowed_host(netloc: str) -> bool:
    if ALLOWED_HOSTS:
        return netloc in ALLOWED_HOSTS
    return bool(_LOCALHOST_PATTERN.match(netloc))


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state-changing API requests as CSRF defense-in-depth.

    When Origin/Referer is present, verify it matches ALLOWED_HOSTS (env var)
    or localhost (default). When absent, reject requests with form-like
    Content-Types (the only types an HTML form can produce).
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if (
            request.method in _MUTATING_METHODS
            and request.url.path.startswith("/api/")
        ):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                from urllib.parse import urlparse
                parsed = urlparse(origin)
                origin_host = parsed.netloc
                if origin_host and not _is_allowed_host(origin_host):
                    return JSONResponse(
                        {"detail": "Cross-origin request rejected"},
                        status_code=403,
                    )
            else:
                content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
                if content_type in _FORM_CONTENT_TYPES:
                    return JSONResponse(
                        {"detail": "Missing Origin header on form submission"},
                        status_code=403,
                    )
        return await call_next(request)


IP_RATE_LIMIT = int(os.environ.get("IP_RATE_LIMIT", 120))
IP_RATE_WINDOW = 60


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    """Global per-IP rate limiter — defense against multi-account abuse."""

    def __init__(self, app, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(app, **kwargs)
        from songmaker_cli.middleware import IpRateLimiter
        self._limiter = IpRateLimiter(IP_RATE_LIMIT, IP_RATE_WINDOW)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        from songmaker_cli.auth import get_client_ip
        direct_ip = request.client.host if request.client else "unknown"
        ip = get_client_ip(direct_ip, request.headers.get("x-forwarded-for"))
        if not self._limiter.is_allowed(ip):
            return JSONResponse(
                {"detail": "Too many requests"}, status_code=429,
                headers={"Retry-After": str(IP_RATE_WINDOW)},
            )
        return await call_next(request)



@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.queries import cleanup_old_login_attempts, delete_expired_sessions

    factory = get_session_factory()
    with factory() as session:
        deleted = delete_expired_sessions(session)
        if deleted:
            log.info("Startup: cleaned up %d expired sessions", deleted)
        pruned = cleanup_old_login_attempts(session)
        if pruned:
            log.info("Startup: pruned %d old login attempts", pruned)
        session.commit()
    yield


def create_app(
    output_dir: Path, project_root: Path,
) -> FastAPI:
    app = FastAPI(
        title="Songmaker",
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=_lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CsrfOriginMiddleware)
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)

    cors_origin = os.environ.get("CORS_ORIGIN")
    cors_kwargs: dict = {
        "allow_methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Cookie"],
        "allow_credentials": True,
    }
    if cors_origin:
        cors_kwargs["allow_origins"] = [cors_origin]
    else:
        cors_kwargs["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    from songmaker_cli.api import router as api_router

    app.include_router(api_router)

    from songmaker_cli.db.engine import get_db_session
    from songmaker_cli.middleware import AuthenticatedUser, get_current_user

    @app.get("/audio/{album}/{filename}")
    async def get_audio(
        album: str, filename: str,
        user: AuthenticatedUser = Depends(get_current_user),
        db: Session = Depends(get_db_session),
    ) -> FileResponse:
        audio_path = (output_dir / album / filename).resolve()
        if not audio_path.is_relative_to(output_dir.resolve()):
            raise HTTPException(403, "Path traversal denied")
        if not audio_path.exists():
            raise HTTPException(404, "Audio file not found")

        if user.role != "admin":
            from songmaker_cli.db.queries import get_album as get_album_query

            db_album = get_album_query(db, album)
            if db_album and db_album.created_by != user.id:
                raise HTTPException(404, "Audio file not found")

        return FileResponse(audio_path, media_type="audio/mpeg")

    sveltekit_dir = project_root / "frontend" / "build"
    sveltekit_app_dir = sveltekit_dir / "_app"

    if sveltekit_app_dir.exists():
        app.mount(
            "/_app", StaticFiles(directory=str(sveltekit_app_dir)), name="sveltekit-app",
        )

    sk_index = sveltekit_dir / "index.html"

    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: HTTPException) -> FileResponse:
        if (
            not request.url.path.startswith("/api/")
            and not request.url.path.startswith("/audio/")
            and not request.url.path.startswith("/_app/")
            and sk_index.exists()
        ):
            return FileResponse(sk_index, media_type="text/html")
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return app


def run_server(
    output_dir: Path | None = None,
    project_root: Path | None = None,
    port: int = 8080,
    open_browser: bool = False,
) -> None:
    import uvicorn

    if project_root is None:
        project_root = find_project_root(Path.cwd()) or Path.cwd()
    if output_dir is None:
        output_dir = project_root / OUTPUT_ROOT

    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    from songmaker_cli.auth import ensure_session_secret
    from songmaker_cli.db.engine import init_db

    set_output_dir(output_dir)
    db_path = output_dir / DB_FILENAME
    init_db(db_path)
    ensure_session_secret(output_dir)

    app = create_app(output_dir, project_root)
    log.info("Songmaker server: http://localhost:%d", port)
    log.info("Auth enabled (session-based)")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")
