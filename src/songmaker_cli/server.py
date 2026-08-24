"""Songmaker server -- FastAPI backend for the web UI.

Serves the SvelteKit frontend, audio files, and REST API backed by PostgreSQL.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from songmaker_cli.app_context import AppContext
from songmaker_cli.config import find_project_root
from songmaker_cli.constants import (
    APP_NAME,
    GZIP_COMPRESS_LEVEL,
    GZIP_MINIMUM_SIZE_BYTES,
    PWA_ICON_PATHS,
)
from songmaker_cli.health_api import _compute_script_hashes
from songmaker_cli.lifecycle import (
    auto_setup_admin,
    cleanup_expired_resource_events,
    reconcile_crashed_loras,
    resource_event_cleanup_loop,
    score_backfill_loop,
    session_sync_loop,
)
from songmaker_cli.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    CsrfOriginMiddleware,
    CsrfTokenMiddleware,
    IpRateLimitMiddleware,
    ResourceStreamDeadlineMiddleware,
    SecurityHeadersMiddleware,
    SelectiveGZipMiddleware,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)


def parse_allowed_hosts() -> tuple[frozenset[str], list[re.Pattern[str]]]:
    raw = get_settings().allowed_hosts
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
    from songmaker_cli.arq_pool import close_arq_pool, init_arq_pool
    from songmaker_cli.db.queries import cleanup_old_login_attempts, delete_expired_sessions
    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    ctx: AppContext = app.state.ctx
    cleanup_expired_queue_streams(ctx)
    with ctx.db() as session:
        deleted = delete_expired_sessions(session)
        if deleted:
            log.info("Startup: cleaned up %d expired sessions", deleted)
        pruned = cleanup_old_login_attempts(session)
        if pruned:
            log.info("Startup: pruned %d old login attempts", pruned)
        session.commit()

    auto_setup_admin(ctx)
    reconcile_crashed_loras(ctx)
    await asyncio.to_thread(cleanup_expired_resource_events, ctx)

    await init_arq_pool()
    log.info("arq pool connected")

    app.state.startup_time = datetime.now(timezone.utc)
    sync_task = asyncio.create_task(session_sync_loop(app))
    event_cleanup_task = asyncio.create_task(resource_event_cleanup_loop(app))
    score_backfill_task = asyncio.create_task(score_backfill_loop(app))
    try:
        yield
    finally:
        sync_task.cancel()
        event_cleanup_task.cancel()
        score_backfill_task.cancel()
        await asyncio.gather(
            sync_task, event_cleanup_task, score_backfill_task, return_exceptions=True,
        )
        await close_arq_pool()


def create_app(
    audio_dir: Path, data_dir: Path, project_root: Path,
    ctx: AppContext | None = None,
) -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=_lifespan,
    )

    if ctx is None:
        from songmaker_cli.auth import ensure_session_secret, parse_trusted_proxies
        from songmaker_cli.db.engine import init_db

        settings = get_settings()
        db_factory = init_db(settings.database_url)
        secret = ensure_session_secret(data_dir)
        hosts_exact, hosts_patterns = parse_allowed_hosts()

        redis_url = settings.redis_url
        from songmaker_cli.redis_client import create_redis
        redis_instance = create_redis(redis_url)

        from songmaker_cli.constants import REDIS_STARTUP_ERROR
        from songmaker_cli.redis_client import redis_health
        if not redis_health(redis_instance):
            redis_instance.close()
            raise RuntimeError(REDIS_STARTUP_ERROR.format(url=redis_url.split("@")[-1]))
        log.info("Redis connected: %s", redis_url.split("@")[-1])

        ctx = AppContext(
            db=db_factory,
            audio_dir=audio_dir,
            data_dir=data_dir,
            session_secret=secret.encode(),
            redis=redis_instance,
            trusted_proxies=parse_trusted_proxies(),
            allowed_hosts_exact=hosts_exact,
            allowed_hosts_patterns=hosts_patterns,
        )

    app.state.ctx = ctx
    from songmaker_cli.redis_client import RedisHttpMetrics, SessionCache
    app.state.http_metrics = RedisHttpMetrics(ctx.redis)
    app.state.session_cache = SessionCache(ctx.redis)

    # Middleware execution order (Starlette LIFO -- last added runs first):
    #   1. ResourceStreamDeadlineMiddleware -- bound the complete resource SSE exchange
    #   2. SelectiveGZipMiddleware    -- compress the finished response body
    #   3. CORS middleware            -- add configured cross-origin policy
    #   4. BodySizeLimitMiddleware    -- reject oversized bodies before processing
    #   5. IpRateLimitMiddleware      -- rate-limit before auth/CSRF to bound cost
    #   6. CsrfOriginMiddleware       -- reject cross-origin state-changing requests
    #   7. CsrfTokenMiddleware        -- verify double-submit CSRF token
    #   8. AccessLogMiddleware        -- log all requests (after security checks)
    #   9. SecurityHeadersMiddleware  -- add security headers to responses
    # WARNING: reordering these lines changes security behavior.
    # SelectiveGZipMiddleware sits just inside ResourceStreamDeadlineMiddleware
    # (the true outermost layer) and outside everything else, on purpose:
    #   - It only inspects the outgoing Accept-Encoding/Content-Type/status
    #     pair and never reads or rejects the request, so its placement
    #     cannot affect the auth/CSRF/rate-limit checks below -- those
    #     already ran and could already reject the request before this
    #     middleware's compression step ever executes.
    #   - Being outside CORS/BodySize/RateLimit/CSRF/AccessLog/SecurityHeaders
    #     means it compresses the fully-assembled response (every other
    #     middleware's headers already set) exactly once, not an
    #     intermediate state some inner middleware still touches.
    #   - It stays inside ResourceStreamDeadlineMiddleware because that one
    #     needs to observe/bound the complete raw ASGI exchange for the one
    #     SSE path it governs. That observation is unaffected by GZip's
    #     presence: `text/event-stream` is never on the compression
    #     allowlist, so GZip forwards those messages one-for-one with no
    #     buffering, exactly as if it were absent (see `middleware/gzip.py`
    #     and `test_server_middleware.py`'s SSE test).
    script_hashes = _compute_script_hashes(project_root / "frontend" / "build" / "index.html")
    app.add_middleware(SecurityHeadersMiddleware, script_hashes=script_hashes)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CsrfTokenMiddleware)
    app.add_middleware(CsrfOriginMiddleware)
    app.add_middleware(IpRateLimitMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)

    cors_origin = get_settings().cors_origin
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
    app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=GZIP_MINIMUM_SIZE_BYTES,
        compresslevel=GZIP_COMPRESS_LEVEL,
    )
    app.add_middleware(ResourceStreamDeadlineMiddleware)

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
    from songmaker_cli.health_api import router as health_router
    from songmaker_cli.sharing_api import router as sharing_router

    app.include_router(api_router)
    app.include_router(health_router)
    app.include_router(sharing_router)

    sveltekit_dir = project_root / "frontend" / "build"
    sveltekit_app_dir = sveltekit_dir / "_app"

    if sveltekit_app_dir.exists():
        app.mount(
            "/_app", StaticFiles(directory=str(sveltekit_app_dir)), name="sveltekit-app",
        )

    favicon_path = sveltekit_dir / "favicon.svg"

    @app.get("/favicon.svg", include_in_schema=False)
    async def serve_favicon() -> FileResponse:
        return FileResponse(favicon_path, media_type="image/svg+xml")

    sw_path = sveltekit_dir / "service-worker.js"
    manifest_path = sveltekit_dir / "manifest.webmanifest"
    icon_192_path = sveltekit_dir / "icon-192.png"
    icon_512_path = sveltekit_dir / "icon-512.png"
    _pwa_exact_paths = frozenset({
        "/service-worker.js",
        "/manifest.webmanifest",
    }) | PWA_ICON_PATHS

    @app.get("/service-worker.js", include_in_schema=False)
    async def serve_service_worker() -> FileResponse:
        if not sw_path.exists():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def serve_webmanifest() -> FileResponse:
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(manifest_path, media_type="application/manifest+json")

    @app.get("/icon-192.png", include_in_schema=False)
    async def serve_icon_192() -> FileResponse:
        if not icon_192_path.exists():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(icon_192_path, media_type="image/png")

    @app.get("/icon-512.png", include_in_schema=False)
    async def serve_icon_512() -> FileResponse:
        if not icon_512_path.exists():
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(icon_512_path, media_type="image/png")

    sk_index = sveltekit_dir / "index.html"

    @app.exception_handler(404)
    async def spa_fallback(request: Request, exc: HTTPException) -> FileResponse:
        if (
            not request.url.path.startswith("/api/")
            and not request.url.path.startswith("/audio/")
            and not request.url.path.startswith("/_app/")
            and not request.url.path.startswith("/shared/")
            and request.url.path not in _pwa_exact_paths
            and sk_index.exists()
        ):
            return FileResponse(sk_index, media_type="text/html")
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    return app


def run_server(
    audio_dir: Path | None = None,
    data_dir: Path | None = None,
    project_root: Path | None = None,
    port: int = 8080,
    open_browser: bool = False,
) -> None:
    import uvicorn

    if project_root is None:
        project_root = find_project_root(Path.cwd()) or Path.cwd()

    settings = get_settings()
    if audio_dir is None:
        audio_dir = project_root / settings.audio_dir
    if data_dir is None:
        data_dir = project_root / settings.data_dir

    from songmaker_cli.logging_config import configure_logging
    configure_logging()

    for d in (audio_dir, data_dir):
        if not d.exists():
            d.mkdir(parents=True)

    app = create_app(audio_dir, data_dir, project_root)
    log.info("Songmaker server: http://localhost:%d", port)
    log.info("Auth enabled (session-based)")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    uvicorn.run(
        app, host=settings.host, port=port, log_level="info",
        timeout_keep_alive=settings.request_timeout_seconds,
    )
