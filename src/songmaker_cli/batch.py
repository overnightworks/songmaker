"""Scoring orchestration — single, batch, and ranked scoring."""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.config import OutputPaths, find_project_root, validate_path
from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.errors import ValidationError
from songmaker_cli.parser import SongMeta, parse_song_md
from songmaker_cli.scoring import run_scoring_pipeline
from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.pipeline import PipelineConfig
from songmaker_cli.snapshot import append_scores_section, read_scores

log = logging.getLogger(__name__)


# ── Score logging ────────────────────────────────────────────────────


def log_scores(scores: SongScores) -> None:
    log.info("=" * 60)
    log.info("  Scores")
    for name, value in scores.to_dict().items():
        log.info("    %s: %s", name, value)
    if scores.silence and scores.silence.has_problems:
        log.warning(
            "  Silence gaps detected (%d gaps, longest %.1fs)",
            scores.silence.gap_count, scores.silence.longest_gap_seconds,
        )
    log.info("=" * 60)


def log_ranking(ranked: list[tuple[OutputPaths, SongScores]]) -> None:
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
        log.info(
            "  %-30s %10s %10s %10s%s",
            paths.versioned_name, dynamics, ab_quality, not has_gaps, flag + marker,
        )

    log.info("=" * 70)
    best_paths = sorted_entries[0][0]
    log.info("  Best: %s", best_paths.mp3)
    log.info("")


# ── Score and rank (used by --best) ──────────────────────────────────


def score_and_rank(
    generated: list[tuple[OutputPaths, Path]], meta: SongMeta | None,
) -> None:
    """Score all generated versions and log a ranked table."""
    log.info("")
    log.info("Scoring %d versions...", len(generated))
    ranked: list[tuple[OutputPaths, SongScores]] = []
    for paths, snapshot_path in generated:
        scores = run_scoring_pipeline(paths.mp3, meta=meta if isinstance(meta, SongMeta) else None)
        append_scores_section(snapshot_path, scores)
        log_scores(scores)
        ranked.append((paths, scores))
    log_ranking(ranked)


# ── Single and batch scoring ─────────────────────────────────────────


def score_single(
    path: str,
    source: str | None,
    scorer_list: list[str] | None,
    config: PipelineConfig,
) -> None:
    """Score a single MP3 file."""
    mp3_path = validate_path(path)
    meta = None
    if source:
        meta = parse_song_md(validate_path(source))

    scores = run_scoring_pipeline(mp3_path, meta=meta, scorers=scorer_list, config=config)
    log_scores(scores)


def _already_scored(snapshot_path: Path) -> bool:
    """Check whether a snapshot already has dynamics scores."""
    if not snapshot_path.exists():
        return False
    existing = read_scores(snapshot_path)
    return bool(existing and "dynamics" in existing)


def _find_meta(mp3: Path, project_root: Path) -> SongMeta | None:
    """Try to locate and parse lyrics metadata for an MP3."""
    from songmaker_cli.check import find_lyrics_source

    try:
        md_path = find_lyrics_source(mp3, None, project_root=str(project_root))
        return parse_song_md(md_path)
    except (ValidationError, FileNotFoundError):
        log.debug("No lyrics found for %s, scoring without metadata", mp3.name)
        return None


def _create_minimal_snapshot(
    snapshot_path: Path, mp3: Path, meta: SongMeta | None,
) -> None:
    """Create a minimal snapshot .md for old songs that don't have one."""
    album = mp3.parent.name
    title = meta.title if meta else mp3.stem
    lyrics = meta.lyrics if meta else ""

    content = f"---\ntitle: {title}\nalbum: {album}\n---\n"
    if lyrics:
        content += f"\n## Lyrics\n\n{lyrics}\n"

    snapshot_path.write_text(content, encoding="utf-8")
    log.info("Created snapshot: %s", snapshot_path.name)


