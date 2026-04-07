"""Background job runners for generation and scoring."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from acestep_engine import AceStepClient
from acestep_engine.errors import AudioDownloadError
from acestep_engine.models import AceStepConfig
from songmaker_cli.api_models import StoredGenerationParams
from songmaker_cli.config import build_ace_config, load_generation_defaults, resolve_model_mode
from songmaker_cli.db.models import GenerationPreset
from songmaker_cli.db.queries import (
    create_generation,
    get_claude_model,
    get_default_preset,
    get_generation,
    get_song,
    get_version,
    save_scores,
    update_job_heartbeat,
    update_job_status,
)
from songmaker_cli.generate import generate_single
from songmaker_cli.parser import AlbumMeta, SongMeta
from songmaker_cli.scoring.pipeline import PipelineConfig
from songmaker_cli.scoring.subprocess_runner import get_scorer_process

log = logging.getLogger(__name__)

_USER_FACING_ERRORS: tuple[tuple[type[Exception], str], ...] = (
    (AudioDownloadError, "Failed to download generated audio"),
    (ConnectionError, "ACE-Step server not reachable"),
    (TimeoutError, "Generation timed out"),
    (RuntimeError, "Internal error during processing"),
)


def _sanitize_error(exc: Exception) -> str:
    """Return a user-safe error message, logging the full exception."""
    if isinstance(exc, GenerationSetupError):
        return str(exc)
    for exc_type, message in _USER_FACING_ERRORS:
        if isinstance(exc, exc_type):
            return message
    return "An unexpected error occurred"


@dataclass
class GenerationContext:
    song_id: str
    version_id: str
    meta: SongMeta
    album_meta: AlbumMeta
    ace_config: AceStepConfig
    audio_dir: Path
    user_id: str
    model_name: str | None
    client: AceStepClient
    base_params: dict = field(default_factory=dict)
    src_generation_id: str | None = None
    raw_src_audio: str | None = None


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

        version = get_version(session, version_id, song_id)
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
    from songmaker_cli.config import get_builtin_defaults, resolve_model_mode
    from songmaker_cli.db.models import User

    with db_factory() as session:
        user = session.query(User).filter_by(id=user_id).first()
        if not user or not user.default_generation_config:
            model_mode = resolve_model_mode(model_name)
            preset = get_default_preset(session, user_id, model_mode)
            return dict(preset.params) if preset else None

        config = user.default_generation_config
        builtins = get_builtin_defaults()
        if config in builtins:
            return dict(builtins[config])

        preset = session.query(GenerationPreset).filter_by(id=config).first()
        return dict(preset.params) if preset else None


def _build_generation_context(
    song_id: str, version_id: str,
    db_factory: sessionmaker[Session], audio_dir: Path, data_dir: Path,
    user_id: str, seed: int | None = None,
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
        global_defaults=load_generation_defaults(db_factory, data_dir),
        preset_params=preset_params,
        seed=seed,
    )
    if model_name:
        ace_config = replace(ace_config, model=model_name)

    if ace_config.reference_audio:
        abs_ref = (audio_dir / ace_config.reference_audio).resolve()
        inside_audio_dir = str(abs_ref).startswith(str(audio_dir.resolve()))
        if ".." in ace_config.reference_audio or not inside_audio_dir:
            log.warning("Reference audio path traversal blocked: %s", ace_config.reference_audio)
            ace_config = replace(ace_config, reference_audio="")
        elif abs_ref.exists():
            ace_config = replace(ace_config, reference_audio=str(abs_ref))
        else:
            log.warning("Reference audio not found: %s", abs_ref)
            ace_config = replace(ace_config, reference_audio="")

    return GenerationContext(
        song_id=song_id,
        version_id=version_id,
        meta=meta,
        album_meta=album_meta,
        ace_config=ace_config,
        audio_dir=audio_dir,
        user_id=user_id,
        model_name=model_name,
        client=client,
        base_params=meta.generation_params,
    )


def _run_single_generation(
    ctx: GenerationContext, generation_id: str,
    db_factory: sessionmaker[Session],
    on_progress: Callable[[str], None] | None = None,
) -> None:
    """Generate one song variant, master it, and persist the DB record.

    On ACE-Step/mastering failure: raises (caller tracks partial progress).
    On DB failure after files written: cleans up orphaned files, then raises.
    """
    result = generate_single(
        ctx.meta, ctx.album_meta, ctx.ace_config,
        ctx.audio_dir, ctx.user_id, generation_id,
        client=ctx.client,
        on_progress=on_progress,
        raw_src_audio=ctx.raw_src_audio,
    )

    mp3_rel = f"{ctx.user_id}/{generation_id}.mp3"
    wav_rel = f"{ctx.user_id}/{generation_id}.wav"
    is_repaint = ctx.ace_config.task_type == "repaint"
    is_cover = ctx.ace_config.task_type == "cover"
    stored = StoredGenerationParams(
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
        audio_cover_strength=ctx.ace_config.audio_cover_strength if is_cover else None,
        cover_noise_strength=(
            ctx.ace_config.cover_noise_strength
            if is_cover and ctx.ace_config.cover_noise_strength > 0 else None
        ),
        cot_caption=result.cot_caption or None,
        cot_lyrics=result.cot_lyrics or None,
    )
    gen_params = stored.model_dump(exclude_none=True)

    try:
        with db_factory() as session:
            create_generation(
                session,
                song_id=ctx.song_id,
                version_id=ctx.version_id,
                mp3_path=mp3_rel,
                seed=result.seed,
                generation_params=gen_params,
                wav_path=wav_rel,
                model_mode=resolve_model_mode(ctx.model_name),
                src_generation_id=ctx.src_generation_id,
            )
            session.commit()
    except Exception:
        _cleanup_orphaned_files(ctx.audio_dir, mp3_rel, wav_rel)
        raise

    log.info("Generated: %s (seed=%s)", mp3_rel, result.seed)


def _finalize_generation_job(
    db_factory: sessionmaker[Session], job_id: str,
    count: int, completed: int, last_error: Exception | None,
) -> None:
    """Set final job status based on how many generations succeeded."""
    if completed == count:
        _update_job(db_factory, job_id, "completed", progress=1.0)
    elif completed > 0:
        _update_job(
            db_factory, job_id, "partial", progress=completed / count,
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


_DIFFUSION_STEP_PATTERN = re.compile(r"(\d+)/(\d+)\s*\[")
_PROGRESS_THROTTLE_SECONDS = 2.0
_HEARTBEAT_INTERVAL_SECONDS = 30.0


def _parse_step_fraction(progress_text: str) -> float | None:
    """Extract a 0..1 fraction from diffusion step text like '8/50 [00:02<00:13]'.

    Only matches the tqdm-style progress format with a bracket suffix to avoid
    false positives from non-progress text like 'LM chunk 1/1'.
    """
    m = _DIFFUSION_STEP_PATTERN.search(progress_text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            return min(current / total, 1.0)
    return None


def _make_generation_progress_callback(
    db_factory: sessionmaker[Session], job_id: str,
    variant_index: int, count: int,
) -> Callable[[str], None]:
    last_update = 0.0
    last_heartbeat = 0.0

    def _on_progress(progress_text: str) -> None:
        nonlocal last_update, last_heartbeat
        now = time.monotonic()
        step_fraction = _parse_step_fraction(progress_text)
        if step_fraction is not None:
            if now - last_update < _PROGRESS_THROTTLE_SECONDS:
                return
            combined = (variant_index + step_fraction) / count
            _update_job(db_factory, job_id, "running", progress=combined)
            last_update = now
            last_heartbeat = now
            return
        if now - last_heartbeat >= _HEARTBEAT_INTERVAL_SECONDS:
            _touch_heartbeat(db_factory, job_id)
            last_heartbeat = now

    return _on_progress


def _copy_to_tmp(src_path: str) -> str:
    suffix = Path(src_path).suffix
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="songmaker_src_")
    os.close(fd)
    shutil.copy2(src_path, tmp_path)
    return tmp_path


def _resolve_raw_wav(mastered_wav_path: str) -> str | None:
    raw_path = Path(mastered_wav_path).with_suffix(".raw.wav")
    return str(raw_path) if raw_path.exists() else None


def _apply_task_overrides(
    ctx: GenerationContext, task_type: str, params: dict,
) -> GenerationContext:
    src_wav = params["src_wav_path"]
    raw_wav = _resolve_raw_wav(src_wav)

    overrides: dict = {
        "task_type": task_type,
        "src_audio": _copy_to_tmp(src_wav),
        "prompt": params.get("prompt", ctx.ace_config.prompt),
        "lyrics": params.get("lyrics", ctx.ace_config.lyrics),
    }
    if task_type == "repaint":
        duration = ctx.ace_config.duration
        overrides["repainting_start"] = params["repainting_start"] * duration
        overrides["repainting_end"] = params["repainting_end"] * duration
        if params.get("repaint_mode"):
            overrides["repaint_mode"] = params["repaint_mode"]
        if params.get("repaint_strength") is not None:
            overrides["repaint_strength"] = params["repaint_strength"]
        if params.get("repaint_latent_crossfade_frames") is not None:
            overrides["repaint_latent_crossfade_frames"] = params["repaint_latent_crossfade_frames"]
        if params.get("repaint_wav_crossfade_sec") is not None:
            overrides["repaint_wav_crossfade_sec"] = params["repaint_wav_crossfade_sec"]
    elif task_type == "cover":
        overrides["audio_cover_strength"] = params["audio_cover_strength"]
        if params.get("cover_noise_strength") is not None:
            overrides["cover_noise_strength"] = params["cover_noise_strength"]

    updated_config = replace(ctx.ace_config, **overrides)
    new_ctx = replace(ctx, ace_config=updated_config)
    if task_type == "repaint" and raw_wav:
        new_ctx = replace(new_ctx, raw_src_audio=_copy_to_tmp(raw_wav))
    return new_ctx


def run_generation_job(
    job_id: str, song_id: str, version_id: str, count: int,
    user_id: str,
    db_factory: sessionmaker[Session] | None = None,
    audio_dir: Path | None = None,
    data_dir: Path | None = None,
    seed: int | None = None,
    repaint_params: dict | None = None,
    cover_params: dict | None = None,
) -> None:
    assert db_factory is not None, "db_factory is required"
    assert audio_dir is not None, "audio_dir is required"
    assert data_dir is not None, "data_dir is required"

    import uuid

    import structlog
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type="generate", song_id=song_id,
    )

    task_type = "cover" if cover_params else ("repaint" if repaint_params else "generate")
    log.info("Generation job %s: song=%s, count=%d, task=%s", job_id, song_id, count, task_type)

    try:
        _update_job(db_factory, job_id, "running", worker_pid=os.getpid())

        try:
            ctx = _build_generation_context(
                song_id, version_id, db_factory, audio_dir, data_dir,
                user_id=user_id, seed=seed,
            )
            if repaint_params:
                ctx = _apply_task_overrides(ctx, "repaint", repaint_params)
                ctx = replace(ctx, src_generation_id=repaint_params.get("src_generation_id"))
            elif cover_params:
                ctx = _apply_task_overrides(ctx, "cover", cover_params)
                ctx = replace(ctx, src_generation_id=cover_params.get("src_generation_id"))
        except GenerationSetupError as exc:
            _update_job(db_factory, job_id, "failed", error=str(exc), error_type="setup_error")
            return

        tmp_copies: list[str] = []
        if ctx.ace_config.src_audio and ctx.ace_config.src_audio.startswith(
            tempfile.gettempdir()
        ):
            tmp_copies.append(ctx.ace_config.src_audio)
        if ctx.raw_src_audio and ctx.raw_src_audio.startswith(tempfile.gettempdir()):
            tmp_copies.append(ctx.raw_src_audio)

        try:
            completed = 0
            last_error: Exception | None = None

            for i in range(count):
                _update_job(db_factory, job_id, "running", progress=i / count)
                on_progress = _make_generation_progress_callback(db_factory, job_id, i, count)
                try:
                    gen_id = str(uuid.uuid4())
                    _run_single_generation(ctx, gen_id, db_factory, on_progress=on_progress)
                    completed += 1
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

    except Exception as exc:
        log.exception("Generation job failed: %s", exc)
        _update_job(
            db_factory, job_id, "failed",
            error=_sanitize_error(exc), error_type="generation_error",
        )


def run_scoring_job(
    job_id: str, gen_id: str, scorers: list[str] | None,
    db_factory: sessionmaker[Session] | None = None,
    audio_dir: Path | None = None,
    device: str = "cpu",
) -> None:
    """Run scoring in a background thread, updating DB status."""
    assert db_factory is not None, "db_factory is required"
    assert audio_dir is not None, "audio_dir is required"

    import structlog
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id, job_type="score", generation_id=gen_id,
    )

    log.info("Scoring job %s: gen=%s, scorers=%s", job_id, gen_id, scorers or "all")

    try:
        _update_job(db_factory, job_id, "running", worker_pid=os.getpid())

        from songmaker_cli.constants import CLAUDE_SCORING_MODEL, SETTING_CLAUDE_SCORING_MODEL

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
            resolved_model = get_claude_model(
                session, SETTING_CLAUDE_SCORING_MODEL, CLAUDE_SCORING_MODEL,
            )

        mp3_full = audio_dir / mp3_path_rel

        if not mp3_full.exists():
            _update_job(
                db_factory, job_id, "failed",
                error="Audio file not found for scoring", error_type="setup_error",
            )
            log.error("Scoring job %s: MP3 not found at %s", job_id, mp3_path_rel)
            return

        scorer = get_scorer_process()
        if not scorer.alive:
            log.info("Scorer subprocess not running — spawning before scoring")

        config = PipelineConfig(device=device, claude_scoring_model=resolved_model)
        meta = SongMeta(**meta_kwargs) if meta_kwargs else None

        def _score_progress(completed: int, total: int, scorer_name: str) -> None:
            _update_job(db_factory, job_id, "running", progress=completed / total)

        song_scores = scorer.score(
            mp3_full, meta=meta, scorers=scorers, config=config, job_id=job_id,
            on_progress=_score_progress,
        )
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

    except TimeoutError as exc:
        log.error("Scoring job timed out: %s", exc)
        _update_job(
            db_factory, job_id, "failed",
            error=_sanitize_error(exc), error_type="timeout",
        )
    except Exception as exc:
        log.exception("Scoring job failed: %s", exc)
        _update_job(
            db_factory, job_id, "failed",
            error=_sanitize_error(exc), error_type="scoring_error",
        )


def _update_job(factory, job_id: str, status: str, **kwargs) -> None:
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            with factory() as session:
                update_job_status(session, job_id, status, **kwargs)
                session.commit()
            return
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                log.warning("Retrying job %s status update to %s", job_id, status)
    log.exception("Failed to update job %s to %s after retry", job_id, status)
    raise RuntimeError(
        f"Job {job_id} status update to {status!r} failed after 2 attempts"
    ) from last_exc


def _touch_heartbeat(factory, job_id: str) -> None:
    try:
        with factory() as session:
            update_job_heartbeat(session, job_id)
            session.commit()
    except Exception:
        log.error(
            "Heartbeat update failed for job %s — "
            "worker may be falsely declared stale if DB stays unreachable",
            job_id, exc_info=True,
        )


async def load_model_on_worker(ctx, job_id: str, worker_id: str, mode: str) -> None:
    import httpx

    from songmaker_cli.db.queries import get_worker_identity
    from songmaker_cli.internal_api import INTERNAL_TOKEN_ENV, INTERNAL_TOKEN_HEADER
    from songmaker_cli.worker_base import _get_db_factory

    factory = _get_db_factory()
    _update_job(factory, job_id, "running", worker_pid=os.getpid())

    with factory() as session:
        worker = get_worker_identity(session, worker_id)
    if worker is None:
        _update_job(
            factory, job_id, "failed",
            error=f"Worker '{worker_id}' not registered",
            error_type="worker_missing",
        )
        return

    token = os.environ.get(INTERNAL_TOKEN_ENV, "")
    headers = {INTERNAL_TOKEN_HEADER: token}
    url = f"http://{worker.host}:{worker.port}/load_model"

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(url, json={"mode": mode}, headers=headers)
    except httpx.HTTPError as exc:
        _update_job(
            factory, job_id, "failed",
            error=f"Worker unreachable: {exc}",
            error_type="worker_unreachable",
        )
        return

    if response.status_code >= 400:
        _update_job(
            factory, job_id, "failed",
            error=f"Worker returned {response.status_code}: {response.text[:200]}",
            error_type="worker_error",
        )
        return

    _update_job(factory, job_id, "completed", progress=1.0)


def _cleanup_orphaned_files(audio_dir: Path, *rel_paths: str) -> None:
    for rel in rel_paths:
        path = audio_dir / rel
        try:
            if path.exists():
                path.unlink()
        except OSError:
            log.warning("Failed to clean orphaned file: %s", rel)
