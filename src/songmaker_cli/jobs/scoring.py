"""Scoring job runner — runs the scorer subprocess and persists results."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli import jobs
from songmaker_cli.constants import JobStatus, JobType
from songmaker_cli.db.queries.generations import (
    get_generation,
    save_scores,
    set_generation_transcript,
)
from songmaker_cli.db.queries.jobs import lock_active_job
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.pipeline import PipelineConfig
from songmaker_cli.settings import get_settings

from ._runtime import _job_is_terminal, _sanitize_error, _update_job

log = logging.getLogger(__name__)

SCORING_JOB_TERMINAL_LOG: Final = "Scoring job %s stopping because job is terminal"


@dataclass(frozen=True)
class ScoringInput:
    mp3_path_rel: str
    meta: SongMeta | None


def run_scoring_job(
    job_id: str,
    gen_id: str,
    scorers: list[str] | None,
    *,
    db_factory: sessionmaker[Session],
    audio_dir: Path,
    device: str = "cpu",
) -> None:
    """Run scoring in a background thread, updating DB status."""
    import structlog

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_id=job_id,
        job_type=JobType.SCORE,
        generation_id=gen_id,
    )

    log.info("Scoring job %s: gen=%s, scorers=%s", job_id, gen_id, scorers or "all")

    try:
        if _job_is_terminal(db_factory, job_id):
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return

        _update_job(db_factory, job_id, JobStatus.RUNNING, worker_pid=os.getpid())
        if _job_is_terminal(db_factory, job_id):
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return

        scoring_input = _load_scoring_input(db_factory, job_id, gen_id)
        if scoring_input is None:
            return
        mp3_full = audio_dir / scoring_input.mp3_path_rel

        if not mp3_full.exists():
            _update_job(
                db_factory,
                job_id,
                JobStatus.FAILED,
                error="Audio file not found for scoring",
                error_type="setup_error",
            )
            log.error("Scoring job %s: MP3 not found at %s", job_id, scoring_input.mp3_path_rel)
            return

        scorer = jobs.get_scorer_process()
        if not scorer.alive:
            log.info("Scorer subprocess not running — spawning before scoring")

        settings = get_settings()
        config = PipelineConfig(
            device=device,
            scorer_timeout=settings.scorer_timeout_seconds,
            text_accuracy_timeout=settings.text_accuracy_timeout_seconds,
        )
        def _score_progress(completed: int, total: int, scorer_name: str) -> None:
            _update_job(db_factory, job_id, JobStatus.RUNNING, progress=completed / total)

        if _job_is_terminal(db_factory, job_id):
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return

        song_scores = scorer.score(
            mp3_full,
            meta=scoring_input.meta,
            scorers=scorers,
            config=config,
            job_id=job_id,
            on_progress=_score_progress,
        )
        if _job_is_terminal(db_factory, job_id):
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return

        if not _persist_scores(db_factory, job_id, gen_id, song_scores):
            return

        log.info(
            "Scored: %s (%d metrics written) — %s",
            scoring_input.mp3_path_rel,
            len(song_scores.to_dict()),
            song_scores.outcome_summary(),
        )
        _finish_scoring_job(db_factory, job_id, scorer, song_scores)

    except TimeoutError as exc:
        log.exception("Scoring job timed out: %s", exc)
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=_sanitize_error(exc, job_id),
            error_type="timeout",
        )
    except Exception as exc:
        log.exception("Scoring job failed: %s", exc)
        _update_job(
            db_factory,
            job_id,
            JobStatus.FAILED,
            error=_sanitize_error(exc, job_id),
            error_type="scoring_error",
        )


def _load_scoring_input(
    db_factory: sessionmaker[Session],
    job_id: str,
    gen_id: str,
) -> ScoringInput | None:
    with db_factory() as session:
        gen = get_generation(session, gen_id)
        if not gen:
            _update_job(
                db_factory,
                job_id,
                JobStatus.FAILED,
                error="Generation not found",
                error_type="setup_error",
            )
            return None
        song = gen.song
        version = gen.version
        meta = _score_meta(song, version)
        return ScoringInput(mp3_path_rel=gen.mp3_path, meta=meta)


def _score_meta(song, version) -> SongMeta | None:
    if not song and not version:
        return None
    meta_kwargs = {"title": song.title if song else ""}
    if version:
        meta_kwargs.update(prompt=version.prompt, lyrics=version.lyrics, bpm=version.bpm)
    if song and song.vocal_language:
        meta_kwargs["vocal_language"] = song.vocal_language
    return SongMeta(**meta_kwargs)


def _persist_scores(
    db_factory: sessionmaker[Session],
    job_id: str,
    gen_id: str,
    song_scores: SongScores,
) -> bool:
    with db_factory() as session:
        if lock_active_job(session, job_id) is None:
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return False
        save_scores(
            session,
            gen_id,
            song_scores.to_dict(),
            refreshed_keys=song_scores.refreshed_output_keys(),
        )
        if text_accuracy := song_scores.text_accuracy:
            set_generation_transcript(
                session, gen_id, text_accuracy.transcript, text_accuracy.whisper_cues,
            )
        session.commit()
    return True


def _finish_scoring_job(
    db_factory: sessionmaker[Session],
    job_id: str,
    scorer,
    song_scores: SongScores,
) -> None:
    if song_scores.any_child_scorer_timed_out:
        log.warning(
            "Scoring job %s left a scorer running past its budget — recycling the child",
            job_id,
        )
        scorer.recycle()
    _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)
