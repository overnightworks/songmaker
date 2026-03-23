"""Songmaker server — FastAPI backend for the player UI.

Serves manifest, audio files, and accepts ratings. Optionally triggers
generation and scoring via the CLI engine.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.config import find_project_root
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.player import generate_player
from songmaker_cli.snapshot import append_scores_section, save_rating

if TYPE_CHECKING:
    from songmaker_cli.parser import SongMeta

log = logging.getLogger(__name__)


class RatingRequest(BaseModel):
    """Star rating from the player UI."""

    rating: int = Field(ge=1, le=5)
    notes: str = ""


class GenerateRequest(BaseModel):
    """Generation request from the player UI."""

    path: str
    count: int = 1


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log every request with IP, method, path, and status."""

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
    """Require X-API-Key header on all requests when api_key is set."""

    def __init__(self, app: FastAPI, api_key: str) -> None:
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Allow public paths: player HTML, audio files, manifest (read-only)
        if (request.url.path == "/"
            or request.url.path.startswith("/static")
            or request.url.path.startswith("/audio/")
            or (request.url.path == "/manifest.json" and request.method == "GET")):
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

    manifest_path = output_dir / "manifest.json"
    player_html = output_dir / "player.html"

    @app.get("/manifest.json")
    async def get_manifest() -> JSONResponse:
        if not manifest_path.exists():
            raise HTTPException(404, "No manifest.json — run songmaker player first")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return JSONResponse(data)

    @app.get("/audio/{album}/{filename}")
    async def get_audio(album: str, filename: str) -> FileResponse:
        audio_path = (output_dir / album / filename).resolve()
        if not audio_path.is_relative_to(output_dir.resolve()):
            raise HTTPException(403, "Path traversal denied")
        if not audio_path.exists():
            raise HTTPException(404, f"Not found: {album}/{filename}")
        return FileResponse(audio_path, media_type="audio/mpeg")

    @app.post("/rate/{album}/{version}")
    async def rate_version(album: str, version: str, req: RatingRequest) -> dict[str, object]:
        snapshot_path = output_dir / album / f"{version}.md"
        if not snapshot_path.exists():
            raise HTTPException(404, f"Snapshot not found: {album}/{version}.md")

        save_rating(snapshot_path, req.rating, req.notes)
        _rebuild_manifest(output_dir, project_root)
        return {"status": "ok", "version": version, "rating": req.rating}

    @app.post("/score/{album}/{version}")
    async def score_version(
        album: str, version: str, background_tasks: BackgroundTasks,
    ) -> dict[str, str]:
        mp3_path = output_dir / album / f"{version}.mp3"
        if not mp3_path.exists():
            raise HTTPException(404, f"MP3 not found: {album}/{version}.mp3")

        background_tasks.add_task(_run_scoring, mp3_path, output_dir, project_root)
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

        background_tasks.add_task(
            _run_generation, md_path, req.count,
        )
        return {"status": "started", "path": req.path}

    @app.get("/")
    async def serve_player() -> FileResponse:
        if not player_html.exists():
            generate_player(output_dir, project_root)
        return FileResponse(player_html, media_type="text/html")

    app.mount(
        "/static", StaticFiles(directory=str(output_dir)), name="static",
    )

    return app


def _rebuild_manifest(output_dir: Path, project_root: Path) -> None:
    """Rebuild manifest.json after a change."""
    generate_player(output_dir, project_root)
    log.info("Manifest rebuilt")


def _run_scoring(mp3_path: Path, output_dir: Path, project_root: Path) -> None:
    """Run scoring pipeline on a single MP3."""
    from songmaker_cli.scoring import run_scoring_pipeline

    snapshot_path = mp3_path.with_suffix(".md")
    meta = _load_meta_for_mp3(mp3_path, project_root)

    scores = run_scoring_pipeline(mp3_path, meta=meta)
    if snapshot_path.exists():
        append_scores_section(snapshot_path, scores)

    _rebuild_manifest(output_dir, project_root)
    log.info("Scored: %s", mp3_path.name)


def _run_generation(md_path: Path, count: int) -> None:
    """Run generation in background."""
    from songmaker_cli.generate import GenerationOptions, run_generate

    opts = GenerationOptions(count=count)
    run_generate(str(md_path), opts)
    log.info("Generation complete: %s", md_path.name)


def _load_meta_for_mp3(mp3_path: Path, project_root: Path) -> SongMeta | None:
    """Try to find and parse the lyrics source for an MP3."""
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

    generate_player(output_dir, project_root)

    app = create_app(output_dir, project_root, api_key=api_key)
    log.info("Songmaker server: http://localhost:%d", port)
    if api_key:
        log.info("API key required: %s...%s", api_key[:4], api_key[-4:])
    else:
        log.info("No API key — server is open (local use only)")

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    # Bind to 0.0.0.0 when API key is set (ngrok needs it), else localhost only
    host = "0.0.0.0" if api_key else "127.0.0.1"
    uvicorn.run(app, host=host, port=port, log_level="info")
