"""Songmaker server -- FastAPI backend for the web UI.

Serves the SvelteKit frontend, audio files, and REST API backed by PostgreSQL.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from logline import configure, set_route
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from webauth.ports import WallClock
from webauth.web_auth import (
    IssuerCalls,
    WebAuth,
    WebAuthSettings,
    WebAuthStores,
)

from songmaker_cli.agent.mcp import (
    build_protected_resource,
    collect_route_tools,
    mount_mcp_front,
    running_mcp_front,
)
from songmaker_cli.app_context import (
    AppContext,
    allowed_hosts,
    build_web_auth_config,
    parse_trusted_proxies,
)
from songmaker_cli.audio_paths import AudioPathRejectedError
from songmaker_cli.auth_api import sign_in_pages
from songmaker_cli.auth_stores import DatabaseSessionTransaction, DatabaseSignInTransaction
from songmaker_cli.config import find_project_root
from songmaker_cli.constants import (
    APP_NAME,
    GZIP_COMPRESS_LEVEL,
    GZIP_MINIMUM_SIZE_BYTES,
    HTTP_NOT_FOUND,
    PWA_ICON_PATHS,
)
from songmaker_cli.cover_runner import cover_runner_loop, reconcile_reaped_cover_jobs
from songmaker_cli.health_api import compute_script_hashes
from songmaker_cli.health_types import BackgroundLoopName, BackgroundLoopRegistry
from songmaker_cli.lifecycle import (
    cleanup_expired_resource_events,
    fail_jobs_of_dead_owners,
    owner_gone_reaper_loop,
    owner_lapse_loop,
    reap_stale_jobs,
    reconcile_crashed_loras,
    reconcile_ended_covers,
    resource_event_cleanup_loop,
    score_backfill_loop,
    session_cleanup_loop,
    stale_job_reaper_loop,
)
from songmaker_cli.middleware.gzip import SelectiveGZipMiddleware
from songmaker_cli.middleware.http_metrics import HttpMetricsMiddleware
from songmaker_cli.middleware.resource_stream_deadline import ResourceStreamDeadlineMiddleware
from songmaker_cli.oidc_client import (
    build_admission_config,
    build_bearer_gate,
    build_oidc_client_config,
)
from songmaker_cli.page_language import PageShell
from songmaker_cli.refusals import install_refusal_handler, not_found_response
from songmaker_cli.request_policies import (
    SIGN_IN_PATHS,
    build_body_size_policy,
    build_csrf_origin_policy,
    build_rate_limit_policy,
    build_security_headers_policy,
)
from songmaker_cli.settings import DEFAULT_SERVER_PORT, Settings, get_settings
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_liveness import keep_owner_lease

WEB_SERVICE_NAME = "songmaker-web"

log = logging.getLogger(__name__)


def _record_background_loop_completion(
    task: asyncio.Task[None],
    name: BackgroundLoopName,
    registry: BackgroundLoopRegistry,
) -> None:
    if registry.shutting_down:
        return
    if task.cancelled():
        registry.mark_dead(name, asyncio.CancelledError())
    else:
        exception = task.exception()
        registry.mark_dead(name, exception)
        if exception is not None:
            log.error("Background loop %s ended", name, exc_info=exception)
            return
    log.error("Background loop %s ended", name)


def _start_background_loops(
    app: FastAPI, registry: BackgroundLoopRegistry,
) -> list[tuple[BackgroundLoopName, asyncio.Task]]:
    loop_tasks = [
        (BackgroundLoopName.SESSION_CLEANUP, asyncio.create_task(session_cleanup_loop(app))),
        (
            BackgroundLoopName.RESOURCE_EVENT_CLEANUP,
            asyncio.create_task(resource_event_cleanup_loop(app)),
        ),
        (BackgroundLoopName.SCORE_BACKFILL, asyncio.create_task(score_backfill_loop(app))),
        (BackgroundLoopName.STALE_JOB_REAPER, asyncio.create_task(stale_job_reaper_loop(app))),
        (BackgroundLoopName.OWNER_LAPSES, asyncio.create_task(owner_lapse_loop(app))),
        (
            BackgroundLoopName.OWNER_GONE_REAPER,
            asyncio.create_task(owner_gone_reaper_loop(app)),
        ),
        (
            BackgroundLoopName.COVER_RUNNER,
            asyncio.create_task(cover_runner_loop(app, registry)),
        ),
    ]
    app.state.background_loop_tasks = dict(loop_tasks)
    for name, task in loop_tasks:
        task.add_done_callback(
            lambda completed, loop_name=name: _record_background_loop_completion(
                completed,
                loop_name,
                registry,
            ),
        )
    return loop_tasks


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    from songmaker_cli.arq_pool import close_arq_pool, init_arq_pool
    from songmaker_cli.db.queries.auth import delete_expired_sessions
    from songmaker_cli.queue_streams import cleanup_expired_queue_streams

    ctx: AppContext = app.state.ctx
    registry = BackgroundLoopRegistry(tuple(BackgroundLoopName))
    app.state.background_loop_registry = registry
    await asyncio.to_thread(cleanup_expired_queue_streams, ctx)
    with ctx.db() as session:
        deleted = delete_expired_sessions(session)
        if deleted:
            log.info("Startup: cleaned up %d expired sessions", deleted)
        session.commit()

    await fail_jobs_of_dead_owners(ctx)
    await asyncio.to_thread(reconcile_reaped_cover_jobs, ctx.db, ctx.audio_dir)
    reap_stale_jobs(ctx)
    reconcile_crashed_loras(ctx)
    await asyncio.to_thread(cleanup_expired_resource_events, ctx)

    await init_arq_pool()
    log.info("arq pool connected")

    app.state.startup_time = utcnow()
    try:
        async with keep_owner_lease(
            ctx.owner_leases, ctx.owner_id,
            on_new_start=partial(reconcile_ended_covers, ctx),
        ) as ctx.owner:
            loop_tasks = _start_background_loops(app, registry)
            try:
                async with running_mcp_front(app):
                    yield
            finally:
                registry.begin_shutdown()
                for _name, task in loop_tasks:
                    task.cancel()
                await asyncio.gather(*(task for _name, task in loop_tasks), return_exceptions=True)
    finally:
        await ctx.slot_releases.drain()
        await close_arq_pool()
        await ctx.async_redis.aclose()


def audio_path_rejected_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Answer a rejected audio path exactly like a missing resource."""
    return JSONResponse({"detail": HTTP_NOT_FOUND}, status_code=404)


