"""Generation job orchestration — context build, dispatch, post-process, persist."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli import jobs
from songmaker_cli.api_models import (
    CoverTaskParams,
    RepaintTaskParams,
    StoredGenerationParams,
)
from songmaker_cli.api_models.generation_params import BaseGenerationParams
from songmaker_cli.config import (
    audio_file_path,
    build_ace_config,
    resolve_model_mode,
)
from songmaker_cli.constants import (
    WORKER_SHARED_TMP_DIRNAME,
    JobStatus,
    JobType,
)
from songmaker_cli.db.models import GenerationPreset
from songmaker_cli.db.queries import (
    create_generation,
    create_generation_created_event,
    get_default_preset,
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
from songmaker_cli.scheduler import NoCapacityError, WorkerTaskFailed

from ._runtime import (
    GenerationSetupError,
    _job_is_terminal,
    _sanitize_error,
    _touch_heartbeat,
    _update_job,
)

log = logging.getLogger(__name__)

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
    song_id: str, version_id: str, db_factory: sessionmaker[Session],
) -> tuple[SongMeta, AlbumMeta]:
    """Load song and version from DB and return domain models."""
    with db_factory() as session:
        song = get_song(session, song_id)
        if not song:
            raise GenerationSetupError("Song not found")

        version = get_version(session, version_id, song_id)
        if not version:
            raise GenerationSetupError("Version not found")

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
        meta.title, album_name, meta.generation_params or "none",
    )
    return meta, album_meta


def _load_preset_params(
    user_id: str | None, model_name: str, db_factory: sessionmaker[Session],
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
    ace_config: AceStepConfig, base_params: BaseGenerationParams,
    db_factory: sessionmaker[Session], audio_dir: Path,
) -> AceStepConfig:
    user_lora_id = base_params.user_lora_id
    if not user_lora_id:
        return ace_config
    from songmaker_cli.constants import LoraStatus
    from songmaker_cli.db.queries import get_user_lora

    with db_factory() as session:
        lora = get_user_lora(session, user_lora_id)
        if lora is None or lora.status != LoraStatus.READY or not lora.storage_path:
            log.warning(
                "UserLora %s not READY — falling back to base model", user_lora_id,
            )
            return ace_config
        lora_path = str((audio_dir / lora.storage_path).resolve())
    return replace(ace_config, lora_path=lora_path)


def _build_generation_context(
    song_id: str, version_id: str,
    db_factory: sessionmaker[Session], audio_dir: Path, data_dir: Path,
    user_id: str, target_model: str, seed: int | None = None,
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
                audio_dir, user_id, ace_config.reference_audio_path,
            )
        except ReferenceAudioRejected as exc:
            raise GenerationSetupError("Reference audio not found") from exc
        ace_config = replace(ace_config, reference_audio_path=str(abs_ref))

    ace_config = _apply_user_lora_path(
        ace_config, meta.generation_params, db_factory, audio_dir,
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
    ctx: GenerationContext,
    generation_id: str,
    db_factory: sessionmaker[Session],
    job_id: str,
) -> None:
    """Read worker WAV, decode/splice/master/encode, persist DB row.

    Synchronous (CPU-bound). Caller wraps in ``asyncio.to_thread`` from
    the async run_generation_job. Mastering + MP3 encoding release the
    GIL but still block the asyncio event loop if called directly.
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
            ctx.audio_dir, ctx.user_id, generation_id, ".raw.wav",
        )
        from audio_engine import write_stereo_wav

        write_stereo_wav(
            str(raw_wav_path), decoded.left, decoded.right, decoded.sample_rate,
        )
        _write_output(
            decoded, worker_seed, mp3_path, wav_path, ctx.meta, ctx.album_meta,
        )
        _persist_generation_row(
            db_factory=db_factory,
            ctx=ctx,
            generation_id=generation_id,
            seed=worker_seed,
            cot_caption=worker_cot_caption,
            cot_lyrics=worker_cot_lyrics,
            mp3_path=mp3_path,
            wav_path=wav_path,
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
    mp3_path: Path,
    wav_path: Path,
    job_id: str,
) -> None:
    mp3_rel = f"{ctx.user_id}/{generation_id}.mp3"
    wav_rel = f"{ctx.user_id}/{generation_id}.wav"
    raw_wav_rel = f"{ctx.user_id}/{generation_id}.raw.wav"
    is_repaint = ctx.ace_config.task_type == "repaint"
    is_cover = ctx.ace_config.task_type == "cover"
    stored = StoredGenerationParams(
        acestep_model=ctx.model_name,
        bpm=ctx.ace_config.bpm,
        audio_duration=ctx.ace_config.audio_duration,
        key_scale=ctx.meta.key_scale,
        guidance_scale=ctx.ace_config.guidance_scale,
        inference_steps=ctx.ace_config.inference_steps,
        shift=ctx.ace_config.shift,
        lm_temperature=ctx.ace_config.lm_temperature,
        infer_method=ctx.ace_config.infer_method,
        thinking=ctx.ace_config.thinking,
        lm_repetition_penalty=(
            ctx.ace_config.lm_repetition_penalty
            if ctx.ace_config.lm_repetition_penalty != 1.0 else None
        ),
        use_cot_caption=False if not ctx.ace_config.use_cot_caption else None,
        use_cot_language=False if not ctx.ace_config.use_cot_language else None,
        use_adg=True if ctx.ace_config.use_adg else None,
        cfg_interval_start=(
            ctx.ace_config.cfg_interval_start
            if ctx.ace_config.cfg_interval_start > 0.0 else None
        ),
        cfg_interval_end=(
            ctx.ace_config.cfg_interval_end
            if ctx.ace_config.cfg_interval_end < 1.0 else None
        ),
        constrained_decoding=True if ctx.ace_config.constrained_decoding else None,
        sampler_mode=(
            ctx.ace_config.sampler_mode
            if ctx.ace_config.sampler_mode != "euler" else None
        ),
        velocity_norm_threshold=(
            ctx.ace_config.velocity_norm_threshold
            if ctx.ace_config.velocity_norm_threshold > 0 else None
        ),
        velocity_ema_factor=(
            ctx.ace_config.velocity_ema_factor
            if ctx.ace_config.velocity_ema_factor > 0 else None
        ),
        latent_shift=(
            ctx.ace_config.latent_shift
            if ctx.ace_config.latent_shift != 0 else None
        ),
        latent_rescale=(
            ctx.ace_config.latent_rescale
            if ctx.ace_config.latent_rescale != 1.0 else None
        ),
        timesteps=ctx.ace_config.timesteps or None,
        task_type=(
            ctx.ace_config.task_type if ctx.ace_config.task_type != "text2music" else None
        ),
        repainting_start=ctx.ace_config.repainting_start if is_repaint else None,
        repainting_end=ctx.ace_config.repainting_end if is_repaint else None,
        repaint_mode=(ctx.ace_config.repaint_mode or None) if is_repaint else None,
        repaint_strength=(
            ctx.ace_config.repaint_strength
            if is_repaint and ctx.ace_config.repaint_mode else None
        ),
        repaint_latent_crossfade_frames=(
            ctx.ace_config.repaint_latent_crossfade_frames
            if is_repaint and ctx.ace_config.repaint_latent_crossfade_frames > 0 else None
        ),
        repaint_wav_crossfade_sec=(
            ctx.ace_config.repaint_wav_crossfade_sec
            if is_repaint and ctx.ace_config.repaint_wav_crossfade_sec > 0 else None
        ),
        audio_cover_strength=(
            ctx.ace_config.audio_cover_strength
            if ctx.ace_config.audio_cover_strength != 1.0 else None
        ),
        cover_noise_strength=(
            ctx.ace_config.cover_noise_strength
            if is_cover and ctx.ace_config.cover_noise_strength > 0 else None
        ),
        cot_caption=cot_caption or None,
        cot_lyrics=cot_lyrics or None,
        user_lora_id=_extract_user_lora_id(ctx.base_params),
    )
    gen_params = stored.model_dump(exclude_none=True)

    try:
        with db_factory() as session:
            if lock_active_job(session, job_id) is None:
                _cleanup_orphaned_files(
                    ctx.audio_dir, mp3_rel, wav_rel, raw_wav_rel,
                )
                return
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
            )
            create_generation_created_event(
                session,
                user_id=ctx.user_id,
                song_id=ctx.song_id,
                generation_id=generation.id,
            )
            session.commit()
    except Exception:
        _cleanup_orphaned_files(ctx.audio_dir, mp3_rel, wav_rel, raw_wav_rel)
        raise

    log.info("Generated: %s (seed=%s)", mp3_rel, seed)


