"""Songmaker server — FastAPI backend for the web UI.

Serves the SvelteKit frontend, audio files, and REST API backed by SQLite.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import logging
import os
import secrets
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


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if (request.url.path == "/"
            or request.url.path.startswith("/static")
            or request.url.path.startswith("/audio/")
            or request.url.path.startswith("/_app")
            or (request.url.path.startswith("/api/") and request.method == "GET")):
            return await call_next(request)

        key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not secrets.compare_digest(key or "", self.api_key):
            ip = request.client.host if request.client else "unknown"
            log.warning("REJECTED %s %s %s (bad API key)", ip, request.method, request.url.path)
            return JSONResponse({"error": "Invalid API key"}, status_code=403)
        return await call_next(request)


def create_app(
    output_dir: Path, project_root: Path, api_key: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Songmaker", docs_url=None, redoc_url=None)

    app.add_middleware(AccessLogMiddleware)

    if api_key:
        app.add_middleware(ApiKeyMiddleware, api_key=api_key)

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from songmaker_cli.api import router as api_router

    app.include_router(api_router)

    @app.get("/audio/{album}/{filename}")
    async def get_audio(album: str, filename: str) -> FileResponse:
        audio_path = (output_dir / album / filename).resolve()
        if not audio_path.is_relative_to(output_dir.resolve()):
            raise HTTPException(403, "Path traversal denied")
        if not audio_path.exists():
            raise HTTPException(404, f"Not found: {album}/{filename}")
        return FileResponse(audio_path, media_type="audio/mpeg")

    sveltekit_dir = project_root / "frontend" / "build"
    sveltekit_app_dir = sveltekit_dir / "_app"

    @app.get("/")
    async def serve_player() -> FileResponse:
        sk_index = sveltekit_dir / "index.html"
        if not sk_index.exists():
            raise HTTPException(
                500, "SvelteKit build not found — run 'cd frontend && pnpm build'",
            )
        return FileResponse(sk_index, media_type="text/html")

    if sveltekit_app_dir.exists():
        app.mount(
            "/_app", StaticFiles(directory=str(sveltekit_app_dir)), name="sveltekit-app",
        )

    app.mount(
        "/static", StaticFiles(directory=str(output_dir)), name="static",
    )

    return app


def run_server(
    output_dir: Path | None = None,
    project_root: Path | None = None,
    port: int = 8080,
    open_browser: bool = False,
    api_key: str | None = None,
) -> None:
    import uvicorn

    if project_root is None:
        project_root = find_project_root(Path.cwd()) or Path.cwd()
    if output_dir is None:
        output_dir = project_root / OUTPUT_ROOT
    if api_key is None:
        api_key = os.environ.get("SONGMAKER_API_KEY")

    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    from songmaker_cli.db.engine import init_db

    db_path = output_dir / DB_FILENAME
    init_db(db_path)

    app = create_app(output_dir, project_root, api_key=api_key)
    log.info("Songmaker server: http://localhost:%d", port)
    if api_key:
        log.info("API key required: %s...%s", api_key[:4], api_key[-4:])
    else:
        log.info("No API key — server is open (local use only)")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    host = "0.0.0.0" if api_key else "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="info")
