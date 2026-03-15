"""Lyrics accuracy checking via Whisper transcription."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import find_lyrics_md, parse_song_md, strip_version_suffix

log = logging.getLogger(__name__)


def run_check(
    path: str,
    source: str | None = None,
    whisper_model: str = "small",
) -> None:
    """Transcribe with Whisper and compare to intended lyrics."""
    from difflib import SequenceMatcher

    from songmaker_cli.constants import SIMILARITY_FAIR, SIMILARITY_GOOD
    from songmaker_cli.main import validate_path

    mp3_path = validate_path(path)
    md_path = find_lyrics_source(mp3_path, source)
    meta = parse_song_md(md_path)

    language = meta.generation_params.get("language", "en")
    transcribed, segments = _transcribe(mp3_path, language, whisper_model)

    clean_intended = clean_lyrics(meta.lyrics)
    clean_transcribed = clean_lyrics(transcribed)
    ratio = SequenceMatcher(None, clean_intended, clean_transcribed).ratio()

    intended_lines = [
        line.strip() for line in meta.lyrics.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    trans_lines = [s["text"].strip() for s in segments if s["text"].strip()]

    _log_check_results(
        mp3_path, md_path, ratio, intended_lines, trans_lines,
        SIMILARITY_GOOD, SIMILARITY_FAIR,
    )


def find_lyrics_source(mp3_path: Path, source: str | None) -> Path:
    """Find the lyrics markdown file for a given MP3."""
    if source:
        md_path = Path(source).resolve()
        if md_path.exists():
            return md_path

    stem = strip_version_suffix(mp3_path.stem)

    search_roots = []
    output_parent = mp3_path.resolve().parent.parent
    if (output_parent.parent / "albums").is_dir():
        search_roots.append(output_parent.parent / "albums")
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


def clean_lyrics(text: str) -> str:
    """Strip section tags and normalize whitespace for comparison."""
    text = re.sub(r"\[.*?\]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _transcribe(
    mp3_path: Path, language: str, model_size: str = "small",
) -> tuple[str, list[dict]]:
    import whisper

    log.info("Loading Whisper model (%s)...", model_size)
    model = whisper.load_model(model_size)
    log.info("Transcribing %s...", mp3_path.name)
    result = model.transcribe(
        str(mp3_path), language=language, fp16=False,
        condition_on_previous_text=False,
    )
    return result["text"].strip(), result.get("segments", [])


def _log_check_results(
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