def _generation_failure_message(exc: Exception | None) -> str:
    """Return what to show the user for a failed generation.

    A worker failure already carries ACE-Step's own cause (VRAM
    shortage, model error) — the one thing that makes the failure
    diagnosable — so it is passed through verbatim. Everything else
    goes through the generic sanitizer.
    """
    if isinstance(exc, WorkerTaskFailed) and str(exc):
        return str(exc)
    return _sanitize_error(exc)


def _finalize_generation_job(
    db_factory: sessionmaker[Session], job_id: str,
    count: int, completed: int, last_error: Exception | None,
) -> None:
    """Set final job status based on how many generations succeeded."""
    if _job_is_terminal(db_factory, job_id):
        return
    if completed == count:
        _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)
    elif completed > 0:
        _update_job(
            db_factory, job_id, JobStatus.PARTIAL, progress=completed / count,
            error=f"{completed}/{count} completed, {count - completed} failed: "
                  f"{_generation_failure_message(last_error)}",
            error_type="generation_error",
        )
    else:
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error=_generation_failure_message(last_error),
            error_type="generation_error",
        )


def _make_generation_progress_callback(
    db_factory: sessionmaker[Session], job_id: str,
    variant_index: int, count: int,
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
    db_factory: sessionmaker[Session], job_id: str,
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
        suffix=suffix, prefix="songmaker_src_", dir=_shared_tmp_dir(audio_dir),
    )
    os.close(fd)
    shutil.copy2(src_path, tmp_path)
    return tmp_path


