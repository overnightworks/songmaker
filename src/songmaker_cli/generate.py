"""Generation orchestration — generate, decode, master, and write output."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from acestep_engine import AceStepClient, AceStepError
from acestep_engine.models import AceStepConfig, AceStepResult
from audio_engine import MasteringError, master_to_mp3, read_wav_bytes, write_stereo_wav
from songmaker_cli.config import (
    OutputPaths,
    build_ace_config,
    find_project_root,
    resolve_output_paths,
    validate_path,
)
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.errors import GenerationError, ValidationError
from songmaker_cli.parser import AlbumMeta, SongMeta, load_album_meta, parse_song_md
from songmaker_cli.snapshot import write_snapshot

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecodedAudio:
    """Stereo audio decoded from ACE-Step WAV bytes."""

    left: NDArray[np.float64]
    right: NDArray[np.float64]
    sample_rate: int
    duration: float


def validate_song_meta(meta: SongMeta) -> None:
    if not meta.prompt:
        raise ValidationError("No 'prompt' field in frontmatter")
    if not meta.lyrics:
        raise ValidationError("No '## Lyrics' section found")


@dataclass(frozen=True)
class GenerationOptions:
    """CLI-level options for a generation run."""

    seed: int | None = None
    count: int = 1
    duration: int | None = None
    bpm: int | None = None
    key: str | None = None
    shift: float | None = None
    guidance_scale: float | None = None
    inference_steps: int | None = None
    lm_temperature: float | None = None
    infer_method: str | None = None
    think_mode: bool | None = None
    player: bool = False

    def ace_overrides(self) -> dict[str, object]:
        """Return non-None ACE-Step parameter overrides."""
        return {
            k: v for k, v in {
                "seed": self.seed, "duration": self.duration, "bpm": self.bpm,
                "key": self.key, "shift": self.shift,
                "guidance_scale": self.guidance_scale,
                "inference_steps": self.inference_steps,
                "lm_temperature": self.lm_temperature,
                "infer_method": self.infer_method, "think_mode": self.think_mode,
            }.items() if v is not None
        }


def load_album_meta_for_song(
    md_path: Path,
    album_name: str = "",
    project_root: Path | None = None,
) -> AlbumMeta:
    """Load album metadata for a song, using album name to locate album.yaml.

    Searches: project_root/albums/<album>/ first, then falls back to
    md_path.parent.parent (the conventional lyrics dir layout).
    """
    if album_name and project_root:
        candidate = project_root / "albums" / album_name
        if candidate.is_dir():
            return load_album_meta(candidate)

    album_dir = md_path.parent.parent
    return load_album_meta(album_dir)


def run_generate(path: str, opts: GenerationOptions | None = None) -> None:
    """Generate a song from a markdown file via ACE-Step."""
    if opts is None:
        opts = GenerationOptions()

    md_path = validate_path(path)
    meta = parse_song_md(md_path)
    validate_song_meta(meta)

    client = AceStepClient()
    server_info = client.server_info()
    model_name = server_info.model if server_info else None
    ace_config = build_ace_config(meta, opts.ace_overrides(), model_name=model_name)

    project_root = find_project_root(md_path)
    album_meta = load_album_meta_for_song(md_path, meta.album, project_root=project_root)
    output_root = (project_root / OUTPUT_ROOT) if project_root else None

    generated = _generate_versions(
        opts.count, md_path, meta, album_meta, ace_config, output_root,
        client=client, server_info=server_info,
    )

    if generated:
        log.info("Generation complete — %d version(s)", len(generated))


def _generate_versions(
    count: int,
    md_path: Path,
    meta: SongMeta,
    album_meta: AlbumMeta,
    ace_config: AceStepConfig,
    output_root: Path | None,
    client: AceStepClient | None = None,
    server_info: object = None,
) -> list[tuple[OutputPaths, Path]]:
    """Run N generation cycles and return (paths, snapshot_path) per version."""
    if client is None:
        client = AceStepClient()
    if not client.is_available:
        raise GenerationError("ACE-Step server is not reachable")
    if server_info is None:
        server_info = client.server_info()
    generated: list[tuple[OutputPaths, Path]] = []

    for i in range(count):
        if count > 1:
            log.info("Generation %d/%d", i + 1, count)

        paths = resolve_output_paths(meta.album, md_path.stem, output_root=output_root)
        _log_generation_banner(meta, paths, ace_config)

        ace_result, elapsed = _run_generation(ace_config, client)
        audio = _decode_audio(ace_result)
        _write_output(audio, ace_result.seed, paths, meta, album_meta)
        write_snapshot(md_path, paths, ace_config, ace_result.seed, server_info)
        _log_result_banner(paths, audio, ace_result.seed, elapsed)

        generated.append((paths, paths.mp3.with_suffix(".md")))

    return generated


@dataclass(frozen=True)
class GenerationResult:
    """Result of a single generation cycle."""

    mp3_path: Path
    seed: int
    duration: float
    output_paths: OutputPaths


def generate_single(
    meta: SongMeta,
    album_meta: AlbumMeta,
    ace_config: AceStepConfig,
    output_root: Path,
    client: AceStepClient | None = None,
) -> GenerationResult:
    """Generate a single MP3 from config. Returns paths and metadata."""
    if client is None:
        client = AceStepClient()
    if not client.is_available:
        raise GenerationError("ACE-Step server is not reachable")

    base_name = meta.title.lower().replace(" ", "_")
    paths = resolve_output_paths(meta.album, base_name, output_root=output_root)
    ace_result, elapsed = _run_generation(ace_config, client)
    audio = _decode_audio(ace_result)
    _write_output(audio, ace_result.seed, paths, meta, album_meta)

    log.info("Generated: %s (seed=%s, %.0fs)", paths.mp3.name, ace_result.seed, elapsed)
    return GenerationResult(
        mp3_path=paths.mp3,
        seed=ace_result.seed,
        duration=audio.duration,
        output_paths=paths,
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


def _run_generation(
    ace_config: AceStepConfig, client: AceStepClient,
) -> tuple[AceStepResult, float]:
    log.info("Generating via ACE-Step...")
    start_time = time.time()
    try:
        result: AceStepResult = client.generate(ace_config)
    except AceStepError as exc:
        raise GenerationError(str(exc)) from exc

    return result, time.time() - start_time


def _decode_audio(ace_result: AceStepResult) -> DecodedAudio:
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


