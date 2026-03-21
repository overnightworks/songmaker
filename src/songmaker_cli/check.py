"""Lyrics accuracy checking via Whisper transcription.

Thin CLI wrapper around scoring.text_accuracy. Provides verbose output
with side-by-side intended vs transcribed lines. For programmatic use,
call scoring.text_accuracy.score_text_accuracy() directly.
"""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.config import find_project_root, validate_path
from songmaker_cli.constants import SIMILARITY_FAIR, SIMILARITY_GOOD
from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import find_lyrics_md, parse_song_md, strip_version_suffix

log = logging.getLogger(__name__)


def run_check(
    path: str,
    source: str | None = None,
    project_root: str | None = None,
    whisper_model: str = "medium",
) -> None:
    """Transcribe with Whisper and compare to intended lyrics."""
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    mp3_path = validate_path(path)
    md_path = find_lyrics_source(mp3_path, source, project_root=project_root)
    meta = parse_song_md(md_path)

    from songmaker_cli.scoring.pipeline import PipelineConfig

    result = score_text_accuracy(mp3_path, meta=meta, config=PipelineConfig(whisper_model=whisper_model))

    log_check_results(
        mp3_path, md_path, result.similarity_ratio,
        list(result.intended_line_texts), result.transcribed_lines,
        SIMILARITY_GOOD, SIMILARITY_FAIR,
    )


def find_lyrics_source(
    mp3_path: Path,
    source: str | None,
    project_root: str | None = None,
) -> Path:
    """Find the lyrics markdown file for a given MP3."""
    if source:
        md_path = Path(source).resolve()
        if not md_path.exists():
            raise ValidationError(f"Lyrics source not found: {md_path}")
        return md_path

    stem = strip_version_suffix(mp3_path.stem)

    search_roots: list[Path] = []

    if project_root:
        explicit_root = Path(project_root).resolve()
        if (explicit_root / "albums").is_dir():
            search_roots.append(explicit_root / "albums")

    detected_root = find_project_root(mp3_path)
    if detected_root and (detected_root / "albums").is_dir():
        candidate = detected_root / "albums"
        if candidate not in search_roots:
            search_roots.append(candidate)

    output_parent = mp3_path.resolve().parent.parent
    if (output_parent.parent / "albums").is_dir():
        candidate = output_parent.parent / "albums"
        if candidate not in search_roots:
            search_roots.append(candidate)

    cwd_albums = Path.cwd() / "albums"
    if cwd_albums.is_dir() and cwd_albums not in search_roots:
        search_roots.append(cwd_albums)

    for albums_dir in search_roots:
        for album_dir in albums_dir.iterdir():
            lyrics_dir = album_dir / "lyrics"
            if not lyrics_dir.is_dir():
                continue
            found = find_lyrics_md(stem, lyrics_dir)
            if found:
                return found

    raise ValidationError(
        f"Could not find lyrics source for {mp3_path.name}. Use --source."
    )


def log_check_results(
    mp3_path: Path,
    md_path: Path,
    ratio: float,
    intended_lines: list[str],
    transcribed_count: int,
    good_threshold: float,
    fair_threshold: float,
) -> None:
    log.info("=" * 60)
    log.info("  Lyrics Check: %s", mp3_path.name)
    log.info("  Source: %s", md_path.name)
    log.info("  Overall similarity: %.0f%%", ratio * 100)
    log.info("  Intended lines: %d", len(intended_lines))
    log.info("  Transcribed segments: %d", transcribed_count)
    log.info("=" * 60)

    log.info("  INTENDED:")
    for line in intended_lines:
        log.info("    %s", line)

    log.info("  SIMILARITY: %.0f%%", ratio * 100)
    if ratio >= good_threshold:
        log.info("  VERDICT: Good")
    elif ratio >= fair_threshold:
        log.info("  VERDICT: Needs improvement — consider regenerating")
    else:
        log.info("  VERDICT: Poor — lyrics mostly not understood")
