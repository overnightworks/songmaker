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
    def __init__(self, app: object, script_hash: str = "") -> None:
        super().__init__(app)
        script_src = "'self'"
        if script_hash:
            script_src += f" '{script_hash}'"
        self._csp = (
            "default-src 'none'; "
            f"script-src {script_src}; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://api.anthropic.com; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "font-src 'self'; "
            "frame-ancestors 'none'"
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = self._csp
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


class HttpMetrics:
    """Thread-safe in-memory HTTP request counters for /metrics."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._request_counts: dict[tuple[str, int], int] = {}
        self._total_duration_ms: float = 0.0
        self._total_requests: int = 0

    def record(self, method: str, status_code: int, duration_ms: float) -> None:
        key = (method, status_code)
        with self._lock:
            self._request_counts[key] = self._request_counts.get(key, 0) + 1
            self._total_duration_ms += duration_ms
            self._total_requests += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg_ms = (
                self._total_duration_ms / self._total_requests
                if self._total_requests > 0 else 0.0
            )
            return {
                "http_requests_total": dict(
                    {f"{m} {s}": c for (m, s), c in sorted(self._request_counts.items())}
                ),
                "http_requests_count": self._total_requests,
                "http_request_duration_avg_ms": round(avg_ms, 1),
            }


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

        http_metrics = getattr(request.app.state, "http_metrics", None)
        if http_metrics:
            http_metrics.record(request.method, response.status_code, duration_ms)

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
    host_without_port = netloc.rsplit(":", 1)[0] if ":" in netloc else netloc
    if exact or patterns:
        if netloc in exact or host_without_port in exact:
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


def _get_gpu_vram_mb() -> float | None:
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.memory_allocated() / 1024 / 1024, 1)
    except ImportError:
        pass
    return None


def _compute_script_hash(index_html: Path) -> str:
    if not index_html.exists():
        return ""
    import hashlib
    import re
    content = index_html.read_text()
    match = re.search(r"<script>(.*?)</script>", content, re.DOTALL)
    if not match:
        return ""
    import base64
    digest = hashlib.sha256(match.group(1).encode()).digest()
    return f"sha256-{base64.b64encode(digest).decode()}"


def _check_db(ctx: AppContext) -> bool:
    try:
        from sqlalchemy import text
        with ctx.db() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _picked_filename(song) -> str | None:  # type: ignore[no-untyped-def]
    picked = [g for g in song.generations if g.is_picked and not g.is_archived]
    if picked:
        return picked[0].mp3_path
    return None


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
    app.state.startup_time = datetime.now(timezone.utc)
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
    app.state.http_metrics = HttpMetrics()

    # Middleware execution order (Starlette LIFO — last added runs first):
    #   1. BodySizeLimitMiddleware  — reject oversized bodies before processing
    #   2. IpRateLimitMiddleware    — rate-limit before auth/CSRF to bound cost
    #   3. CsrfOriginMiddleware     — reject cross-origin state-changing requests
    #   4. CsrfTokenMiddleware      — verify double-submit CSRF token
    #   5. AccessLogMiddleware       — log all requests (after security checks)
    #   6. SecurityHeadersMiddleware — add security headers to responses
    # WARNING: reordering these lines changes security behavior.
    script_hash = _compute_script_hash(project_root / "frontend" / "build" / "index.html")
    app.add_middleware(SecurityHeadersMiddleware, script_hash=script_hash)
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

    _metrics_cache: dict[str, object] = {}
    _metrics_cache_time: list[float] = [0.0]

    @app.get("/metrics")
    def metrics_endpoint(request: Request) -> JSONResponse:
        import time

        from songmaker_cli.constants import METRICS_CACHE_TTL_SECONDS

        now = time.monotonic()
        if now - _metrics_cache_time[0] < METRICS_CACHE_TTL_SECONDS and _metrics_cache:
            return JSONResponse(_metrics_cache)

        ctx: AppContext = request.app.state.ctx
        http_metrics: HttpMetrics = request.app.state.http_metrics

        from songmaker_cli.db.queries import job_counts_by_type_and_status, job_duration_stats
        with ctx.db() as session:
            jobs_by_type = job_counts_by_type_and_status(session)
            duration = job_duration_stats(session)

        gpu_vram_mb = _get_gpu_vram_mb()
        queue_depth = ctx.gpu_queue.queue_depth if ctx.gpu_queue else 0

        result: dict[str, object] = {
            "jobs_total": jobs_by_type,
            "jobs_active": sum(
                counts.get("queued", 0) + counts.get("running", 0)
                for counts in jobs_by_type.values()
            ),
            "job_duration_seconds": duration,
            "queue_depth": queue_depth,
            "gpu_vram_mb": gpu_vram_mb,
            **http_metrics.snapshot(),
        }

        _metrics_cache.clear()
        _metrics_cache.update(result)
        _metrics_cache_time[0] = now
        return JSONResponse(result)

    @app.get("/health")
    def health_check(request: Request) -> JSONResponse:
        ctx: AppContext = request.app.state.ctx
        startup_time: datetime = getattr(
            request.app.state, "startup_time", datetime.now(timezone.utc),
        )
        uptime = int((datetime.now(timezone.utc) - startup_time).total_seconds())

        db_ok = _check_db(ctx)
        gpu_running = bool(ctx.gpu_queue and ctx.gpu_queue.is_running)
        queue_depth = ctx.gpu_queue.queue_depth if ctx.gpu_queue else 0

        if ctx.gpu_queue:
            acestep_model = ctx.gpu_queue.active_model
            acestep = "healthy" if acestep_model is not None else (
                "healthy" if ctx.gpu_queue.acestep_healthy else "unhealthy"
            )
        else:
            acestep_model = None
            acestep = "unknown"

        degraded = not db_ok or (ctx.gpu_queue and not gpu_running)
        return JSONResponse({
            "status": "degraded" if degraded else "ok",
            "gpu_queue": "running" if gpu_running else "stopped",
            "queue_depth": queue_depth,
            "db": "ok" if db_ok else "error",
            "acestep": acestep,
            "acestep_model": acestep_model,
            "uptime_seconds": uptime,
        })

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

    from songmaker_cli.constants import SHARED_RATE_LIMIT, SHARED_RATE_WINDOW_SECONDS
    from songmaker_cli.middleware import IpRateLimiter

    shared_limiter = IpRateLimiter(SHARED_RATE_LIMIT, SHARED_RATE_WINDOW_SECONDS)

    def _check_shared_rate_limit(request: Request) -> None:
        from songmaker_cli.auth import get_client_ip
        ctx: AppContext = request.app.state.ctx
        direct_ip = request.client.host if request.client else "unknown"
        ip = get_client_ip(
            direct_ip,
            request.headers.get("x-forwarded-for"),
            ctx.trusted_proxies,
        )
        if not shared_limiter.is_allowed(ip):
            raise HTTPException(
                429, "Too many requests",
                headers={"Retry-After": str(SHARED_RATE_WINDOW_SECONDS)},
            )

    @app.get("/shared/{slug}")
    def get_shared_album(
        slug: str,
        request: Request,
        db: Session = Depends(get_db_session),
    ) -> JSONResponse:
        _check_shared_rate_limit(request)
        from songmaker_cli.api_models import SharedAlbumResponse, SharedSongItem
        from songmaker_cli.db.queries import get_album_by_slug

        album = get_album_by_slug(db, slug)
        if not album:
            raise HTTPException(404, "Not found")
        songs = sorted(album.songs, key=lambda s: s.track_number)
        base_url = str(request.base_url).rstrip("/")
        response = SharedAlbumResponse(
            title=album.title,
            artist=album.artist,
            subtitle=album.subtitle,
            year=album.year,
            songs=[
                SharedSongItem(
                    title=s.title,
                    track_number=s.track_number,
                    audio_url=(
                        f"{base_url}/shared/{slug}/audio/{_picked_filename(s)}"
                        if _picked_filename(s) else None
                    ),
                )
                for s in songs
            ],
        )
        return JSONResponse(response.model_dump())

    @app.get("/shared/{slug}/audio/{filename:path}")
    async def get_shared_audio(
        slug: str,
        filename: str,
        request: Request,
        db: Session = Depends(get_db_session),
    ) -> FileResponse:
        _check_shared_rate_limit(request)
        from songmaker_cli.db.queries import get_album_by_slug
        album = get_album_by_slug(db, slug)
        if not album:
            raise HTTPException(404, "Not found")

        valid_filenames = {
            _picked_filename(s)
            for s in album.songs
            if _picked_filename(s)
        }
        if filename not in valid_filenames:
            raise HTTPException(404, "Not found")

        audio_path = (output_dir / filename).resolve()
        if not audio_path.is_relative_to(output_dir.resolve()):
            raise HTTPException(403, "Path traversal denied")
        if not audio_path.exists():
            raise HTTPException(404, "Not found")
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
            and not request.url.path.startswith("/shared/")
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
