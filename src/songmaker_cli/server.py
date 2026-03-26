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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.app_context import AppContext, get_db_session
from songmaker_cli.config import find_project_root
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
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://api.anthropic.com; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        is_https = request.url.scheme == "https"
        if not is_https:
            ctx: AppContext = request.app.state.ctx
            direct_ip = request.client.host if request.client else ""
            if ctx.trusted_proxies and direct_ip in ctx.trusted_proxies:
                is_https = request.headers.get("x-forwarded-proto", "") == "https"
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        import structlog

        structlog.contextvars.clear_contextvars()

        from songmaker_cli.auth import get_client_ip
        ctx: AppContext = request.app.state.ctx
        direct_ip = request.client.host if request.client else "unknown"
        ip = get_client_ip(direct_ip, request.headers.get("x-forwarded-for"), ctx.trusted_proxies)

        structlog.contextvars.bind_contextvars(
            ip=ip, method=request.method, path=request.url.path,
        )

        start = datetime.now(timezone.utc)
        response = await call_next(request)
        duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
        log.info(
            "ACCESS %s %s %s %d (%.0fms)",
            ip, request.method, request.url.path,
            response.status_code, duration_ms,
        )
        return response


_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


_FORM_CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
})


_LOCALHOST_PATTERN = re.compile(r"^(localhost|127\.0\.0\.1)(:\d+)?$")


_CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login", "/api/auth/setup"})


class CsrfTokenMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF defense-in-depth.

    Mutating /api/ requests must include an X-CSRF-Token header whose value
    matches the csrf_token cookie. Login and setup are exempt (they issue
    the token). The token is set as a non-HttpOnly cookie so the frontend
    JS can read and echo it back.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if (
            request.method in _MUTATING_METHODS
            and request.url.path.startswith("/api/")
            and request.url.path not in _CSRF_EXEMPT_PATHS
        ):
            from songmaker_cli.auth import CSRF_HEADER, verify_csrf_token, verify_session_cookie
            from songmaker_cli.middleware import SESSION_COOKIE

            ctx: AppContext = request.app.state.ctx
            header_token = request.headers.get(CSRF_HEADER)
            if not header_token:
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"}, status_code=403,
                )
            raw_cookie = request.cookies.get(SESSION_COOKIE)
            secret = ctx.session_secret
            session_id = verify_session_cookie(raw_cookie, secret) if raw_cookie else None
            if not session_id or not verify_csrf_token(header_token, session_id, secret):
                return JSONResponse(
                    {"detail": "CSRF token missing or invalid"}, status_code=403,
                )
        return await call_next(request)


def _is_allowed_host(
    netloc: str,
    exact: frozenset[str],
    patterns: list[re.Pattern[str]],
) -> bool:
    if exact or patterns:
        if netloc in exact:
            return True
        return any(p.match(netloc) for p in patterns)
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
                ctx: AppContext = request.app.state.ctx
                parsed = urlparse(origin)
                origin_host = parsed.netloc
                if origin_host and not _is_allowed_host(
                    origin_host, ctx.allowed_hosts_exact, ctx.allowed_hosts_patterns,
                ):
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


REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT", 30))

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
        ctx: AppContext = request.app.state.ctx
        direct_ip = request.client.host if request.client else "unknown"
        ip = get_client_ip(direct_ip, request.headers.get("x-forwarded-for"), ctx.trusted_proxies)
        if not self._limiter.is_allowed(ip):
            return JSONResponse(
                {"detail": "Too many requests"}, status_code=429,
                headers={"Retry-After": str(IP_RATE_WINDOW)},
            )
        return await call_next(request)


def parse_allowed_hosts() -> tuple[frozenset[str], list[re.Pattern[str]]]:
    """Parse ALLOWED_HOSTS env into exact matches and wildcard patterns."""
    raw = os.environ.get("ALLOWED_HOSTS", "")
    exact: set[str] = set()
    patterns: list[re.Pattern[str]] = []
    for h in raw.split(","):
        h = h.strip()
        if not h:
            continue
        if h.startswith("*."):
            suffix = re.escape(h[2:])
            patterns.append(re.compile(rf"^[^:]+\.{suffix}(:\d+)?$"))
        else:
            exact.add(h)
    return frozenset(exact), patterns


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    from songmaker_cli.db.queries import cleanup_old_login_attempts, delete_expired_sessions

    ctx: AppContext = app.state.ctx
    with ctx.db() as session:
        deleted = delete_expired_sessions(session)
        if deleted:
            log.info("Startup: cleaned up %d expired sessions", deleted)
        pruned = cleanup_old_login_attempts(session)
        if pruned:
            log.info("Startup: pruned %d old login attempts", pruned)
        session.commit()
    yield
    if ctx.gpu_queue:
        log.info("Shutting down GPU queue...")
        ctx.gpu_queue.shutdown()


