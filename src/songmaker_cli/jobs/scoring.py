"""Scoring job runner — runs the scorer subprocess and persists results."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli import jobs
from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.db.queries import (
    get_claude_scoring_model,
    get_generation,
    save_scores,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.pipeline import PipelineConfig

from ._runtime import _job_is_terminal, _sanitize_error, _update_job

log = logging.getLogger(__name__)


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
        job_id=job_id, job_type=JobType.SCORE, generation_id=gen_id,
    )

    log.info("Scoring job %s: gen=%s, scorers=%s", job_id, gen_id, scorers or "all")

    try:
        if _job_is_terminal(db_factory, job_id):
            log.info("Scoring job %s stopping because job is terminal", job_id)
            return

        _update_job(db_factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())
        if _job_is_terminal(db_factory, job_id):
            log.info("Scoring job %s stopping because job is terminal", job_id)
            return

        with db_factory() as session:
            gen = get_generation(session, gen_id)
            if not gen:
                _update_job(
                    db_factory, job_id, JobStatus.FAILED,
                    error="Generation not found", error_type="setup_error",
                )
                return
            mp3_path_rel = gen.mp3_path
            song = gen.song
            ver = gen.version

            meta_kwargs: dict = {}
            if song or ver:
                meta_kwargs["title"] = song.title if song else ""
                if ver:
                    meta_kwargs["prompt"] = ver.prompt
                    meta_kwargs["lyrics"] = ver.lyrics
                    meta_kwargs["bpm"] = ver.bpm
                if song and song.vocal_language:
                    meta_kwargs["vocal_language"] = song.vocal_language
            resolved_model = get_claude_scoring_model(session)

        mp3_full = audio_dir / mp3_path_rel

        if not mp3_full.exists():
            _update_job(
                db_factory, job_id, JobStatus.FAILED,
                error="Audio file not found for scoring", error_type="setup_error",
            )
            log.error("Scoring job %s: MP3 not found at %s", job_id, mp3_path_rel)
            return

        scorer = jobs.get_scorer_process()
        if not scorer.alive:
            log.info("Scorer subprocess not running — spawning before scoring")

        config = PipelineConfig(device=device, claude_scoring_model=resolved_model)
        meta = SongMeta(**meta_kwargs) if meta_kwargs else None

        def _score_progress(completed: int, total: int, scorer_name: str) -> None:
            _update_job(db_factory, job_id, JobStatus.RUNNING, progress=completed / total)

        if _job_is_terminal(db_factory, job_id):
            log.info("Scoring job %s stopping because job is terminal", job_id)
            return

        song_scores = scorer.score(
            mp3_full, meta=meta, scorers=scorers, config=config, job_id=job_id,
            on_progress=_score_progress,
        )
        if _job_is_terminal(db_factory, job_id):
            log.info("Scoring job %s stopping because job is terminal", job_id)
            return

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
        _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)

    except TimeoutError as exc:
        log.error("Scoring job timed out: %s", exc)
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error=_sanitize_error(exc), error_type="timeout",
        )
    except Exception as exc:
        log.exception("Scoring job failed: %s", exc)
        _update_job(
            db_factory, job_id, JobStatus.FAILED,
            error=_sanitize_error(exc), error_type="scoring_error",
        )