def _install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AudioPathRejectedError, audio_path_rejected_handler)
    install_refusal_handler(app)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        fields = sorted({".".join(str(loc) for loc in e["loc"]) for e in exc.errors()})
        return JSONResponse(
            {"detail": f"Validation error on: {', '.join(fields)}"},
            status_code=422,
        )


def _install_pwa_assets(app: FastAPI, sveltekit_dir: Path) -> frozenset[str]:
    """Serve the favicon, service worker, manifest and icons; return their exact paths."""
    favicon_path = sveltekit_dir / "favicon.svg"

    @app.get("/favicon.svg", include_in_schema=False)
    async def serve_favicon() -> FileResponse:
        return FileResponse(favicon_path, media_type="image/svg+xml")

    sw_path = sveltekit_dir / "service-worker.js"
    manifest_path = sveltekit_dir / "manifest.webmanifest"
    exact_paths = (
        frozenset(
            {
                "/service-worker.js",
                "/manifest.webmanifest",
            }
        )
        | PWA_ICON_PATHS
    )

    @app.get("/service-worker.js", include_in_schema=False)
    async def serve_service_worker() -> FileResponse:
        if not sw_path.exists():
            raise HTTPException(status_code=404, detail=HTTP_NOT_FOUND)  # unread: media
        return FileResponse(
            sw_path,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"},
        )

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def serve_webmanifest() -> FileResponse:
        if not manifest_path.exists():
            raise HTTPException(status_code=404, detail=HTTP_NOT_FOUND)  # unread: media
        return FileResponse(manifest_path, media_type="application/manifest+json")

    def register_icon_route(icon_path: str) -> None:
        icon_file = sveltekit_dir / icon_path.lstrip("/")

        @app.get(icon_path, include_in_schema=False)
        async def serve_icon() -> FileResponse:
            if not icon_file.exists():
                raise HTTPException(status_code=404, detail=HTTP_NOT_FOUND)  # unread: media
            return FileResponse(icon_file, media_type="image/png")

    for icon_path in sorted(PWA_ICON_PATHS):
        register_icon_route(icon_path)

    return exact_paths


