"""Songmaker CLI — generate songs from markdown via ACE-Step."""

from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

from cyclopts import App, Parameter

from songmaker_cli.config import OutputPaths, build_ace_config, resolve_output_paths
from songmaker_cli.constants import DEFAULT_ARTIST, NORMALIZE_PEAK
from songmaker_cli.errors import GenerationError, SongmakerError, ValidationError
from songmaker_cli.parser import AlbumMeta, SongMeta, parse_album_yaml, parse_song_md

if TYPE_CHECKING:
    from acestep_engine.models import AceStepConfig, AceStepResult

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
log = logging.getLogger(__name__)

app = App(name="songmaker", help="Generate songs from markdown files.")


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
) -> None:
    """Generate a song from a markdown file via ACE-Step."""
    md_path = _validate_path(path)
    meta = parse_song_md(md_path)
    _validate_song_meta(meta)

    cli_overrides = _collect_overrides(
        seed=seed, duration=duration, bpm=bpm, key=key, shift=shift,
        guidance_scale=guidance_scale, inference_steps=inference_steps,
        lm_temperature=lm_temperature, infer_method=infer_method,
        think_mode=think_mode,
    )
    ace_config = build_ace_config(meta, cli_overrides)
    album_meta = _load_album_meta(md_path)

    for i in range(count):
        if count > 1:
            log.info("Generation %d/%d", i + 1, count)

        paths = resolve_output_paths(meta.album, md_path.stem)
        _log_generation_banner(meta, paths, ace_config)

        result, elapsed = _run_generation(ace_config)
        _write_output(result, paths, meta, album_meta)
        _log_result_banner(paths, result, elapsed)
        _update_player(paths)

        if check:
            run_check(str(paths.mp3), source=str(md_path))


@app.command
def player(
    output: Annotated[
        str, Parameter(name=["-o", "--output"], help="Output directory")
    ] = "_output",
    root: Annotated[
        Optional[str], Parameter(help="Project root")
    ] = None,
) -> None:
    """Generate the unified HTML player for all albums."""
    from songmaker_cli.player import generate_player

    output_dir = Path(output).resolve()
    if not output_dir.exists():
        raise ValidationError(f"{output_dir} not found")

    project_root = Path(root).resolve() if root else None
    player_path = generate_player(output_dir, project_root)
    log.info("Player generated: %s", player_path)


@app.command
def check(
    path: Annotated[str, Parameter(help="MP3 file to check")],
    source: Annotated[
        Optional[str], Parameter(help="Lyrics .md file")
    ] = None,
    whisper_model: Annotated[
        str, Parameter(help="Whisper model size (base/small/medium/large)")
    ] = "small",
) -> None:
    """Check lyrics accuracy via Whisper transcription."""
    run_check(path, source, whisper_model=whisper_model)


def _validate_path(path: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise ValidationError(f"{resolved} not found")
    return resolved


def _validate_song_meta(meta: SongMeta) -> None:
    if not meta.prompt:
        raise ValidationError("No 'prompt' field in frontmatter")
    if not meta.lyrics:
        raise ValidationError("No '## Lyrics' section found")


def _collect_overrides(**kwargs: object) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


def _load_album_meta(md_path: Path) -> AlbumMeta:
    album_yaml = md_path.parent.parent / "album.yaml"
    if album_yaml.exists():
        return parse_album_yaml(album_yaml)
    album_name = md_path.parent.parent.name
    return AlbumMeta(
        title=album_name.replace("_", " ").title(),
        artist=DEFAULT_ARTIST,
    )


def _log_generation_banner(
    meta: SongMeta, paths: OutputPaths, ace_config: AceStepConfig,
) -> None:
    log.info("=" * 60)
    log.info("  %s — v%d", meta.title, paths.version)
    log.info(
        "  %s BPM | %s | %ds",
        ace_config.bpm, ace_config.key or "—", ace_config.duration,
    )
    log.info("  Album: %s", meta.album)
    log.info("=" * 60)


def _run_generation(ace_config: AceStepConfig) -> tuple[AceStepResult, float]:
    from acestep_engine import AceStepClient

    log.info("Generating via ACE-Step...")
    start_time = time.time()
    client = AceStepClient()
    result: AceStepResult = client.generate(ace_config)
    if result is None:
        raise GenerationError("ACE-Step generation failed")

    return result, time.time() - start_time


def _write_output(
    result: AceStepResult,
    paths: OutputPaths,
    meta: SongMeta,
    album_meta: AlbumMeta,
) -> None:
    from audio_engine.audio_io import master_to_mp3, normalize_audio, write_wav_file

    write_wav_file(str(paths.raw_wav), result.samples)
    samples = normalize_audio(result.samples, NORMALIZE_PEAK)
    write_wav_file(str(paths.wav), samples)

    id3_metadata = {
        "title": meta.title,
        "artist": album_meta.artist,
        "album": album_meta.title,
        "track": meta.track,
        "genre": meta.genre,
        "lyrics": meta.lyrics,
    }
    if master_to_mp3(str(paths.wav), str(paths.mp3), metadata=id3_metadata):
        paths.wav.unlink(missing_ok=True)
        paths.raw_wav.unlink(missing_ok=True)


def _log_result_banner(
    paths: OutputPaths, result: AceStepResult, elapsed: float,
) -> None:
    log.info("=" * 60)
    log.info("  Done: %s", paths.mp3)
    log.info(
        "  Time: %.0fs | Duration: %.1fs | Seed: %s",
        elapsed, result.duration, result.seed,
    )
    log.info("=" * 60)


def _update_player(paths: OutputPaths) -> None:
    from songmaker_cli.player import generate_player

    player_path = generate_player(paths.output_dir.parent)
    log.info("Player updated: %s", player_path)


def run_check(
    path: str,
    source: str | None = None,
    whisper_model: str = "small",
) -> None:
    """Transcribe with Whisper and compare to intended lyrics."""
    from difflib import SequenceMatcher

    from songmaker_cli.constants import SIMILARITY_FAIR, SIMILARITY_GOOD

    mp3_path = _validate_path(path)
    md_path = _find_lyrics_source(mp3_path, source)
    meta = parse_song_md(md_path)

    language = meta.generation_params.get("language", "en")
    transcribed, segments = _transcribe(mp3_path, language, whisper_model)

    clean_intended = _clean_lyrics(meta.lyrics)
    clean_transcribed = _clean_lyrics(transcribed)
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


def _find_lyrics_source(mp3_path: Path, source: str | None) -> Path:
    if source:
        md_path = Path(source).resolve()
        if md_path.exists():
            return md_path

    base = re.sub(r"_v\d+$", "", mp3_path.stem)
    albums_dir = Path("albums")
    if albums_dir.is_dir():
        for album_dir in albums_dir.iterdir():
            candidate = album_dir / "lyrics" / f"{base}.md"
            if candidate.exists():
                return candidate

    raise ValidationError(
        f"Could not find lyrics source for {mp3_path.name}. Use --source."
    )


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


def _clean_lyrics(text: str) -> str:
    text = re.sub(r"\[.*?\]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


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


def main() -> None:
    try:
        app()
    except SongmakerError as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