def _resolve_raw_wav(mastered_wav_path: str) -> str | None:
    raw_path = Path(mastered_wav_path).with_suffix(".raw.wav")
    return str(raw_path) if raw_path.exists() else None


def _apply_repaint_overrides(
    ctx: GenerationContext, params: RepaintTaskParams,
) -> GenerationContext:
    raw_wav = _resolve_raw_wav(params.src_wav_path)
    audio_duration = ctx.ace_config.audio_duration

    overrides: dict = {
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

    new_ctx = replace(
        ctx,
        ace_config=replace(ctx.ace_config, **overrides),
        src_generation_id=params.src_generation_id,
    )
    if raw_wav:
        new_ctx = replace(
            new_ctx, raw_src_audio=_copy_to_shared_tmp(raw_wav, ctx.audio_dir),
        )
    return new_ctx


def _apply_cover_overrides(
    ctx: GenerationContext, params: CoverTaskParams,
) -> GenerationContext:
    overrides: dict = {
        "task_type": "cover",
        "src_audio_path": _copy_to_shared_tmp(params.src_wav_path, ctx.audio_dir),
        "prompt": params.prompt or ctx.ace_config.prompt,
        "lyrics": params.lyrics or ctx.ace_config.lyrics,
        "audio_cover_strength": params.audio_cover_strength,
    }
    if params.cover_noise_strength is not None:
        overrides["cover_noise_strength"] = params.cover_noise_strength

    return replace(
        ctx,
        ace_config=replace(ctx.ace_config, **overrides),
        src_generation_id=params.src_generation_id,
    )


async def run_generation_job(
    job_id: str, song_id: str, version_id: str, count: int,
    user_id: str,
    *,
    target_model: str,
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    data_dir: Path,
    redis: Redis,
    seed: int | None = None,
    repaint_params: RepaintTaskParams | None = None,
    cover_params: CoverTaskParams | None = None,
) -> None:

    import uuid

    import structlog

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type=JobType.GENERATE, song_id=song_id,
    )

    task_type = "cover" if cover_params else ("repaint" if repaint_params else "generate")
    log.info("Generation job %s: song=%s, count=%d, task=%s", job_id, song_id, count, task_type)

    shared_tmp_prefix = str(audio_dir / WORKER_SHARED_TMP_DIRNAME)

    try:
        if _job_is_terminal(db_factory, job_id):
            log.info("Generation job %s stopping because job is terminal", job_id)
            return

        _update_job(db_factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())
        if _job_is_terminal(db_factory, job_id):
            log.info("Generation job %s stopping because job is terminal", job_id)
            return

        try:
            ctx = await asyncio.to_thread(
                _build_generation_context,
                song_id, version_id, db_factory, audio_dir, data_dir,
                user_id=user_id, seed=seed, target_model=target_model,
            )
            if repaint_params is not None:
                ctx = _apply_repaint_overrides(ctx, repaint_params)
            elif cover_params is not None:
                ctx = _apply_cover_overrides(ctx, cover_params)
        except GenerationSetupError as exc:
            _update_job(
                db_factory, job_id, JobStatus.FAILED,
                error=str(exc), error_type="setup_error",
            )
            return

        tmp_copies: list[str] = []
        if (
            ctx.ace_config.src_audio_path
            and ctx.ace_config.src_audio_path.startswith(shared_tmp_prefix)
        ):
            tmp_copies.append(ctx.ace_config.src_audio_path)
        if ctx.raw_src_audio and ctx.raw_src_audio.startswith(shared_tmp_prefix):
            tmp_copies.append(ctx.raw_src_audio)

        try:
            completed = 0
            last_error: Exception | None = None

            for i in range(count):
                if _job_is_terminal(db_factory, job_id):
                    log.info("Generation job %s stopping because job is terminal", job_id)
                    return
                _update_job(db_factory, job_id, JobStatus.RUNNING, progress=i / count)
                on_progress = _make_generation_progress_callback(db_factory, job_id, i, count)
                on_heartbeat = _make_heartbeat_callback(db_factory, job_id)
                try:
                    gen_id = str(uuid.uuid4())
                    worker_result = await jobs.dispatch_generation(
                        ace_config=ctx.ace_config,
                        target_mode=ctx.model_name,
                        on_progress=on_progress,
                        on_heartbeat=on_heartbeat,
                        redis=redis,
                        db_factory=db_factory,
                    )
                    if _job_is_terminal(db_factory, job_id):
                        _discard_worker_audio(worker_result.audio_path)
                        log.info(
                            "Generation job %s stopping because job is terminal", job_id,
                        )
                        return
                    await asyncio.to_thread(
                        jobs.post_process_generation,
                        worker_audio_path=worker_result.audio_path,
                        worker_seed=worker_result.seed,
                        worker_cot_caption=worker_result.cot_caption,
                        worker_cot_lyrics=worker_result.cot_lyrics,
                        ctx=ctx,
                        generation_id=gen_id,
                        db_factory=db_factory,
                        job_id=job_id,
                    )
                    completed += 1
                except (NoCapacityError, WorkerTaskFailed) as exc:
                    log.warning("Generation %d/%d failed: %s", i + 1, count, exc)
                    last_error = exc
                except Exception as exc:
                    log.exception("Generation %d/%d failed: %s", i + 1, count, exc)
                    last_error = exc

            _finalize_generation_job(db_factory, job_id, count, completed, last_error)
        finally:
            for tmp in tmp_copies:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    except asyncio.CancelledError:
        log.warning("Generation job %s cancelled (arq timeout or worker shutdown)", job_id)
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error="Job cancelled: exceeded ARQ_JOB_TIMEOUT or worker shutdown",
            error_type="timeout",
        )
        raise
    except Exception as exc:
        log.exception("Generation job failed: %s", exc)
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error=_generation_failure_message(exc), error_type="generation_error",
        )


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
