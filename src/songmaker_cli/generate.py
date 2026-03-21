"""Generation orchestration — generate, score, rank, and write output."""

from __future__ import annotations

import logging
import time
import webbrowser
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
from songmaker_cli.player import generate_player
from songmaker_cli.snapshot import append_scores_section, write_snapshot

if __name__ != "__main__":
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from songmaker_cli.scoring import SongScores

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
    check: bool = False
    score: bool = False
    best: int | None = None
    player: bool = False

    def ace_overrides(self) -> dict:
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

    count = opts.count
    do_score = opts.score
    if opts.best is not None:
        count = opts.best
        do_score = True

    ace_config = build_ace_config(meta, opts.ace_overrides())

    project_root = find_project_root(md_path)
    album_meta = load_album_meta_for_song(md_path, meta.album, project_root=project_root)
    output_root = (project_root / OUTPUT_ROOT) if project_root else None

    generated = _generate_versions(
        count, md_path, meta, album_meta, ace_config, output_root,
        score_each=(do_score and opts.best is None), check_each=opts.check,
    )

    if opts.best is not None:
        _score_and_rank(generated, meta)

    if generated:
        last_paths = generated[-1][0]
        player_path = _update_player(last_paths)
        if opts.player:
            open_player(player_path)


def _generate_versions(
    count: int,
    md_path: Path,
    meta: SongMeta,
    album_meta: AlbumMeta,
    ace_config: AceStepConfig,
    output_root: Path | None,
    score_each: bool,
    check_each: bool,
) -> list[tuple[OutputPaths, Path]]:
    """Run N generation cycles and return (paths, snapshot_path) per version."""
    client = AceStepClient()
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
        snapshot_path = write_snapshot(md_path, paths, ace_config, ace_result.seed, server_info)
        _log_result_banner(paths, audio, ace_result.seed, elapsed)

        if score_each:
            from songmaker_cli.scoring import run_scoring_pipeline

            scores = run_scoring_pipeline(paths.mp3, meta=meta)
            append_scores_section(snapshot_path, scores)
            log_scores(scores)

        if check_each:
            from songmaker_cli.check import run_check

            run_check(str(paths.mp3), source=str(md_path))

        generated.append((paths, snapshot_path))

    return generated


def _score_and_rank(
    generated: list[tuple[OutputPaths, Path]], meta: SongMeta,
) -> None:
    """Score all generated versions and log a ranked table."""
    from songmaker_cli.scoring import run_scoring_pipeline

    log.info("")
    log.info("Scoring %d versions...", len(generated))
    ranked: list[tuple[OutputPaths, SongScores]] = []
    for paths, snapshot_path in generated:
        scores = run_scoring_pipeline(paths.mp3, meta=meta)
        append_scores_section(snapshot_path, scores)
        log_scores(scores)
        ranked.append((paths, scores))
    _log_ranking_by_dynamics(ranked)


def log_scores(scores: SongScores) -> None:
    log.info("=" * 60)
    log.info("  Scores")
    for name, value in scores.to_dict().items():
        log.info("    %s: %s", name, value)
    if scores.silence and scores.silence.has_problems:
        log.warning("  Silence gaps detected (%d gaps, longest %.1fs)",
                     scores.silence.gap_count, scores.silence.longest_gap_seconds)
    log.info("=" * 60)


def _log_ranking_by_dynamics(ranked: list[tuple[OutputPaths, SongScores]]) -> None:
    """Log a ranked table of scored versions, sorted by emotional dynamics."""

    def _sort_key(entry: tuple[OutputPaths, SongScores]) -> float:
        _, scores = entry
        if scores.emotional_dynamics:
            return scores.emotional_dynamics.overall_expressiveness
        return 0.0

    sorted_entries = sorted(ranked, key=_sort_key, reverse=True)

    log.info("")
    log.info("=" * 70)
    log.info("  RANKING (%d versions)", len(sorted_entries))
    log.info("  %-30s %10s %10s %10s", "Version", "Dynamics", "AB Quality", "Silence")
    log.info("  " + "-" * 66)

    for i, (paths, scores) in enumerate(sorted_entries):
        dynamics = (
            round(scores.emotional_dynamics.overall_expressiveness * 100, 1)
            if scores.emotional_dynamics else "-"
        )
        ab_quality = round(scores.audiobox.production_quality, 1) if scores.audiobox else "-"
        has_gaps = scores.silence.has_problems if scores.silence else False
        flag = " [gaps]" if has_gaps else ""
        marker = " <-- best" if i == 0 else ""
        log.info("  %-30s %10s %10s %10s%s",
                 paths.versioned_name, dynamics, ab_quality, not has_gaps, flag + marker)

    log.info("=" * 70)
    best_paths = sorted_entries[0][0]
    log.info("  Best: %s", best_paths.mp3)
    log.info("")


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


def _update_player(paths: OutputPaths) -> Path:
    player_path = generate_player(paths.output_dir.parent)
    log.info("Player updated: %s", player_path)
    return player_path


def open_player(player_path: Path) -> None:
    url = player_path.resolve().as_uri()
    log.info("Opening player: %s", url)
    webbrowser.open(url)