def build_web_auth(
    ctx: AppContext,
    settings: Settings,
    script_hashes: Sequence[str],
    issuer_calls: IssuerCalls | None,
    wall_clock: WallClock,
) -> WebAuth:
    """The composition call: webauth's stack with songmaker's own layers in its two slots.

    Outermost first, the whole stack is: the request line and the client-address writer
    (`front`), `outside`, webauth's security headers, path refusal, body limit, rate limit, bearer
    gate and CSRF origin check, then `inside`. A layer in `outside` sees every refusal of the
    stack with its headers; one in `inside` sees only the requests the stack admitted.
    WARNING: reordering the entries of the two slots changes security behavior.
    """
    client = build_oidc_client_config(settings)
    return WebAuth.build(
        WebAuthSettings(
            config=build_web_auth_config(ctx, settings, wall_clock=wall_clock),
            client=client,
            sign_in_paths=SIGN_IN_PATHS,
            keeps_id_token=True,
            max_sessions=settings.max_concurrent_sessions_per_user,
            security_headers=build_security_headers_policy(script_hashes),
            csrf_origin=build_csrf_origin_policy(),
            body_size=build_body_size_policy(settings),
            rate_limit=build_rate_limit_policy(settings),
        ),
        stores=WebAuthStores(
            sign_in=DatabaseSignInTransaction(ctx.db),
            sessions=DatabaseSessionTransaction(ctx.db),
        ),
        groups=build_admission_config(client),
        pages=sign_in_pages(),
        front=parse_trusted_proxies(settings),
        outside=(
            # The deadline bounds the whole raw exchange of the one SSE path it governs; gzip
            # compresses the finished response once and forwards `text/event-stream` untouched.
            Middleware(ResourceStreamDeadlineMiddleware),
            Middleware(
                SelectiveGZipMiddleware,
                minimum_size=GZIP_MINIMUM_SIZE_BYTES,
                compresslevel=GZIP_COMPRESS_LEVEL,
            ),
            Middleware(CORSMiddleware, **_cors_middleware_kwargs(settings.cors_origin)),
        ),
        inside=(
            Middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts(settings))),
            Middleware(HttpMetricsMiddleware),
        ),
        issuer_calls=issuer_calls,
    )


def _report_the_full_route(request: Request) -> None:
    """Give the request line the route's template with the prefixes of the routers it sits in.

    FastAPI's route holds only its own path (`/songs/{song_id}`), while the rate-limit policy and
    an operator reading the log both speak of the whole one (`/api/songs/{song_id}`). The prefix is
    what the request path has before the route's own part.
    """
    route = request.scope["route"]
    own_path = route.path_format.format(**request.scope["path_params"])
    prefix = request.scope["path"].removesuffix(own_path)
    set_route(request.scope, prefix + route.path)


def create_app(
    audio_dir: Path,
    data_dir: Path,
    project_root: Path,
    ctx: AppContext | None = None,
    issuer_calls: IssuerCalls | None = None,
    wall_clock: WallClock = time.time,
) -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan, dependencies=[Depends(_report_the_full_route)],
    )
    if ctx is None:
        ctx = _create_default_context(audio_dir, data_dir)

    app.state.ctx = ctx
    from songmaker_cli.redis_client import RedisHttpMetrics

    settings = get_settings()
    script_hashes = compute_script_hashes(project_root / "frontend" / "build" / "index.html")
    auth = build_web_auth(ctx, settings, script_hashes, issuer_calls, wall_clock)
    app.state.web_auth = auth
    app.state.http_metrics = RedisHttpMetrics(ctx.redis)

    _include_routers(app)

    # Every route that appears in the schema is registered, so the marks are read from a
    # complete schema; the gate needs them before it is installed.
    agent_tools = collect_route_tools(app)
    mcp_resource = build_protected_resource(settings, agent_tools.marks)
    # `/mcp` is a route of the host: it registers before `auth.install`.
    app.state.mcp_front = mount_mcp_front(
        app, agent_tools, mcp_resource, auth.admission.bound_issuer,
    )

    _install_error_handlers(app)
    sveltekit_dir = project_root / "frontend" / "build"
    sveltekit_app_dir = sveltekit_dir / "_app"

    if sveltekit_app_dir.exists():
        app.mount(
            "/_app",
            StaticFiles(directory=str(sveltekit_app_dir)),
            name="sveltekit-app",
        )

    _pwa_exact_paths = _install_pwa_assets(app, sveltekit_dir)
    page_shell = PageShell.read(sveltekit_dir / "index.html")
    app.state.page_shell = page_shell

    # The security-critical middleware order is the composition call's (`build_web_auth`): the
    # install after the last route places webauth's stack between the two slots.
    auth.install(app, bearer=build_bearer_gate(settings, mcp_resource))

    @app.exception_handler(404)
    def spa_fallback(request: Request, exc: HTTPException) -> HTMLResponse | JSONResponse:
        if request.url.path.startswith(("/api/", "/audio/")):
            return not_found_response(request, exc)
        if (
            not request.url.path.startswith("/_app/")
            and not request.url.path.startswith("/shared/")
            and request.url.path not in _pwa_exact_paths
            and page_shell is not None
        ):
            return page_shell.answer(request)
        return JSONResponse({"detail": HTTP_NOT_FOUND}, status_code=404)

    return app


