"""Songmaker server — FastAPI backend for the web UI.

Serves the SvelteKit frontend, audio files, and REST API backed by SQLite.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.config import find_project_root
from songmaker_cli.constants import OUTPUT_ROOT

log = logging.getLogger(__name__)

DB_FILENAME = "songmaker.db"


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


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        from songmaker_cli.middleware import session_auth_middleware

        return await session_auth_middleware(request, call_next)


def create_app(
    output_dir: Path, project_root: Path, *, auth_enabled: bool = True,
) -> FastAPI:
    app = FastAPI(title="Songmaker", docs_url=None, redoc_url=None)

    app.add_middleware(AccessLogMiddleware)

    if auth_enabled:
        app.add_middleware(SessionMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    from songmaker_cli.api import router as api_router

    app.include_router(api_router)

    @app.get("/audio/{album}/{filename}")
    async def get_audio(album: str, filename: str, request: Request) -> FileResponse:
        audio_path = (output_dir / album / filename).resolve()
        if not audio_path.is_relative_to(output_dir.resolve()):
            raise HTTPException(403, "Path traversal denied")
        if not audio_path.exists():
            raise HTTPException(404, f"Not found: {album}/{filename}")

        user = getattr(request.state, "user", None)
        if user and user.role != "admin":
            from songmaker_cli.db.engine import get_session_factory
            from songmaker_cli.db.queries import get_album

            factory = get_session_factory()
            with factory() as session:
                db_album = get_album(session, album)
                if db_album and db_album.created_by != user.id:
                    raise HTTPException(404, f"Not found: {album}/{filename}")

        return FileResponse(audio_path, media_type="audio/mpeg")

    sveltekit_dir = project_root / "frontend" / "build"
    sveltekit_app_dir = sveltekit_dir / "_app"

    app.mount(
        "/static", StaticFiles(directory=str(output_dir)), name="static",
    )

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
            and not request.url.path.startswith("/static/")
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

    from songmaker_cli.db.engine import init_db

    db_path = output_dir / DB_FILENAME
    init_db(db_path)

    session_secret = os.environ.get("SESSION_SECRET", "")
    auth_enabled = bool(session_secret)

    app = create_app(output_dir, project_root, auth_enabled=auth_enabled)
    log.info("Songmaker server: http://localhost:%d", port)
    if auth_enabled:
        log.info("Auth enabled (session-based)")
    else:
        log.info("Auth disabled — set SESSION_SECRET to enable")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    host = "0.0.0.0" if auth_enabled else "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="info")
