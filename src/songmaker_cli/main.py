"""Songmaker CLI — generate songs from markdown via ACE-Step."""

from __future__ import annotations

import logging
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
            from songmaker_cli.check import run_check

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
    from songmaker_cli.check import run_check

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


def main() -> None:
    try:
        app()
    except SongmakerError as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
