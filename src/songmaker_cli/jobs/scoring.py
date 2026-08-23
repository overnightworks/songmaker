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
    lock_active_job,
    save_scores,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.lyrical_coherence import (
    CoherenceJudgeConfig,
    judge_lyrical_coherence,
)
from songmaker_cli.scoring.pipeline import PipelineConfig
from songmaker_cli.scoring.registry import CHILD_SCORER_NAMES, LYRICAL_COHERENCE_SCORER
from songmaker_cli.settings import get_settings

from ._runtime import _job_is_terminal, _sanitize_error, _update_job

log = logging.getLogger(__name__)


def _split_by_host(scorers: list[str] | None) -> tuple[list[str] | None, bool]:
    """The scorers the child runs, and whether the parent judges coherence.

    ``None`` means "everything this process runs" on both sides.
    """
    if scorers is None:
        return None, True
    return (
        [name for name in scorers if name in CHILD_SCORER_NAMES],
        LYRICAL_COHERENCE_SCORER in scorers,
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

        settings = get_settings()
        config = PipelineConfig(
            device=device,
            scorer_timeout=settings.scorer_timeout_seconds,
            text_accuracy_timeout=settings.text_accuracy_timeout_seconds,
        )
        child_scorers, judge_coherence = _split_by_host(scorers)
        meta = SongMeta(**meta_kwargs) if meta_kwargs else None

        def _score_progress(completed: int, total: int, scorer_name: str) -> None:
            _update_job(db_factory, job_id, JobStatus.RUNNING, progress=completed / total)

        if _job_is_terminal(db_factory, job_id):
            log.info("Scoring job %s stopping because job is terminal", job_id)
            return

        song_scores = scorer.score(
            mp3_full, meta=meta, scorers=child_scorers, config=config, job_id=job_id,
            on_progress=_score_progress,
        )
        if _job_is_terminal(db_factory, job_id):
            log.info("Scoring job %s stopping because job is terminal", job_id)
            return

        if judge_coherence:
            song_scores = judge_lyrical_coherence(song_scores, meta, CoherenceJudgeConfig(
                model=resolved_model,
                api_key=settings.anthropic_api_key,
                timeout=settings.scorer_timeout_seconds,
            ))

        scores_dict = song_scores.to_dict()

        text_accuracy = song_scores.text_accuracy

        with db_factory() as session:
            from songmaker_cli.db.models import Generation as GenModel
            if lock_active_job(session, job_id) is None:
                log.info("Scoring job %s stopping because job is terminal", job_id)
                return
            save_scores(
                session, gen_id, scores_dict,
                refreshed_keys=song_scores.refreshed_output_keys(),
            )
            if text_accuracy is not None:
                gen_record = session.query(GenModel).filter_by(id=gen_id).first()
                if gen_record:
                    gen_record.whisper_text = text_accuracy.transcript
                    gen_record.whisper_cues = [
                        cue.model_dump() for cue in text_accuracy.whisper_cues
                    ]
            session.commit()

        log.info(
            "Scored: %s (%d metrics written) — %s",
            mp3_path_rel, len(scores_dict), song_scores.outcome_summary(),
        )
        if song_scores.any_scorer_timed_out:
            log.warning(
                "Scoring job %s left a scorer running past its budget — recycling the child",
                job_id,
            )
            scorer.recycle()
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
