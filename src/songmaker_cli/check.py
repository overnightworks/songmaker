"""Lyrics accuracy checking via Whisper transcription.

Thin CLI wrapper around scoring.text_accuracy. This module handles source
file discovery and verbose logging; the scorer does the actual analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.config import find_project_root, validate_path
from songmaker_cli.constants import SIMILARITY_FAIR, SIMILARITY_GOOD
from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import find_lyrics_md, parse_song_md, strip_version_suffix
from songmaker_cli.scoring.text_accuracy import (
    _get_whisper_model,
    _transcribe,
    clean_lyrics,
)

log = logging.getLogger(__name__)


def run_check(
    path: str,
    source: str | None = None,
    project_root: str | None = None,
    whisper_model: str = "small",
    model: object | None = None,
) -> None:
    """Transcribe with Whisper and compare to intended lyrics.

    This is the verbose CLI version — logs intended vs transcribed lines.
    For programmatic use, call scoring.text_accuracy.score_text_accuracy().
    """
    from difflib import SequenceMatcher

    mp3_path = validate_path(path)
    md_path = find_lyrics_source(mp3_path, source, project_root=project_root)
    meta = parse_song_md(md_path)

    language = meta.generation_params.get("language", "en")
    if model is None:
        model = _get_whisper_model(whisper_model)
    transcribed, segments = _transcribe(mp3_path, language, model)

    clean_intended = clean_lyrics(meta.lyrics)
    clean_transcribed = clean_lyrics(transcribed)
    ratio = SequenceMatcher(None, clean_intended, clean_transcribed).ratio()

    intended_lines = [
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    trans_lines = [s.get("text", "").strip() for s in segments if s.get("text", "").strip()]

    log_check_results(
        mp3_path, md_path, ratio, intended_lines, trans_lines,
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
    trans_lines: list[str],
    good_threshold: float,
    fair_threshold: float,
) -> None:
    log.info("=" * 60)
    log.info("  Lyrics Check: %s", mp3_path.name)
    log.info("  Source: %s", md_path.name)
    log.info("  Overall similarity: %.0f%%", ratio * 100)
    log.info("  Intended lines: %d", len(intended_lines))
    log.info("  Transcribed segments: %d", len(trans_lines))
    log.info("=" * 60)

    log.info("  INTENDED:")
    for line in intended_lines:
        log.info("    %s", line)

    log.info("  TRANSCRIBED:")
    for line in trans_lines:
        log.info("    %s", line)

    log.info("  SIMILARITY: %.0f%%", ratio * 100)
    if ratio >= good_threshold:
        log.info("  VERDICT: Good")
    elif ratio >= fair_threshold:
        log.info("  VERDICT: Needs improvement — consider regenerating")
    else:
        log.info("  VERDICT: Poor — lyrics mostly not understood")
