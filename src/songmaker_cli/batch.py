"""Batch scoring — score all MP3s in _output/."""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.config import find_project_root, validate_path
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.errors import ValidationError
from songmaker_cli.generate import log_scores
from songmaker_cli.scoring import run_scoring_pipeline
from songmaker_cli.snapshot import append_scores_section, read_scores

log = logging.getLogger(__name__)


def score_single(
    path: str,
    source: str | None,
    scorer_list: list[str] | None,
    config: object,
) -> None:
    """Score a single MP3 file."""
    from songmaker_cli.parser import parse_song_md

    mp3_path = validate_path(path)
    meta = None
    if source:
        meta = parse_song_md(validate_path(source))

    scores = run_scoring_pipeline(mp3_path, meta=meta, scorers=scorer_list, config=config)
    log_scores(scores)


def score_all(
    scorer_list: list[str] | None,
    config: object,
    force: bool,
) -> None:
    """Score all MP3s in _output/, skipping already-scored unless force=True."""
    from songmaker_cli.check import find_lyrics_source
    from songmaker_cli.parser import parse_song_md

    project_root = find_project_root(Path.cwd()) or Path.cwd()
    output_dir = project_root / OUTPUT_ROOT

    if not output_dir.exists():
        raise ValidationError(f"No output directory: {output_dir}")

    mp3s = sorted(output_dir.rglob("*.mp3"))
    if not mp3s:
        log.info("No MP3s found in %s", output_dir)
        return

    log.info("Scoring %d MP3s...", len(mp3s))
    scored = 0
    skipped = 0

    for mp3 in mp3s:
        snapshot_path = mp3.with_suffix(".md")

        if not force and snapshot_path.exists():
            existing = read_scores(snapshot_path)
            if existing and "dynamics" in existing:
                skipped += 1
                continue

        meta = None
        try:
            md_path = find_lyrics_source(mp3, None, project_root=str(project_root))
            meta = parse_song_md(md_path)
        except Exception:
            pass

        log.info("[%d/%d] %s", scored + skipped + 1, len(mp3s), mp3.name)
        scores = run_scoring_pipeline(mp3, meta=meta, scorers=scorer_list, config=config)

        if snapshot_path.exists():
            append_scores_section(snapshot_path, scores)

        log_scores(scores)
        scored += 1

    log.info("Done: %d scored, %d skipped (already scored)", scored, skipped)

    from songmaker_cli.player import generate_player

    generate_player(output_dir, project_root)
    log.info("Player updated")
