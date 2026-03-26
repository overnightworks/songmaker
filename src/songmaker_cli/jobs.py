"""Background job runners for generation and scoring."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from acestep_engine import AceStepClient
from acestep_engine.models import AceStepConfig
from songmaker_cli.api_models import StoredGenerationParams
from songmaker_cli.config import build_ace_config, load_generation_defaults
from songmaker_cli.db.queries import (
    create_generation,
    get_default_preset,
    get_generation,
    get_song,
    save_scores,
    update_job_status,
)
from songmaker_cli.generate import generate_single
from songmaker_cli.parser import AlbumMeta, SongMeta
from songmaker_cli.scoring import run_scoring_pipeline
from songmaker_cli.scoring.pipeline import PipelineConfig

log = logging.getLogger(__name__)

_USER_FACING_ERRORS: dict[str, str] = {
    "AudioDownloadError": "Failed to download generated audio",
    "ConnectionError": "ACE-Step server not reachable",
    "TimeoutError": "Generation timed out",
    "RuntimeError": "Internal error during processing",
}


def _sanitize_error(exc: Exception) -> str:
    """Return a user-safe error message, logging the full exception."""
    if isinstance(exc, GenerationSetupError):
        return str(exc)
    type_name = type(exc).__name__
    if type_name in _USER_FACING_ERRORS:
        return _USER_FACING_ERRORS[type_name]
    return "An unexpected error occurred"


@dataclass
class GenerationContext:
    song_id: str
    version_id: str
    meta: SongMeta
    album_meta: AlbumMeta
    ace_config: AceStepConfig
    output_root: Path
    model_name: str | None
    client: AceStepClient
    base_params: dict = field(default_factory=dict)


class GenerationSetupError(Exception):
    pass


def _load_song_meta(
    song_id: str, version_id: str, db_factory: sessionmaker[Session],
) -> tuple[SongMeta, AlbumMeta]:
    """Load song and version from DB and return domain models."""
    with db_factory() as session:
        song = get_song(session, song_id)
        if not song:
            raise GenerationSetupError("Song not found")

        version = next((v for v in song.versions if v.id == version_id), None)
        if not version:
            raise GenerationSetupError("Version not found")

        album = song.album
        album_name = album.title.lower().replace(" ", "_") if album else "unknown"

        base_params: dict = {
            k: v for k, v in {
                "bpm": version.bpm,
                "duration": version.duration,
                "key": version.key,
                "language": song.language,
            }.items() if v
        }
        base_params.update(version.generation_params or {})

        meta = SongMeta(
            title=song.title,
            album=album_name,
            track=str(song.track_number),
            prompt=version.prompt,
            lyrics=version.lyrics,
            generation_params=base_params,
        )
        album_meta = AlbumMeta(
            title=album_name,
            artist=album.artist if album else "",
        )

    log.debug("Loaded: '%s' (album=%s, params=%s)", meta.title, album_name, base_params or "none")
    return meta, album_meta


def _load_preset_params(
    user_id: str | None, model_name: str | None, db_factory: sessionmaker[Session],
) -> dict | None:
    if not user_id:
        return None
    is_sft = model_name and "sft" in model_name
    model_mode = "sft" if is_sft else "turbo"
    with db_factory() as session:
        preset = get_default_preset(session, user_id, model_mode)
        return dict(preset.params) if preset else None


def _build_generation_context(
    song_id: str, version_id: str,
    db_factory: sessionmaker[Session], output_dir: Path,
    user_id: str | None = None,
) -> GenerationContext:
    """Load song/version from DB and build all config needed for generation."""
    meta, album_meta = _load_song_meta(song_id, version_id, db_factory)

    client = AceStepClient()
    if not client.is_available:
        raise GenerationSetupError("ACE-Step server not reachable")

    server_info = client.server_info()
    model_name = server_info.model if server_info else None
    log.debug("ACE-Step model: %s", model_name)

    preset_params = _load_preset_params(user_id, model_name, db_factory)
    ace_config = build_ace_config(
        meta,
        model_name=model_name,
        global_defaults=load_generation_defaults(db_factory, output_dir),
        preset_params=preset_params,
    )

    return GenerationContext(
        song_id=song_id,
        version_id=version_id,
        meta=meta,
        album_meta=album_meta,
        ace_config=ace_config,
        output_root=output_dir,
        model_name=model_name,
        client=client,
        base_params=meta.generation_params,
    )


def run_generation_job(
    job_id: str, song_id: str, version_id: str, count: int,
    user_id: str | None = None,
    db_factory: sessionmaker[Session] | None = None,
    output_dir: Path | None = None,
) -> None:
    """Run generation in a background thread, updating DB status."""
    assert db_factory is not None, "db_factory is required"
    assert output_dir is not None, "output_dir is required"

    import structlog
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type="generate", song_id=song_id,
    )

    log.info("Generation job %s: song=%s, count=%d", job_id, song_id, count)

    try:
        _update_job(db_factory, job_id, "running")

        try:
            ctx = _build_generation_context(
                song_id, version_id, db_factory, output_dir, user_id=user_id,
            )
        except GenerationSetupError as exc:
            _update_job(db_factory, job_id, "failed", error=str(exc), error_type="setup_error")
            return

        completed = 0
        last_error: Exception | None = None

        for i in range(count):
            _update_job(db_factory, job_id, "running", progress=i / count)

            try:
                result = generate_single(
                    ctx.meta, ctx.album_meta, ctx.ace_config, ctx.output_root, client=ctx.client,
                )
            except Exception as exc:
                log.exception("Generation %d/%d failed: %s", i + 1, count, exc)
                last_error = exc
                continue

            mp3_rel = f"{ctx.meta.album}/{result.mp3_path.name}"
            wav_rel = f"{ctx.meta.album}/{result.wav_path.name}"
            gen_params = StoredGenerationParams(
                acestep_model=ctx.model_name,
                bpm=ctx.ace_config.bpm,
                duration=ctx.ace_config.duration,
                key=ctx.meta.generation_params.get("key", ""),
                guidance_scale=ctx.ace_config.guidance_scale,
                inference_steps=ctx.ace_config.inference_steps,
                shift=ctx.ace_config.shift,
                lm_temperature=ctx.ace_config.lm_temperature,
                infer_method=ctx.ace_config.infer_method,
                think_mode=ctx.ace_config.think_mode,
            ).model_dump(exclude_none=True)

            with db_factory() as session:
                create_generation(
                    session,
                    song_id=song_id,
                    version_id=version_id,
                    mp3_path=mp3_rel,
                    seed=result.seed,
                    generation_params=gen_params,
                    wav_path=wav_rel,
                )
                session.commit()

            completed += 1
            log.info("Generated %d/%d: %s (seed=%s)", i + 1, count, mp3_rel, result.seed)

        if completed == count:
            _update_job(db_factory, job_id, "completed", progress=1.0)
        elif completed > 0:
            _update_job(
                db_factory, job_id, "failed", progress=completed / count,
                error=f"{completed}/{count} completed, {count - completed} failed: "
                      f"{_sanitize_error(last_error)}",
                error_type="generation_error",
            )
        else:
            _update_job(
                db_factory, job_id, "failed",
                error=_sanitize_error(last_error),
                error_type="generation_error",
            )

    except Exception as exc:
        log.exception("Generation job failed: %s", exc)
        _update_job(
            db_factory, job_id, "failed",
            error=_sanitize_error(exc), error_type="generation_error",
        )
    finally:
        _cleanup_gpu()


def run_scoring_job(
    job_id: str, gen_id: str, scorers: list[str] | None,
    db_factory: sessionmaker[Session] | None = None,
    output_dir: Path | None = None,
) -> None:
    """Run scoring in a background thread, updating DB status."""
    assert db_factory is not None, "db_factory is required"
    assert output_dir is not None, "output_dir is required"

    import structlog
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type="score", generation_id=gen_id,
    )

    log.info("Scoring job %s: gen=%s, scorers=%s", job_id, gen_id, scorers or "all")

    try:
        _update_job(db_factory, job_id, "running")

        with db_factory() as session:
            gen = get_generation(session, gen_id)
            if not gen:
                _update_job(
                    db_factory, job_id, "failed",
                    error="Generation not found", error_type="setup_error",
                )
                return
            mp3_path_rel = gen.mp3_path
            song = gen.song

            meta_kwargs: dict = {}
            if song:
                ver = song.latest_version
                if ver:
                    meta_kwargs = {
                        "title": song.title,
                        "prompt": ver.prompt,
                        "lyrics": ver.lyrics,
                    }

        mp3_full = output_dir / mp3_path_rel

        if not mp3_full.exists():
            _update_job(
                db_factory, job_id, "failed",
                error="Audio file not found for scoring", error_type="setup_error",
            )
            log.error("Scoring job %s: MP3 not found at %s", job_id, mp3_path_rel)
            return

        device = _detect_device()
        config = PipelineConfig(device=device)
        meta = SongMeta(**meta_kwargs) if meta_kwargs else None
        song_scores = run_scoring_pipeline(mp3_full, meta=meta, scorers=scorers, config=config)
        scores_dict = song_scores.to_dict()

        whisper_text = None
        if song_scores.text_accuracy:
            whisper_text = "\n".join(song_scores.text_accuracy.transcribed_line_texts)

        with db_factory() as session:
            from songmaker_cli.db.models import Generation as GenModel
            save_scores(session, gen_id, scores_dict)
            if whisper_text is not None:
                gen_record = session.query(GenModel).filter_by(id=gen_id).first()
                if gen_record:
                    gen_record.whisper_text = whisper_text
            session.commit()

        log.info("Scored: %s (%d metrics)", mp3_path_rel, len(scores_dict))
        _update_job(db_factory, job_id, "completed", progress=1.0)

    except Exception as exc:
        log.exception("Scoring job failed: %s", exc)
        _update_job(
            db_factory, job_id, "failed",
            error=_sanitize_error(exc), error_type="scoring_error",
        )
    finally:
        _cleanup_gpu()


def _cleanup_gpu() -> None:
    try:
        import gc

        import torch
        if torch.cuda.is_available():
            gc.collect()
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _detect_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


def _update_job(factory, job_id: str, status: str, **kwargs) -> None:
    try:
        with factory() as session:
            update_job_status(session, job_id, status, **kwargs)
            session.commit()
    except Exception:
        log.exception("Failed to update job %s to %s", job_id, status)