def _auto_detect_device(config: PipelineConfig) -> PipelineConfig:
    """Auto-detect GPU if available and ACE-Step isn't hogging VRAM."""
    if config.device != "cpu":
        return config

    try:
        import torch

        if not torch.cuda.is_available():
            return config

        free_gb = (torch.cuda.get_device_properties(0).total_mem
                   - torch.cuda.memory_reserved(0)) / 1e9
        if free_gb > 5.0:
            log.info("GPU detected with %.1fGB free — using CUDA", free_gb)
            return PipelineConfig(
                whisper_model=config.whisper_model,
                device="cuda",
                scorer_timeout=config.scorer_timeout,
            )
        log.info("GPU has only %.1fGB free (ACE-Step running?) — using CPU", free_gb)
    except Exception:
        pass
    return config


def _whisper_pass(
    mp3s: list[Path], config: PipelineConfig, project_root: Path, force: bool,
) -> None:
    """Run Whisper transcription on all songs in a single pass.

    Loads the model once, transcribes all songs, then unloads.
    This is separate from the scoring pipeline to manage GPU memory.
    """
    # Only run if text_accuracy or vocal_quality would need it
    songs_needing_whisper = [
        mp3 for mp3 in mp3s
        if force or not mp3.with_suffix(".whisper").exists()
    ]
    if not songs_needing_whisper:
        log.info("All songs already have Whisper transcriptions")
        return

    log.info("Whisper pass: %d songs with %s on %s",
             len(songs_needing_whisper), config.whisper_model, config.device)

    import whisper

    model = whisper.load_model(config.whisper_model, device=config.device)
    fp16 = config.device == "cuda"

    for i, mp3 in enumerate(songs_needing_whisper):
        log.info("[%d/%d] Whisper: %s", i + 1, len(songs_needing_whisper), mp3.name)
        result = model.transcribe(
            str(mp3), language="en", fp16=fp16,
            condition_on_previous_text=True,
        )
        lines = [
            s["text"].strip()
            for s in result.get("segments", [])
            if s.get("text", "").strip()
        ]
        mp3.with_suffix(".whisper").write_text("\n".join(lines), encoding="utf-8")

    # Free GPU memory
    del model
    try:
        import torch

        torch.cuda.empty_cache()
    except Exception:
        pass
    log.info("Whisper pass complete")


def score_all(
    scorer_list: list[str] | None,
    config: PipelineConfig,
    force: bool,
) -> None:
    """Score all MP3s in _output/.

    Pipeline:
    1. Auto-detect GPU if available
    2. Whisper transcription pass (loads model once, transcribes all, unloads)
    3. Score each song with remaining scorers
    4. Rebuild player
    """
    from songmaker_cli.player import generate_player

    project_root = find_project_root(Path.cwd()) or Path.cwd()
    output_dir = project_root / OUTPUT_ROOT

    if not output_dir.exists():
        raise ValidationError(f"No output directory: {output_dir}")

    mp3s = sorted(output_dir.rglob("*.mp3"))
    mp3s = [m for m in mp3s if "test_" not in m.stem]
    if not mp3s:
        log.info("No MP3s found in %s", output_dir)
        return

    config = _auto_detect_device(config)

    # Step 1: Whisper pass — single model load, all songs
    needs_whisper = scorer_list is None or any(
        s in (scorer_list or []) for s in ("text_accuracy", "vocal_quality")
    )
    if needs_whisper:
        _whisper_pass(mp3s, config, project_root, force)

    # Step 2: Score each song
    log.info("Scoring %d MP3s...", len(mp3s))
    scored = 0
    skipped = 0

    for mp3 in mp3s:
        snapshot_path = mp3.with_suffix(".md")

        if not force and _already_scored(snapshot_path):
            skipped += 1
            continue

        if not snapshot_path.exists():
            meta = _find_meta(mp3, project_root)
            _create_minimal_snapshot(snapshot_path, mp3, meta)
        else:
            meta = _find_meta(mp3, project_root)

        log.info("[%d/%d] %s", scored + skipped + 1, len(mp3s), mp3.name)
        scores = run_scoring_pipeline(mp3, meta=meta, scorers=scorer_list, config=config)
        append_scores_section(snapshot_path, scores)
        log_scores(scores)
        scored += 1

    log.info("Done: %d scored, %d skipped (already scored)", scored, skipped)
    generate_player(output_dir, project_root)
    log.info("Player updated")
