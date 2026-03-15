"""Songmaker CLI — generate songs from markdown via ACE-Step."""

from __future__ import annotations

import logging
import re
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

from cyclopts import App, Parameter

from songmaker_cli.config import OutputPaths, build_ace_config, resolve_output_paths
from songmaker_cli.errors import GenerationError, SongmakerError, ValidationError
from songmaker_cli.parser import SongMeta, load_album_meta, parse_song_md

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from acestep_engine.models import AceStepConfig, AceStepResult
    from songmaker_cli.parser import AlbumMeta

log = logging.getLogger(__name__)

app = App(name="songmaker", help="Generate songs from markdown files.")


@dataclass(frozen=True)
class DecodedAudio:
    """Stereo audio decoded from ACE-Step WAV bytes."""

    left: NDArray[np.float64]
    right: NDArray[np.float64]
    sample_rate: int
    duration: float


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
    player: Annotated[
        bool, Parameter(name="--player", help="Open HTML player after generation"),
    ] = False,
) -> None:
    """Generate a song from a markdown file via ACE-Step."""
    md_path = validate_path(path)
    meta = parse_song_md(md_path)
    validate_song_meta(meta)

    cli_overrides = collect_overrides(
        seed=seed, duration=duration, bpm=bpm, key=key, shift=shift,
        guidance_scale=guidance_scale, inference_steps=inference_steps,
        lm_temperature=lm_temperature, infer_method=infer_method,
        think_mode=think_mode,
    )
    ace_config = build_ace_config(meta, cli_overrides)
    album_meta = load_album_meta_for_song(md_path)

    player_path = None
    for i in range(count):
        if count > 1:
            log.info("Generation %d/%d", i + 1, count)

        paths = resolve_output_paths(meta.album, md_path.stem)
        _log_generation_banner(meta, paths, ace_config)

        ace_result, elapsed = _run_generation(ace_config)
        audio = _decode_audio(ace_result)
        _write_output(audio, ace_result.seed, paths, meta, album_meta)
        _log_result_banner(paths, audio, ace_result.seed, elapsed)
        player_path = _update_player(paths)

        if check:
            run_check(str(paths.mp3), source=str(md_path))

    if player and player_path:
        _open_player(player_path)


@app.command
def player(
    output: Annotated[
        str, Parameter(name=["-o", "--output"], help="Output directory")
    ] = "_output",
    root: Annotated[
        Optional[str], Parameter(help="Project root")
    ] = None,
    open_browser: Annotated[
        bool, Parameter(name="--open", help="Open player in browser")
    ] = False,
) -> None:
    """Generate the unified HTML player for all albums."""
    from songmaker_cli.player import generate_player

    output_dir = Path(output).resolve()
    if not output_dir.exists():
        raise ValidationError(f"{output_dir} not found")

    project_root = Path(root).resolve() if root else None
    player_path = generate_player(output_dir, project_root)
    log.info("Player generated: %s", player_path)

    if open_browser:
        _open_player(player_path)


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


def validate_path(path: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise ValidationError(f"{resolved} not found")
    return resolved


def validate_song_meta(meta: SongMeta) -> None:
    if not meta.prompt:
        raise ValidationError("No 'prompt' field in frontmatter")
    if not meta.lyrics:
        raise ValidationError("No '## Lyrics' section found")


def collect_overrides(**kwargs: object) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


def load_album_meta_for_song(md_path: Path) -> AlbumMeta:
    album_dir = md_path.parent.parent
    return load_album_meta(album_dir)


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
    from acestep_engine import AceStepClient, AceStepError

    log.info("Generating via ACE-Step...")
    start_time = time.time()
    client = AceStepClient()
    try:
        result: AceStepResult = client.generate(ace_config)
    except AceStepError as exc:
        raise GenerationError(str(exc)) from exc

    return result, time.time() - start_time


def _decode_audio(ace_result: AceStepResult) -> DecodedAudio:
    from audio_engine import read_wav_bytes

    left, right, sample_rate = read_wav_bytes(ace_result.wav_bytes)
    if len(left) == 0:
        raise GenerationError("ACE-Step returned empty or unparseable audio")

    duration = len(left) / sample_rate
    log.info("Audio decoded: %.1fs at %d Hz", duration, sample_rate)
    return DecodedAudio(left=left, right=right, sample_rate=sample_rate, duration=duration)


def _write_output(
    audio: DecodedAudio,
    seed: int,
    paths: OutputPaths,
    meta: SongMeta,
    album_meta: AlbumMeta,
) -> None:
    from audio_engine import MasteringError, master_to_mp3, write_stereo_wav

    write_stereo_wav(str(paths.raw_wav), audio.left, audio.right, audio.sample_rate)

    id3_metadata = {
        "title": meta.title,
        "artist": album_meta.artist,
        "album": album_meta.title,
        "track": meta.track,
        "genre": meta.genre,
        "lyrics": meta.lyrics,
        "comment": f"seed={seed}",
    }
    try:
        master_to_mp3(
            audio.left, audio.right, str(paths.mp3),
            sample_rate=audio.sample_rate, metadata=id3_metadata,
        )
    except MasteringError as exc:
        raise GenerationError(str(exc)) from exc
    paths.raw_wav.unlink(missing_ok=True)


def _log_result_banner(
    paths: OutputPaths, audio: DecodedAudio, seed: int, elapsed: float,
) -> None:
    log.info("=" * 60)
    log.info("  Done: %s", paths.mp3)
    log.info(
        "  Time: %.0fs | Duration: %.1fs | Seed: %s",
        elapsed, audio.duration, seed,
    )
    log.info("=" * 60)


def _update_player(paths: OutputPaths) -> Path:
    from songmaker_cli.player import generate_player

    player_path = generate_player(paths.output_dir.parent)
    log.info("Player updated: %s", player_path)
    return player_path


def _open_player(player_path: Path) -> None:
    url = player_path.resolve().as_uri()
    log.info("Opening player: %s", url)
    webbrowser.open(url)


def run_check(
    path: str,
    source: str | None = None,
    whisper_model: str = "small",
) -> None:
    """Transcribe with Whisper and compare to intended lyrics."""
    from difflib import SequenceMatcher

    from songmaker_cli.constants import SIMILARITY_FAIR, SIMILARITY_GOOD

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
    from songmaker_cli.parser import find_lyrics_md, strip_version_suffix

    if source:
        md_path = Path(source).resolve()
        if md_path.exists():
            return md_path

    stem = strip_version_suffix(mp3_path.stem)

    # Search albums/ relative to the MP3 file's output tree, then CWD
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


def clean_lyrics(text: str) -> str:
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