def _include_routers(app: FastAPI) -> None:
    from songmaker_cli.api import router as api_router
    from songmaker_cli.audio_api import router as audio_router
    from songmaker_cli.health_api import router as health_router
    from songmaker_cli.shared_views_api import router as shared_views_router
    from songmaker_cli.sharing_api import router as sharing_router

    # The file routes register before the views so that `/shared/song/cover` and its
    # siblings reach the album-cover route, as no slug can equal those words.
    for router in (api_router, audio_router, health_router, sharing_router, shared_views_router):
        app.include_router(router)


def _create_default_context(audio_dir: Path, data_dir: Path) -> AppContext:
    from songmaker_cli.db.database_url import connection_url_from_settings
    from songmaker_cli.db.engine import init_db
    from songmaker_cli.object_store import object_store_of
    from songmaker_cli.redis_client import create_async_redis, create_redis, wait_for_redis

    settings = get_settings()
    object_store = object_store_of(settings)
    redis_instance = create_redis(settings.redis_url)
    try:
        wait_for_redis(redis_instance, settings.redis_url.split("@")[-1])
    except BaseException:
        redis_instance.close()
        raise
    return AppContext(
        db=init_db(connection_url_from_settings(settings)),
        audio_dir=audio_dir,
        data_dir=data_dir,
        signing_key=settings.session_secret.get_secret_value().encode(),
        redis=redis_instance,
        async_redis=create_async_redis(settings.redis_url),
        object_store=object_store,
    )


def _cors_middleware_kwargs(cors_origin: str | None) -> dict:
    if cors_origin and ("*" in cors_origin or "," in cors_origin):
        raise ValueError(
            "Invalid CORS_ORIGIN: configure one literal origin; "
            "wildcards and lists are not allowed",
        )

    cors_kwargs: dict = {
        "allow_methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Cookie"],
        "allow_credentials": True,
    }
    if cors_origin:
        cors_kwargs["allow_origins"] = [cors_origin]
    else:
        cors_kwargs["allow_origin_regex"] = r"^https?://(localhost|127\.0\.0\.1)(:(8080|5173))?$"
    return cors_kwargs


def run_server(
    project_root: Path | None = None,
    port: int = DEFAULT_SERVER_PORT,
    open_browser: bool = False,
) -> None:
    import uvicorn

    if project_root is None:
        project_root = find_project_root(Path.cwd()) or Path.cwd()

    settings = get_settings()
    audio_dir = project_root / settings.audio_dir
    data_dir = project_root / settings.data_dir

    configure(WEB_SERVICE_NAME)

    for d in (audio_dir, data_dir):
        if not d.exists():
            d.mkdir(parents=True)

    app = create_app(audio_dir, data_dir, project_root)
    from songmaker_cli.agent.backend import compose_agent_backend

    compose_agent_backend(app, settings)
    log.info("Songmaker server: http://localhost:%d", port)
    log.info("Auth enabled (session-based)")

    if open_browser:
        import webbrowser

        webbrowser.open(f"http://localhost:{port}")

    # proxy_headers=False: uvicorn's own X-Forwarded-For/-Proto handling would
    # rewrite the peer address and the scheme before any application code sees
    # them, from *any* peer unless forwarded_allow_ips is kept in sync with
    # TRUSTED_PROXIES. TrustedProxies is the single owner of that decision (webauth's
    # client-address writer applies it), so uvicorn must hand over the connection as it is.
    uvicorn.run(
        app,
        host=settings.host,
        port=port,
        timeout_keep_alive=settings.request_timeout_seconds,
        proxy_headers=False,
        log_config=None,
    )
