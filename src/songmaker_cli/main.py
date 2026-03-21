"""Songmaker CLI — thin adapter between cyclopts and engine modules."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

from cyclopts import App, Parameter

from songmaker_cli.config import find_project_root, validate_path
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.errors import SongmakerError, ValidationError
from songmaker_cli.generate import GenerationOptions, open_player, run_generate
from songmaker_cli.player import generate_player

log = logging.getLogger(__name__)

app = App(name="songmaker", help="Generate songs from markdown files.")


@app.meta.default
def _launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    verbose: Annotated[bool, Parameter(name=["-v", "--verbose"], help="Debug logging")] = False,
    quiet: Annotated[bool, Parameter(name=["-q", "--quiet"], help="Errors only")] = False,
) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(name)s: %(message)s")
    app(tokens)


@app.command
def generate(
    path: Annotated[str, Parameter(help="Path to song .md file")],
    seed: Annotated[Optional[int], Parameter(help="Random seed")] = None,
    count: Annotated[int, Parameter(help="Number of versions to generate")] = 1,
    duration: Annotated[Optional[int], Parameter(help="Duration in seconds")] = None,
    bpm: Annotated[Optional[int], Parameter(help="Tempo in BPM")] = None,
    key: Annotated[Optional[str], Parameter(help="Musical key")] = None,
    shift: Annotated[Optional[float], Parameter(help="Flow matching shift")] = None,
    guidance_scale: Annotated[Optional[float], Parameter(help="CFG strength")] = None,
    inference_steps: Annotated[Optional[int], Parameter(help="Denoising steps")] = None,
    lm_temperature: Annotated[Optional[float], Parameter(help="LM temperature")] = None,
    infer_method: Annotated[Optional[str], Parameter(help="ode or sde")] = None,
    think_mode: Annotated[Optional[bool], Parameter(help="LM chain-of-thought")] = None,
    check: Annotated[bool, Parameter(help="Run Whisper check after")] = False,
    score: Annotated[bool, Parameter(help="Run scoring pipeline after")] = False,
    best: Annotated[
        Optional[int], Parameter(help="Generate N, score all, rank by dynamics"),
    ] = None,
    player: Annotated[
        bool, Parameter(name="--player", help="Open HTML player after generation"),
    ] = False,
) -> None:
    """Generate a song from a markdown file via ACE-Step."""
    opts = GenerationOptions(
        seed=seed, count=count, duration=duration, bpm=bpm, key=key,
        shift=shift, guidance_scale=guidance_scale,
        inference_steps=inference_steps, lm_temperature=lm_temperature,
        infer_method=infer_method, think_mode=think_mode,
        check=check, score=score, best=best, player=player,
    )
    run_generate(path, opts)


@app.command
def player(
    output: Annotated[
        str, Parameter(name=["-o", "--output"], help="Output directory")
    ] = "",
    root: Annotated[
        Optional[str], Parameter(help="Project root")
    ] = None,
    open_browser: Annotated[
        bool, Parameter(name="--open", help="Open player in browser")
    ] = False,
) -> None:
    """Generate the unified HTML player for all albums."""
    if output:
        output_dir = Path(output).resolve()
    else:
        project_root_found = find_project_root(Path.cwd())
        output_dir = (project_root_found / OUTPUT_ROOT if project_root_found
                      else Path(OUTPUT_ROOT)).resolve()

    if not output_dir.exists():
        raise ValidationError(f"{output_dir} not found")

    project_root = Path(root).resolve() if root else None
    player_path = generate_player(output_dir, project_root)
    log.info("Player generated: %s", player_path)

    if open_browser:
        open_player(player_path)


@app.command
def score(
    path: Annotated[Optional[str], Parameter(help="MP3 file to score")] = None,
    source: Annotated[
        Optional[str], Parameter(help="Lyrics .md file for text accuracy")
    ] = None,
    scorers: Annotated[
        Optional[str], Parameter(help="Comma-separated scorer names, or 'all'")
    ] = None,
    whisper_model: Annotated[
        str, Parameter(help="Whisper model size (base/small/medium/large)")
    ] = "medium",
    all: Annotated[
        bool, Parameter(name="--all", help="Score all MP3s in _output/")
    ] = False,
    force: Annotated[
        bool, Parameter(help="Re-score even if already scored")
    ] = False,
    device: Annotated[
        str, Parameter(help="Device for scoring models (cpu/cuda)")
    ] = "cpu",
) -> None:
    """Score a generated song on quality dimensions."""
    from songmaker_cli.scoring.pipeline import PipelineConfig

    scorer_list = None
    if scorers and scorers != "all":
        scorer_list = [s.strip() for s in scorers.split(",")]
    config = PipelineConfig(whisper_model=whisper_model, device=device)

    if all:
        from songmaker_cli.batch import score_all

        score_all(scorer_list, config, force)
        return

    if path is None:
        raise ValidationError("Provide an MP3 path or use --all")

    from songmaker_cli.batch import score_single

    score_single(path, source, scorer_list, config)


@app.command
def archive(
    path: Annotated[Optional[str], Parameter(help="MP3 file to archive")] = None,
    below: Annotated[
        Optional[float],
        Parameter(help="Archive all versions with dynamics below this value"),
    ] = None,
) -> None:
    """Move bad versions to _archive/ instead of deleting.

    Preserves MP3 + snapshot .md for future preference model training.
    """
    from songmaker_cli.archive import archive_below_threshold, archive_file
    from songmaker_cli.snapshot import read_scores

    project_root = find_project_root(Path.cwd()) or Path.cwd()
    output_dir = project_root / OUTPUT_ROOT
    archive_dir = project_root / "_archive"

    if path:
        mp3_path = validate_path(path)
        archive_file(mp3_path, archive_dir)
    elif below is not None:
        archive_below_threshold(below, output_dir, archive_dir, read_scores)
    else:
        raise ValidationError("Provide an MP3 path or use --below <threshold>")

    generate_player(output_dir, project_root)
    log.info("Player updated")


@app.command
def check(
    path: Annotated[str, Parameter(help="MP3 file to check")],
    source: Annotated[
        Optional[str], Parameter(help="Lyrics .md file")
    ] = None,
    project_root: Annotated[
        Optional[str], Parameter(help="Project root for finding lyrics")
    ] = None,
    whisper_model: Annotated[
        str, Parameter(help="Whisper model size (base/small/medium/large)")
    ] = "medium",
) -> None:
    """Check lyrics accuracy via Whisper transcription.

    Without --source, searches for lyrics in order:
    1. --project-root/albums/*/lyrics/
    2. Detected project root (via pyproject.toml) albums/*/lyrics/
    3. MP3 parent's grandparent/albums/*/lyrics/
    4. cwd/albums/*/lyrics/
    """
    from songmaker_cli.check import run_check

    run_check(path, source, project_root=project_root, whisper_model=whisper_model)


@app.command
def server(
    port: Annotated[int, Parameter(help="Server port")] = 8080,
    output: Annotated[
        str, Parameter(name=["-o", "--output"], help="Output directory")
    ] = "",
    root: Annotated[
        Optional[str], Parameter(help="Project root")
    ] = None,
    open_browser: Annotated[
        bool, Parameter(name="--open", help="Open browser on start")
    ] = False,
) -> None:
    """Start the songmaker web server for the player UI."""
    from songmaker_cli.server import run_server

    output_dir = Path(output).resolve() if output else None
    project_root = Path(root).resolve() if root else None
    run_server(
        output_dir=output_dir, project_root=project_root,
        port=port, open_browser=open_browser,
    )


def main() -> None:
    try:
        app.meta()
    except SongmakerError as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
