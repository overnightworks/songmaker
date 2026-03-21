"""Songmaker server — FastAPI backend for the player UI.

Serves manifest, audio files, and accepts ratings. Optionally triggers
generation and scoring via the CLI engine.

Usage:
    songmaker server [--port 8080] [--open]
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from songmaker_cli.config import find_project_root
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.player import generate_player
from songmaker_cli.snapshot import append_scores_section

log = logging.getLogger(__name__)


class RatingRequest(BaseModel):
    """Star rating from the player UI."""

    rating: int
    notes: str = ""


class GenerateRequest(BaseModel):
    """Generation request from the player UI."""

    path: str
    count: int = 1
    best: int | None = None
    score: bool = False


def create_app(output_dir: Path, project_root: Path) -> FastAPI:
    """Create the FastAPI app with routes bound to the given directories."""
    app = FastAPI(title="Songmaker", docs_url=None, redoc_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
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

        _save_rating(snapshot_path, req.rating, req.notes)
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
        if not md_path.exists():
            raise HTTPException(404, f"Song file not found: {req.path}")

        background_tasks.add_task(
            _run_generation, md_path, req.count, req.best, req.score,
            output_dir, project_root,
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


def _save_rating(snapshot_path: Path, rating: int, notes: str) -> None:
    """Append or update user_rating in the snapshot's ## Scores section."""
    text = snapshot_path.read_text(encoding="utf-8")

    if "## Scores" in text:
        before_scores = text[:text.index("## Scores")].rstrip()
        scores_section = text[text.index("## Scores"):]
    else:
        before_scores = text.rstrip()
        scores_section = ""

    lines = scores_section.splitlines() if scores_section else []
    new_lines = [
        ln for ln in lines
        if not ln.startswith("- user_rating:")
        and not ln.startswith("- user_notes:")
    ]

    if not new_lines:
        new_lines = ["## Scores", ""]
    new_lines.append(f"- user_rating: {rating}")
    if notes:
        new_lines.append(f"- user_notes: {notes}")

    result = before_scores + "\n\n" + "\n".join(new_lines) + "\n"
    snapshot_path.write_text(result, encoding="utf-8")
    log.info("Rating saved: %s = %d stars", snapshot_path.name, rating)


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


def _run_generation(
    md_path: Path, count: int, best: int | None, score: bool,
    output_dir: Path, project_root: Path,
) -> None:
    """Run generation in background."""
    from songmaker_cli.generate import run_generate

    run_generate(
        str(md_path), count=count, best=best, score=score,
    )
    log.info("Generation complete: %s", md_path.name)


def _load_meta_for_mp3(mp3_path: Path, project_root: Path) -> Any:
    """Try to find and parse the lyrics source for an MP3."""
    from songmaker_cli.check import find_lyrics_source
    from songmaker_cli.parser import parse_song_md

    try:
        md_path = find_lyrics_source(mp3_path, None, project_root=str(project_root))
        return parse_song_md(md_path)
    except Exception:
        return None


def run_server(
    output_dir: Path | None = None,
    project_root: Path | None = None,
    port: int = 8080,
    open_browser: bool = False,
) -> None:
    """Start the songmaker server."""
    import uvicorn

    if project_root is None:
        project_root = find_project_root(Path.cwd()) or Path.cwd()
    if output_dir is None:
        output_dir = project_root / OUTPUT_ROOT

    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    generate_player(output_dir, project_root)

    app = create_app(output_dir, project_root)
    log.info("Songmaker server: http://localhost:%d", port)

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
