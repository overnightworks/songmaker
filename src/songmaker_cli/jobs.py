"""Background job runners for generation and scoring."""

from __future__ import annotations

import logging
from pathlib import Path

from songmaker_cli.constants import OUTPUT_ROOT
from songmaker_cli.db.engine import get_session_factory

log = logging.getLogger(__name__)


def run_generation_job(
    job_id: str, song_id: str, version_id: str, count: int,
) -> None:
    """Run generation in a background thread, updating DB status."""
    factory = get_session_factory()

    try:
        _update_job(factory, job_id, "running")

        with factory() as session:
            from songmaker_cli.db.queries import get_song
            song = get_song(session, song_id)
            if not song:
                _update_job(factory, job_id, "failed", error="Song not found")
                return

            version = next((v for v in song.versions if v.id == version_id), None)
            if not version:
                _update_job(factory, job_id, "failed", error="Version not found")
                return

            album = song.album
            album_name = album.title.lower().replace(" ", "_") if album else "unknown"
            album_artist = album.artist if album else ""
            song_title = song.title
            track_number = song.track_number
            lyrics = version.lyrics
            prompt = version.prompt
            bpm = version.bpm
            duration = version.duration
            key = version.key
            language = song.language

        from acestep_engine import AceStepClient
        from songmaker_cli.config import build_ace_config, find_project_root
        from songmaker_cli.parser import SongMeta

        meta = SongMeta(
            title=song_title,
            album=album_name,
            track=str(track_number),
            prompt=prompt,
            lyrics=lyrics,
            generation_params={
                k: v for k, v in {
                    "bpm": bpm, "duration": duration, "key": key, "language": language,
                }.items() if v
            },
        )

        client = AceStepClient()
        if not client.is_available:
            _update_job(factory, job_id, "failed", error="ACE-Step server not reachable")
            return

        server_info = client.server_info()
        model_name = server_info.model if server_info else None
        ace_config = build_ace_config(meta, model_name=model_name)

        project_root = find_project_root(Path.cwd())
        output_root = (project_root / OUTPUT_ROOT) if project_root else Path(OUTPUT_ROOT)

        from songmaker_cli.generate import generate_single
        from songmaker_cli.parser import AlbumMeta

        album_meta = AlbumMeta(title=album_name, artist=album_artist)

        for i in range(count):
            progress = i / count
            _update_job(factory, job_id, "running", progress=progress)

            result = generate_single(meta, album_meta, ace_config, output_root, client=client)

            mp3_rel = f"{album_name}/{result.mp3_path.name}"
            gen_params = {
                "acestep_model": model_name,
                "bpm": bpm,
                "duration": duration,
                "key": key,
                "guidance_scale": ace_config.guidance_scale,
                "inference_steps": ace_config.inference_steps,
                "shift": ace_config.shift,
                "lm_temperature": ace_config.lm_temperature,
                "infer_method": ace_config.infer_method,
                "think_mode": ace_config.think_mode,
            }

            with factory() as session:
                from songmaker_cli.db.queries import create_generation
                create_generation(
                    session,
                    song_id=song_id,
                    version_id=version_id,
                    mp3_path=mp3_rel,
                    seed=result.seed,
                    generation_params=gen_params,
                )
                session.commit()

            log.info("Generated %d/%d: %s (seed=%s)", i + 1, count, mp3_rel, result.seed)

        _update_job(factory, job_id, "completed", progress=1.0)

    except Exception as exc:
        log.exception("Generation job failed: %s", exc)
        _update_job(factory, job_id, "failed", error=str(exc))


def run_scoring_job(
    job_id: str, gen_id: str, scorers: list[str] | None,
) -> None:
    """Run scoring in a background thread, updating DB status."""
    factory = get_session_factory()

    try:
        _update_job(factory, job_id, "running")

        with factory() as session:
            from songmaker_cli.db.queries import get_generation
            gen = get_generation(session, gen_id)
            if not gen:
                _update_job(factory, job_id, "failed", error="Generation not found")
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

        from songmaker_cli.config import find_project_root
        from songmaker_cli.constants import OUTPUT_ROOT

        project_root = find_project_root(Path.cwd())
        output_root = (project_root / OUTPUT_ROOT) if project_root else Path(OUTPUT_ROOT)
        mp3_full = output_root / mp3_path_rel

        if not mp3_full.exists():
            _update_job(factory, job_id, "failed", error=f"MP3 not found: {mp3_path_rel}")
            return

        from songmaker_cli.parser import SongMeta
        from songmaker_cli.scoring import run_scoring_pipeline
        from songmaker_cli.scoring.pipeline import PipelineConfig

        device = _detect_device()
        config = PipelineConfig(device=device)
        meta = SongMeta(**meta_kwargs) if meta_kwargs else None
        song_scores = run_scoring_pipeline(mp3_full, meta=meta, scorers=scorers, config=config)
        scores_dict = song_scores.to_dict()

        whisper_text = None
        if song_scores.text_accuracy:
            whisper_text = "\n".join(song_scores.text_accuracy.transcribed_line_texts)

        with factory() as session:
            from songmaker_cli.db.models import Generation as GenModel
            from songmaker_cli.db.queries import save_scores
            save_scores(session, gen_id, scores_dict)
            if whisper_text is not None:
                gen_record = session.query(GenModel).filter_by(id=gen_id).first()
                if gen_record:
                    gen_record.whisper_text = whisper_text
            session.commit()

        log.info("Scored: %s (%d metrics)", mp3_path_rel, len(scores_dict))
        _update_job(factory, job_id, "completed", progress=1.0)

    except Exception as exc:
        log.exception("Scoring job failed: %s", exc)
        _update_job(factory, job_id, "failed", error=str(exc))


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
            from songmaker_cli.db.queries import update_job_status
            update_job_status(session, job_id, status, **kwargs)
            session.commit()
    except Exception:
        log.exception("Failed to update job %s to %s", job_id, status)