def create_app(
    output_dir: Path, project_root: Path,
    ctx: AppContext | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Songmaker",
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=_lifespan,
    )

    if ctx is None:
        from songmaker_cli.auth import ensure_session_secret, parse_trusted_proxies
        from songmaker_cli.db.engine import init_db
        from songmaker_cli.gpu_queue import GpuQueue

        db_factory = init_db(output_dir / DB_FILENAME)
        secret = ensure_session_secret(output_dir)
        hosts_exact, hosts_patterns = parse_allowed_hosts()
        gpu_q = GpuQueue(db_factory)

        ctx = AppContext(
            db=db_factory,
            output_dir=output_dir,
            session_secret=secret.encode(),
            trusted_proxies=parse_trusted_proxies(),
            allowed_hosts_exact=hosts_exact,
            allowed_hosts_patterns=hosts_patterns,
            gpu_queue=gpu_q,
        )
        gpu_q.start()

    app.state.ctx = ctx

    # Middleware execution order (Starlette LIFO — last added runs first):
    #   1. BodySizeLimitMiddleware  — reject oversized bodies before processing
    #   2. IpRateLimitMiddleware    — rate-limit before auth/CSRF to bound cost
    #   3. CsrfOriginMiddleware     — reject cross-origin state-changing requests
    #   4. CsrfTokenMiddleware      — verify double-submit CSRF token
    #   5. AccessLogMiddleware       — log all requests (after security checks)
    #   6. SecurityHeadersMiddleware — add security headers to responses
    # WARNING: reordering these lines changes security behavior.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CsrfTokenMiddleware)
    app.add_middleware(CsrfOriginMiddleware)
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)

    cors_origin = os.environ.get("CORS_ORIGIN")
    cors_kwargs: dict = {
        "allow_methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Cookie", "X-CSRF-Token"],
        "allow_credentials": True,
    }
    if cors_origin and "*" in cors_origin:
        if not re.match(
            r"^\*\.[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,}$",
            cors_origin,
        ):
            raise ValueError(
                f"Invalid CORS_ORIGIN wildcard: {cors_origin!r}. "
                "Must be *.domain.tld (e.g., *.example.com, *.trycloudflare.com)"
            )
        suffix = re.escape(cors_origin[2:])
        cors_kwargs["allow_origin_regex"] = rf"^https?://[^:/]+\.{suffix}$"
    elif cors_origin:
        cors_kwargs["allow_origins"] = [cors_origin]
    else:
        cors_kwargs["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:(8080|5173))?$"
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError,
    ) -> JSONResponse:
        fields = sorted({
            ".".join(str(loc) for loc in e["loc"]) for e in exc.errors()
        })
        return JSONResponse(
            {"detail": f"Validation error on: {', '.join(fields)}"},
            status_code=422,
        )

    from songmaker_cli.api import router as api_router

    app.include_router(api_router)

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

        from songmaker_cli.db.queries import get_album as get_album_query

        db_album = get_album_query(db, album)
        if not db_album:
            raise HTTPException(404, "Audio file not found")
        if user.role != "admin" and db_album.created_by != user.id:
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


def _load_env_file(project_root: Path) -> None:
    """Load .server.env if it exists, without overriding existing env vars."""
    from dotenv import load_dotenv

    env_file = project_root / ".server.env"
    if not env_file.exists():
        return
    load_dotenv(env_file, override=False)
    log.info("Loaded env from %s", env_file)


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

    _load_env_file(project_root)

    from songmaker_cli.logging_config import configure_logging
    configure_logging()

    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    app = create_app(output_dir, project_root)
    log.info("Songmaker server: http://localhost:%d", port)
    log.info("Auth enabled (session-based)")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    host = os.environ.get("HOST", "127.0.0.1")
    workers = int(os.environ.get("UVICORN_WORKERS", 1))
    if workers > 1:
        raise ValueError(
            f"UVICORN_WORKERS={workers} is unsupported. "
            "SQLite and the in-memory GPU queue require a single worker process. "
            "Use workers=1 (default)."
        )
    uvicorn.run(
        app, host=host, port=port, log_level="info",
        timeout_keep_alive=REQUEST_TIMEOUT_SECONDS,
    )
