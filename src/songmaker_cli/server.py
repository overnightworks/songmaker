"""Songmaker server — FastAPI backend for the player UI.

Serves the SvelteKit frontend, audio files, and REST API backed by SQLite.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.config import find_project_root
from songmaker_cli.constants import OUTPUT_ROOT

if TYPE_CHECKING:
    from songmaker_cli.parser import SongMeta

log = logging.getLogger(__name__)

DB_FILENAME = "songmaker.db"


class GenerateRequest(BaseModel):
    path: str
    count: int = 1


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
    """Create the FastAPI app with routes bound to the given directories."""
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

    _scoring_lock = threading.Lock()
    _generation_lock = threading.Lock()

    @app.get("/audio/{album}/{filename}")
    async def get_audio(album: str, filename: str) -> FileResponse:
        audio_path = (output_dir / album / filename).resolve()
        if not audio_path.is_relative_to(output_dir.resolve()):
            raise HTTPException(403, "Path traversal denied")
        if not audio_path.exists():
            raise HTTPException(404, f"Not found: {album}/{filename}")
        return FileResponse(audio_path, media_type="audio/mpeg")

    @app.post("/score/{album}/{version}")
    async def score_version(
        album: str, version: str, background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        mp3_path = output_dir / album / f"{version}.mp3"
        if not mp3_path.exists():
            raise HTTPException(404, f"MP3 not found: {album}/{version}.mp3")

        if not _scoring_lock.acquire(blocking=False):
            raise HTTPException(409, "Scoring already in progress")
        background_tasks.add_task(
            _run_scoring, mp3_path, output_dir, project_root, _scoring_lock,
        )
        return {"status": "started", "version": version}

    @app.post("/generate")
    async def trigger_generate(
        req: GenerateRequest, background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        md_path = Path(req.path).resolve()
        albums_dir = (project_root / "albums").resolve()
        if not md_path.is_relative_to(albums_dir):
            raise HTTPException(403, "Path must be under albums/")
        if not md_path.exists():
            raise HTTPException(404, f"Song file not found: {req.path}")

        if not _generation_lock.acquire(blocking=False):
            raise HTTPException(409, "Generation already in progress")
        background_tasks.add_task(_run_generation, md_path, req.count, _generation_lock)
        return {"status": "started", "path": req.path}

    # SvelteKit build directory
    sveltekit_dir = project_root / "frontend" / "build"
    sveltekit_app_dir = sveltekit_dir / "_app"

    @app.get("/")
    async def serve_player() -> FileResponse:
        sk_index = sveltekit_dir / "index.html"
        if not sk_index.exists():
            raise HTTPException(
                500, "SvelteKit build not found — run 'cd player && pnpm build'",
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


def _run_scoring(
    mp3_path: Path, output_dir: Path, project_root: Path, lock: threading.Lock,
) -> None:
    try:
        from songmaker_cli.scoring import run_scoring_pipeline
        from songmaker_cli.snapshot import append_scores_section

        snapshot_path = mp3_path.with_suffix(".md")
        meta = _load_meta_for_mp3(mp3_path, project_root)

        scores = run_scoring_pipeline(mp3_path, meta=meta)
        if snapshot_path.exists():
            append_scores_section(snapshot_path, scores)

        log.info("Scored: %s", mp3_path.name)
    finally:
        lock.release()


def _run_generation(md_path: Path, count: int, lock: threading.Lock) -> None:
    try:
        from songmaker_cli.generate import GenerationOptions, run_generate

        opts = GenerationOptions(count=count)
        run_generate(str(md_path), opts)
        log.info("Generation complete: %s", md_path.name)
    finally:
        lock.release()


def _load_meta_for_mp3(mp3_path: Path, project_root: Path) -> SongMeta | None:
    import yaml

    from songmaker_cli.check import find_lyrics_source
    from songmaker_cli.errors import ValidationError
    from songmaker_cli.parser import parse_song_md

    try:
        md_path = find_lyrics_source(mp3_path, None, project_root=str(project_root))
        return parse_song_md(md_path)
    except (ValidationError, FileNotFoundError, yaml.YAMLError):
        return None


def run_server(
    output_dir: Path | None = None,
    project_root: Path | None = None,
    port: int = 8080,
    open_browser: bool = False,
    api_key: str | None = None,
) -> None:
    """Start the songmaker server."""
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
