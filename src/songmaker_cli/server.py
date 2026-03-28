"""Songmaker server -- FastAPI backend for the web UI.

Serves the SvelteKit frontend, audio files, and REST API backed by PostgreSQL.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import asyncio
import logging
import os
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
from songmaker_cli.constants import AUDIO_ROOT, DATA_ROOT
from songmaker_cli.health_api import _compute_script_hash
from songmaker_cli.lifecycle import auto_setup_admin, session_sync_loop
from songmaker_cli.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    CsrfOriginMiddleware,
    CsrfTokenMiddleware,
    IpRateLimitMiddleware,
    SecurityHeadersMiddleware,
)

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT", 30))


def parse_allowed_hosts() -> tuple[frozenset[str], list[re.Pattern[str]]]:
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
    from songmaker_cli.arq_pool import close_arq_pool, init_arq_pool
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

    auto_setup_admin(ctx)

    await init_arq_pool()
    log.info("arq pool connected")

    app.state.startup_time = datetime.now(timezone.utc)
    sync_task = asyncio.create_task(session_sync_loop(app))
    yield
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    await close_arq_pool()


def create_app(
    audio_dir: Path, data_dir: Path, project_root: Path,
    ctx: AppContext | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Hallucinai",
        docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=_lifespan,
    )

    if ctx is None:
        from songmaker_cli.auth import ensure_session_secret, parse_trusted_proxies
        from songmaker_cli.db.engine import init_db, resolve_database_url

        db_url = resolve_database_url()
        db_factory = init_db(db_url)
        secret = ensure_session_secret(data_dir)
        hosts_exact, hosts_patterns = parse_allowed_hosts()

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
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
    #   1. BodySizeLimitMiddleware  -- reject oversized bodies before processing
    #   2. IpRateLimitMiddleware    -- rate-limit before auth/CSRF to bound cost
    #   3. CsrfOriginMiddleware     -- reject cross-origin state-changing requests
    #   4. CsrfTokenMiddleware      -- verify double-submit CSRF token
    #   5. AccessLogMiddleware       -- log all requests (after security checks)
    #   6. SecurityHeadersMiddleware -- add security headers to responses
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
    from songmaker_cli.config import load_env_file

    load_env_file(project_root)


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
    if audio_dir is None:
        audio_dir = project_root / AUDIO_ROOT
    if data_dir is None:
        data_dir = project_root / DATA_ROOT

    _load_env_file(project_root)

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

    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(
        app, host=host, port=port, log_level="info",
        timeout_keep_alive=REQUEST_TIMEOUT_SECONDS,
    )
