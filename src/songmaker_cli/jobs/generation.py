"""Generation job orchestration — context build, dispatch, post-process, persist."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, cast

from arq.connections import ArqRedis
from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli import jobs
from songmaker_cli.acestep_state import decr_queue_depth
from songmaker_cli.api_models import (
    CoverTaskParams,
    RepaintTaskParams,
    StoredGenerationParams,
)
from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.arq_pool import is_scoring_worker_healthy
from songmaker_cli.config import (
    audio_file_path,
    build_ace_config,
    resolve_model_mode,
)
from songmaker_cli.constants import (
    ARQ_MUSIC_QUEUE_NAME,
    ARQ_SCORING_QUEUE_NAME,
    GENERATION_WAITING_FOR_LORA_QUEUE_REASON,
    GPU_HOLD_POLL_INTERVAL_SECONDS,
    JOB_ERROR_GENERATION_CANCELLED,
    JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND,
    JOB_ERROR_SONG_NOT_FOUND,
    JOB_ERROR_USER_LORA_UNAVAILABLE,
    JOB_ERROR_VERSION_NOT_FOUND,
    WORKER_SHARED_TMP_DIRNAME,
    JobFunction,
    JobStatus,
    JobType,
)
from songmaker_cli.db.models import GenerationPreset
from songmaker_cli.db.queries import (
    create_generation,
    create_generation_created_event,
    create_job,
    get_default_preset,
    get_generation,
    get_song,
    get_version,
    lock_active_job,
)
from songmaker_cli.generate import (
    _decode_audio,
    _splice_repaint_raw,
    _write_output,
)
from songmaker_cli.parser import AlbumMeta, SongMeta
from songmaker_cli.scheduler import AllWorkersHeld, NoCapacityError, WorkerTaskFailed

from ._runtime import (
    GenerationSetupError,
    _job_is_terminal,
    _sanitize_error,
    _touch_heartbeat,
    _update_job,
)

log = logging.getLogger(__name__)

GENERATION_JOB_TERMINAL_LOG: Final = "Generation job %s stopping because job is terminal"

_PROGRESS_THROTTLE_SECONDS = 2.0


@dataclass
class GenerationContext:
    song_id: str
    version_id: str
    meta: SongMeta
    album_meta: AlbumMeta
    ace_config: AceStepConfig
    audio_dir: Path
    user_id: str
    model_name: str
    base_params: dict = field(default_factory=dict)
    src_generation_id: str | None = None
    raw_src_audio: str | None = None


@dataclass(frozen=True)
class _DecodedAudioInput:
    wav_bytes: bytes


def _load_song_meta(
    song_id: str,
    version_id: str,
    db_factory: sessionmaker[Session],
) -> tuple[SongMeta, AlbumMeta]:
    """Load song and version from DB and return domain models."""
    with db_factory() as session:
        song = get_song(session, song_id)
        if not song:
            raise GenerationSetupError(JOB_ERROR_SONG_NOT_FOUND)

        version = get_version(session, version_id, song_id)
        if not version:
            raise GenerationSetupError(JOB_ERROR_VERSION_NOT_FOUND)

        album = song.album
        album_name = album.title.lower().replace(" ", "_") if album else "unknown"

        meta = SongMeta(
            title=song.title,
            album=album_name,
            track=str(song.track_number),
            prompt=version.prompt,
            lyrics=version.lyrics,
            bpm=version.bpm,
            audio_duration=version.audio_duration,
            key_scale=version.key_scale,
            vocal_language=song.vocal_language,
            generation_params=BaseGenerationParams.model_validate(
                version.generation_params or {},
            ),
        )
        album_meta = AlbumMeta(
            title=album_name,
            artist=album.artist if album else "",
        )

    log.debug(
        "Loaded: '%s' (album=%s, params=%s)",
        meta.title,
        album_name,
        meta.generation_params or "none",
    )
    return meta, album_meta


def _load_preset_params(
    user_id: str | None,
    model_name: str,
    db_factory: sessionmaker[Session],
) -> BaseGenerationParams | None:
    if not user_id:
        return None
    from songmaker_cli.config import get_builtin_defaults, resolve_model_mode
    from songmaker_cli.db.models import User

    with db_factory() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user or not user.default_generation_config:
            model_mode = resolve_model_mode(model_name)
            preset = get_default_preset(session, user_id, model_mode)
            if preset is None:
                return None
            return BaseGenerationParams.model_validate(preset.params or {})

        config = user.default_generation_config
        builtins = get_builtin_defaults()
        if config in builtins:
            return BaseGenerationParams.model_validate(builtins[config])

        preset = session.query(GenerationPreset).filter_by(id=config).first()
        if preset is None:
            return None
        return BaseGenerationParams.model_validate(preset.params or {})


def _extract_user_lora_id(base_params: object) -> str | None:
    if isinstance(base_params, BaseGenerationParams):
        return base_params.user_lora_id
    if isinstance(base_params, dict):
        try:
            return BaseGenerationParams.model_validate(base_params).user_lora_id
        except Exception:
            return None
    return None


def _apply_user_lora_path(
    ace_config: AceStepConfig,
    base_params: BaseGenerationParams,
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    user_id: str,
    target_model_mode: str,
) -> AceStepConfig:
    user_lora_id = base_params.user_lora_id
    if not user_lora_id:
        return ace_config
    from songmaker_cli.constants import LoraStatus
    from songmaker_cli.db.queries import get_user_lora

    with db_factory() as session:
        lora = get_user_lora(session, user_lora_id, include_deleted_rows=True)
        if (
            lora is None
            or lora.user_id != user_id
            or lora.deleted_at is not None
            or lora.status != LoraStatus.READY
            or not lora.storage_path
            or lora.model_mode != target_model_mode
        ):
            raise GenerationSetupError(JOB_ERROR_USER_LORA_UNAVAILABLE)
        lora_path = str((audio_dir / lora.storage_path).resolve())
    return cast(AceStepConfig, replace(ace_config, lora_path=lora_path))


def _build_generation_context(
    song_id: str,
    version_id: str,
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    data_dir: Path,
    user_id: str,
    target_model: str,
    seed: int | None = None,
) -> GenerationContext:
    """Load song/version from DB and build all config needed for generation.

    ``target_model`` is the user-requested mode (e.g. "sft", "xl-sft").
    """
    meta, album_meta = _load_song_meta(song_id, version_id, db_factory)

    model_name = resolve_model_mode(target_model)
    log.debug("Target ACE-Step model: %s", model_name)

    preset_params = _load_preset_params(user_id, model_name, db_factory)
    ace_config = build_ace_config(
        meta,
        model_name=model_name,
        global_defaults=jobs.load_generation_defaults(db_factory, data_dir),
        preset_params=preset_params,
        seed=seed,
    )
    ace_config = replace(ace_config, model=model_name)

    if ace_config.reference_audio_path:
        from songmaker_cli.reference_audio import (
            ReferenceAudioRejected,
            resolve_owned_reference_audio,
        )

        try:
            abs_ref = resolve_owned_reference_audio(
                audio_dir,
                user_id,
                ace_config.reference_audio_path,
            )
        except ReferenceAudioRejected as exc:
            raise GenerationSetupError(JOB_ERROR_REFERENCE_AUDIO_NOT_FOUND) from exc
        ace_config = replace(ace_config, reference_audio_path=str(abs_ref))

    ace_config = _apply_user_lora_path(
        ace_config,
        meta.generation_params,
        db_factory,
        audio_dir,
        user_id,
        model_name,
    )

    return GenerationContext(
        song_id=song_id,
        version_id=version_id,
        meta=meta,
        album_meta=album_meta,
        ace_config=ace_config,
        audio_dir=audio_dir,
        user_id=user_id,
        model_name=model_name,
        base_params=meta.generation_params,
    )


def post_process_generation(
    *,
    worker_audio_path: str,
    worker_seed: int,
    worker_cot_caption: str,
    worker_cot_lyrics: str,
    worker_delivered_batch_size: int | None,
    ctx: GenerationContext,
    generation_id: str,
    db_factory: sessionmaker[Session],
    job_id: str,
) -> str | None:
    """Read worker WAV, decode/splice/master/encode, persist DB row.

    Synchronous (CPU-bound). Caller wraps in ``asyncio.to_thread`` from
    the async run_generation_job. Mastering + MP3 encoding release the
    GIL but still block the asyncio event loop if called directly.

    Returns the persisted ``Generation.id`` — a fresh id the row's own
    default assigns, distinct from ``generation_id`` (used only to name the
    audio files) — or ``None`` when the job was cancelled before the row
    could be written. Callers that need to act on the actual generation
    (e.g. auto-scoring it) must use this return value, not the parameter.
    """
    src_wav = Path(worker_audio_path)
    try:
        decoded = _decode_audio(_DecodedAudioInput(wav_bytes=src_wav.read_bytes()))

        server_handles_crossfade = bool(
            ctx.ace_config.repaint_mode or ctx.ace_config.repaint_wav_crossfade_sec > 0
        )
        needs_splice = (
            ctx.ace_config.task_type == "repaint"
            and ctx.ace_config.src_audio_path
            and not server_handles_crossfade
        )
        if needs_splice:
            splice_src = ctx.raw_src_audio or ctx.ace_config.src_audio_path
            decoded = _splice_repaint_raw(decoded, ctx.ace_config, splice_src)

        mp3_path = audio_file_path(ctx.audio_dir, ctx.user_id, generation_id, ".mp3")
        wav_path = audio_file_path(ctx.audio_dir, ctx.user_id, generation_id, ".wav")
        raw_wav_path = audio_file_path(
            ctx.audio_dir,
            ctx.user_id,
            generation_id,
            ".raw.wav",
        )
        from audio_engine import write_stereo_wav

        write_stereo_wav(
            str(raw_wav_path),
            decoded.left,
            decoded.right,
            decoded.sample_rate,
        )
        _write_output(
            decoded,
            worker_seed,
            mp3_path,
            wav_path,
            ctx.meta,
            ctx.album_meta,
        )
        return _persist_generation_row(
            db_factory=db_factory,
            ctx=ctx,
            generation_id=generation_id,
            seed=worker_seed,
            cot_caption=worker_cot_caption,
            cot_lyrics=worker_cot_lyrics,
            delivered_batch_size=worker_delivered_batch_size,
            job_id=job_id,
        )
    finally:
        try:
            src_wav.unlink()
        except OSError:
            log.warning("Failed to delete worker temp WAV: %s", src_wav)


def _persist_generation_row(
    *,
    db_factory: sessionmaker[Session],
    ctx: GenerationContext,
    generation_id: str,
    seed: int,
    cot_caption: str,
    cot_lyrics: str,
    delivered_batch_size: int | None,
    job_id: str,
) -> str | None:
    mp3_rel = f"{ctx.user_id}/{generation_id}.mp3"
    wav_rel = f"{ctx.user_id}/{generation_id}.wav"
    raw_wav_rel = f"{ctx.user_id}/{generation_id}.raw.wav"
    gen_params = _stored_generation_params(ctx, cot_caption, cot_lyrics, delivered_batch_size)

    try:
        with db_factory() as session:
            if lock_active_job(session, job_id) is None:
                _cleanup_orphaned_files(ctx.audio_dir, mp3_rel, wav_rel, raw_wav_rel)
                return None
            generation = create_generation(
                session,
                song_id=ctx.song_id,
                version_id=ctx.version_id,
                mp3_path=mp3_rel,
                seed=seed,
                generation_params=gen_params,
                wav_path=wav_rel,
                model_mode=ctx.model_name,
                src_generation_id=ctx.src_generation_id,
                audio_dir=ctx.audio_dir,
            )
            persisted_id = generation.id
            create_generation_created_event(
                session,
                user_id=ctx.user_id,
                song_id=ctx.song_id,
                generation_id=persisted_id,
            )
            session.commit()
    except Exception:
        _cleanup_orphaned_files(ctx.audio_dir, mp3_rel, wav_rel, raw_wav_rel)
        raise

    log.info("Generated: %s (seed=%s)", mp3_rel, seed)
    return persisted_id


def _stored_generation_params(
    ctx: GenerationContext,
    cot_caption: str,
    cot_lyrics: str,
    delivered_batch_size: int | None,
) -> dict:
    config = ctx.ace_config
    stored = StoredGenerationParams(
        acestep_model=ctx.model_name,
        bpm=config.bpm,
        audio_duration=config.audio_duration,
        key_scale=ctx.meta.key_scale,
        guidance_scale=config.guidance_scale,
        inference_steps=config.inference_steps,
        shift=config.shift,
        lm_temperature=config.lm_temperature,
        infer_method=config.infer_method,
        thinking=config.thinking,
        **_stored_generation_options(config),
        **_stored_task_options(config),
        cot_caption=cot_caption or None,
        cot_lyrics=cot_lyrics or None,
        user_lora_id=_extract_user_lora_id(ctx.base_params),
        **_stored_batch_options(config, delivered_batch_size),
    )
    return stored.model_dump(exclude_none=True)


def _stored_generation_options(config: AceStepConfig) -> dict:
    return {
        "lm_repetition_penalty": _unless_close(config.lm_repetition_penalty, 1.0),
        "use_cot_caption": False if not config.use_cot_caption else None,
        "use_cot_language": False if not config.use_cot_language else None,
        "use_adg": True if config.use_adg else None,
        "cfg_interval_start": (
            config.cfg_interval_start if config.cfg_interval_start > 0.0 else None
        ),
        "cfg_interval_end": config.cfg_interval_end if config.cfg_interval_end < 1.0 else None,
        "constrained_decoding": True if config.constrained_decoding else None,
        "sampler_mode": config.sampler_mode if config.sampler_mode != "euler" else None,
        "velocity_norm_threshold": (
            config.velocity_norm_threshold if config.velocity_norm_threshold > 0 else None
        ),
        "velocity_ema_factor": (
            config.velocity_ema_factor if config.velocity_ema_factor > 0 else None
        ),
        "latent_shift": config.latent_shift if config.latent_shift != 0 else None,
        "latent_rescale": _unless_close(config.latent_rescale, 1.0),
        "timesteps": config.timesteps or None,
        "task_type": config.task_type if config.task_type != "text2music" else None,
        "audio_cover_strength": _unless_close(config.audio_cover_strength, 1.0),
    }


def _stored_task_options(config: AceStepConfig) -> dict:
    if config.task_type == "repaint":
        return {
            "repainting_start": config.repainting_start,
            "repainting_end": config.repainting_end,
            "repaint_mode": config.repaint_mode or None,
            "repaint_strength": config.repaint_strength if config.repaint_mode else None,
            "repaint_latent_crossfade_frames": (
                config.repaint_latent_crossfade_frames
                if config.repaint_latent_crossfade_frames > 0
                else None
            ),
            "repaint_wav_crossfade_sec": (
                config.repaint_wav_crossfade_sec if config.repaint_wav_crossfade_sec > 0 else None
            ),
        }
    if config.task_type == "cover" and config.cover_noise_strength > 0:
        return {"cover_noise_strength": config.cover_noise_strength}
    return {}


def _stored_batch_options(config: AceStepConfig, delivered_batch_size: int | None) -> dict:
    return {
        "batch_size": config.batch_size if config.batch_size != 1 else None,
        "delivered_batch_size": (
            delivered_batch_size
            if delivered_batch_size is not None and delivered_batch_size != config.batch_size
            else None
        ),
    }


def _unless_close(value: float, default: float) -> float | None:
    return value if not math.isclose(value, default) else None


def _finalize_generation_job(
    db_factory: sessionmaker[Session],
    job_id: str,
    count: int,
    completed: int,
    last_error: Exception | None,
) -> None:
    """Set final job status based on how many generations succeeded."""
    if _job_is_terminal(db_factory, job_id):
        return
    if completed == count:
        _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)
    elif completed > 0:
        _update_job(
            db_factory,
            job_id,
            JobStatus.PARTIAL,
            progress=completed / count,
            error=f"{completed}/{count} completed, {count - completed} failed: "
            f"{_sanitize_error(last_error, job_id)}",
            error_type="generation_error",
        )
    else:
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=_sanitize_error(last_error, job_id),
            error_type="generation_error",
        )


def _create_auto_score_job(
    db_factory: sessionmaker[Session],
    gen_id: str,
    song_id: str,
) -> str | None:
    """Create the DB row for an automatic post-generation score job.

    Returns ``None`` (creating nothing) when the generation row itself never
    made it into the DB — the narrow race where the generation job was
    cancelled while ``post_process_generation`` was writing it — since
    scoring a generation that does not exist would only fail immediately.

    ``user_id=None`` is the origin marker that keeps this job out of the
    manual re-score button's budget: ``count_user_jobs_in_window`` always
    filters on a specific user id, so a row with no user never counts
    against anyone's rate limit. The generation job's own completion path is
    the only caller, once per successfully persisted generation, so there is
    no retry loop here that could turn this into a flood.
    """
    with db_factory() as session:
        if get_generation(session, gen_id) is None:
            return None
        job = create_job(session, JobType.SCORE, user_id=None, song_id=song_id)
        session.commit()
        return job.id


async def _dispatch_auto_score(
    redis: ArqRedis,
    db_factory: sessionmaker[Session],
    job_id: str,
    gen_id: str,
) -> None:
    """Hand an auto-score job to the scoring queue, or fail it cleanly.

    Never raises: this runs right after a generation has already succeeded,
    and a scoring hiccup must not turn that success into a failure. A
    scoring worker that is down when we check leaves this job FAILED with a
    clear reason instead of queuing indefinitely — the generation still has
    no score row, so ``lifecycle.py``'s throttled backfill loop picks it up
    once a worker comes back.

    Health is checked via the passed-in ``redis`` connection, not the
    process-singleton pool ``is_scoring_worker_healthy()`` defaults to —
    this runs inside the music worker process, which never calls
    ``init_arq_pool()``.
    """
    try:
        worker_healthy = await is_scoring_worker_healthy(redis)
        if not worker_healthy:
            _update_job(
                db_factory,
                job_id,
                JobStatus.FAILED,
                error="Scoring worker not running",
                error_type="setup_error",
            )
            return
        await redis.enqueue_job(
            JobFunction.SCORE,
            job_id,
            gen_id,
            None,
            _queue_name=ARQ_SCORING_QUEUE_NAME,
        )
    except Exception:
        log.exception("Auto-score dispatch failed for generation %s", gen_id)
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error="Failed to enqueue auto-score job",
            error_type="setup_error",
        )


async def _auto_score_generation(
    redis: ArqRedis,
    db_factory: sessionmaker[Session],
    gen_id: str,
    song_id: str,
) -> None:
    """Create and dispatch this generation's auto-score job, or do nothing.

    Never raises: called from the generation job's own success path, right
    after ``completed`` is already counted, so a problem here must stay a
    scoring-side concern and never turn a successful generation into a
    reported failure.
    """
    try:
        job_id = await asyncio.to_thread(_create_auto_score_job, db_factory, gen_id, song_id)
    except Exception:
        log.exception("Auto-score job creation failed for generation %s", gen_id)
        return
    if job_id:
        await _dispatch_auto_score(redis, db_factory, job_id, gen_id)


def _make_generation_progress_callback(
    db_factory: sessionmaker[Session],
    job_id: str,
    variant_index: int,
    count: int,
) -> Callable[[float], None]:
    last_update = 0.0

    def _on_progress(step_fraction: float) -> None:
        nonlocal last_update
        now = time.monotonic()
        if now - last_update < _PROGRESS_THROTTLE_SECONDS:
            return
        combined = (variant_index + step_fraction) / count
        _update_job(db_factory, job_id, JobStatus.RUNNING, progress=combined)
        last_update = now

    return _on_progress


def _make_heartbeat_callback(
    db_factory: sessionmaker[Session],
    job_id: str,
) -> Callable[[], None]:
    def _on_heartbeat() -> None:
        _touch_heartbeat(db_factory, job_id)

    return _on_heartbeat


def _shared_tmp_dir(audio_dir: Path) -> Path:
    d = audio_dir / WORKER_SHARED_TMP_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_to_shared_tmp(src_path: str, audio_dir: Path) -> str:
    suffix = Path(src_path).suffix
    fd, tmp_path = tempfile.mkstemp(
        suffix=suffix,
        prefix="songmaker_src_",
        dir=_shared_tmp_dir(audio_dir),
    )
    os.close(fd)
    shutil.copy2(src_path, tmp_path)
    return tmp_path


def _resolve_raw_wav(mastered_wav_path: str) -> str | None:
    raw_path = Path(mastered_wav_path).with_suffix(".raw.wav")
    return str(raw_path) if raw_path.exists() else None


def _apply_repaint_overrides(
    ctx: GenerationContext,
    params: RepaintTaskParams,
) -> GenerationContext:
    raw_wav = _resolve_raw_wav(params.src_wav_path)
    audio_duration = ctx.ace_config.audio_duration

    overrides: dict[str, Any] = {
        "task_type": "repaint",
        "src_audio_path": _copy_to_shared_tmp(params.src_wav_path, ctx.audio_dir),
        "prompt": params.prompt or ctx.ace_config.prompt,
        "lyrics": params.lyrics or ctx.ace_config.lyrics,
        "repainting_start": params.repainting_start * audio_duration,
        "repainting_end": params.repainting_end * audio_duration,
    }
    if params.repaint_mode is not None:
        overrides["repaint_mode"] = params.repaint_mode
    if params.repaint_strength is not None:
        overrides["repaint_strength"] = params.repaint_strength
    if params.repaint_latent_crossfade_frames is not None:
        overrides["repaint_latent_crossfade_frames"] = params.repaint_latent_crossfade_frames
    if params.repaint_wav_crossfade_sec is not None:
        overrides["repaint_wav_crossfade_sec"] = params.repaint_wav_crossfade_sec

    new_ctx: GenerationContext = replace(
        ctx,
        ace_config=cast(AceStepConfig, replace(ctx.ace_config, **overrides)),
        src_generation_id=params.src_generation_id,
    )
    if raw_wav:
        new_ctx = replace(
            new_ctx,
            raw_src_audio=_copy_to_shared_tmp(raw_wav, ctx.audio_dir),
        )
    return new_ctx


def _apply_cover_overrides(
    ctx: GenerationContext,
    params: CoverTaskParams,
) -> GenerationContext:
    overrides: dict[str, Any] = {
        "task_type": "cover",
        "src_audio_path": _copy_to_shared_tmp(params.src_wav_path, ctx.audio_dir),
        "prompt": params.prompt or ctx.ace_config.prompt,
        "lyrics": params.lyrics or ctx.ace_config.lyrics,
        "audio_cover_strength": params.audio_cover_strength,
    }
    if params.cover_noise_strength is not None:
        overrides["cover_noise_strength"] = params.cover_noise_strength

    new_ctx: GenerationContext = replace(
        ctx,
        ace_config=cast(AceStepConfig, replace(ctx.ace_config, **overrides)),
        src_generation_id=params.src_generation_id,
    )
    return new_ctx


async def run_generation_job(
    job_id: str,
    song_id: str,
    version_id: str,
    count: int,
    user_id: str,
    *,
    target_model: str,
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    data_dir: Path,
    redis: ArqRedis,
    seed: int | None = None,
    repaint_params: RepaintTaskParams | None = None,
    cover_params: CoverTaskParams | None = None,
) -> None:

    import structlog

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id,
        job_type=JobType.GENERATE,
        song_id=song_id,
    )

    if cover_params:
        task_type = "cover"
    elif repaint_params:
        task_type = "repaint"
    else:
        task_type = "generate"
    log.info("Generation job %s: song=%s, count=%d, task=%s", job_id, song_id, count, task_type)

    admitted_worker = None

    try:
        admitted_worker = await _admit_generation_worker_or_requeue(
            redis,
            db_factory,
            job_id,
            song_id,
            version_id,
            count,
            user_id,
            seed,
            target_model,
            repaint_params,
            cover_params,
        )
        if admitted_worker is None:
            return

        ctx = await _build_generation_job_context(
            db_factory,
            job_id,
            song_id,
            version_id,
            audio_dir,
            data_dir,
            user_id,
            seed,
            target_model,
            repaint_params,
            cover_params,
        )
        if ctx is None:
            return

        _update_job(db_factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())
        if _job_is_terminal(db_factory, job_id):
            log.info(GENERATION_JOB_TERMINAL_LOG, job_id)
            return

        tmp_copies = _temporary_generation_audio_paths(ctx)
        try:
            await _generate_variants(
                admitted_worker,
                redis,
                db_factory,
                job_id,
                song_id,
                count,
                ctx,
            )
        finally:
            _remove_temporary_generation_audio(tmp_copies)

    except asyncio.CancelledError:
        log.warning("Generation job %s cancelled (arq timeout or worker shutdown)", job_id)
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=JOB_ERROR_GENERATION_CANCELLED,
            error_type="timeout",
        )
        raise
    except Exception as exc:
        log.exception("Generation job failed: %s", exc)
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=_sanitize_error(exc, job_id),
            error_type="generation_error",
        )
    finally:
        if admitted_worker is not None:
            await decr_queue_depth(redis, admitted_worker.id)


async def _admit_generation_worker_or_requeue(
    redis: ArqRedis,
    db_factory: sessionmaker[Session],
    job_id: str,
    song_id: str,
    version_id: str,
    count: int,
    user_id: str,
    seed: int | None,
    target_model: str,
    repaint_params: RepaintTaskParams | None,
    cover_params: CoverTaskParams | None,
):
    if _job_is_terminal(db_factory, job_id):
        log.info(GENERATION_JOB_TERMINAL_LOG, job_id)
        return None
    try:
        return await jobs.admit_generation_worker(
            target_mode=target_model,
            redis=redis,
            db_factory=db_factory,
        )
    except AllWorkersHeld:
        _update_job(
            db_factory,
            job_id,
            JobStatus.QUEUED,
            queue_reason=GENERATION_WAITING_FOR_LORA_QUEUE_REASON,
        )
        await redis.enqueue_job(
            JobFunction.GENERATE,
            job_id,
            song_id,
            version_id,
            count,
            user_id,
            seed,
            target_model,
            repaint_params.model_dump() if repaint_params is not None else None,
            cover_params.model_dump() if cover_params is not None else None,
            _queue_name=ARQ_MUSIC_QUEUE_NAME,
            _defer_by=GPU_HOLD_POLL_INTERVAL_SECONDS,
        )
        return None


async def _build_generation_job_context(
    db_factory: sessionmaker[Session],
    job_id: str,
    song_id: str,
    version_id: str,
    audio_dir: Path,
    data_dir: Path,
    user_id: str,
    seed: int | None,
    target_model: str,
    repaint_params: RepaintTaskParams | None,
    cover_params: CoverTaskParams | None,
) -> GenerationContext | None:
    try:
        ctx = await asyncio.to_thread(
            _build_generation_context,
            song_id,
            version_id,
            db_factory,
            audio_dir,
            data_dir,
            user_id=user_id,
            seed=seed,
            target_model=target_model,
        )
        return _apply_generation_task_overrides(ctx, repaint_params, cover_params)
    except GenerationSetupError as exc:
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=_sanitize_error(exc, job_id),
            error_type="setup_error",
        )
        return None


def _apply_generation_task_overrides(
    ctx: GenerationContext,
    repaint_params: RepaintTaskParams | None,
    cover_params: CoverTaskParams | None,
) -> GenerationContext:
    if repaint_params is not None:
        return _apply_repaint_overrides(ctx, repaint_params)
    if cover_params is not None:
        return _apply_cover_overrides(ctx, cover_params)
    return ctx


def _temporary_generation_audio_paths(ctx: GenerationContext) -> list[str]:
    shared_tmp_prefix = str(ctx.audio_dir / WORKER_SHARED_TMP_DIRNAME)
    candidates = [ctx.ace_config.src_audio_path, ctx.raw_src_audio]
    return [path for path in candidates if path and path.startswith(shared_tmp_prefix)]


def _remove_temporary_generation_audio(paths: list[str]) -> None:
    for path in paths:
        try:
            os.unlink(path)
        except OSError:
            pass


async def _generate_variants(
    admitted_worker,
    redis: ArqRedis,
    db_factory: sessionmaker[Session],
    job_id: str,
    song_id: str,
    count: int,
    ctx: GenerationContext,
) -> None:
    completed = 0
    last_error: Exception | None = None
    for index in range(count):
        if _job_is_terminal(db_factory, job_id):
            log.info(GENERATION_JOB_TERMINAL_LOG, job_id)
            return
        persisted_gen_id, error = await _generate_variant(
            admitted_worker,
            db_factory,
            job_id,
            index,
            count,
            ctx,
        )
        if error is not None:
            last_error = error
            continue
        completed += 1
        if persisted_gen_id:
            await _auto_score_generation(redis, db_factory, persisted_gen_id, song_id)
    _finalize_generation_job(db_factory, job_id, count, completed, last_error)


async def _generate_variant(
    admitted_worker,
    db_factory: sessionmaker[Session],
    job_id: str,
    index: int,
    count: int,
    ctx: GenerationContext,
) -> tuple[str | None, Exception | None]:
    import uuid

    _update_job(db_factory, job_id, JobStatus.RUNNING, progress=index / count)
    try:
        worker_result = await jobs.dispatch_generation_on_worker(
            worker=admitted_worker,
            ace_config=ctx.ace_config,
            target_mode=ctx.model_name,
            on_progress=_make_generation_progress_callback(db_factory, job_id, index, count),
            on_heartbeat=_make_heartbeat_callback(db_factory, job_id),
        )
        if _job_is_terminal(db_factory, job_id):
            _discard_worker_audio(worker_result.audio_path)
            log.info(GENERATION_JOB_TERMINAL_LOG, job_id)
            return None, None
        persisted_gen_id = await asyncio.to_thread(
            jobs.post_process_generation,
            worker_audio_path=worker_result.audio_path,
            worker_seed=worker_result.seed,
            worker_cot_caption=worker_result.cot_caption,
            worker_cot_lyrics=worker_result.cot_lyrics,
            worker_delivered_batch_size=worker_result.delivered_batch_size,
            ctx=ctx,
            generation_id=str(uuid.uuid4()),
            db_factory=db_factory,
            job_id=job_id,
        )
        return persisted_gen_id, None
    except (NoCapacityError, WorkerTaskFailed) as exc:
        log.warning("Generation %d/%d failed: %s", index + 1, count, exc)
        return None, exc
    except Exception as exc:
        log.exception("Generation %d/%d failed: %s", index + 1, count, exc)
        return None, exc


def _discard_worker_audio(audio_path: str) -> None:
    path = Path(audio_path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("Failed to delete worker temp WAV: %s", path)


def _cleanup_orphaned_files(audio_dir: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = audio_dir / rel
        try:
            if path.exists():
                path.unlink()
        except OSError:
            log.warning("Failed to clean orphaned file: %s", rel)
