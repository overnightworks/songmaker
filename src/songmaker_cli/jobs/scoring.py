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
from songmaker_cli.db.queries import (
    get_generation,
    get_judge_model,
    get_judge_provider,
    lock_active_job,
    save_scores,
)
from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.lyrical_coherence import (
    CoherenceJudgeConfig,
    judge_lyrical_coherence,
)
from songmaker_cli.scoring.models import ScorerOutcome, SongScores
from songmaker_cli.scoring.pipeline import PipelineConfig
from songmaker_cli.scoring.registry import CHILD_SCORER_NAMES, LYRICAL_COHERENCE_SCORER
from songmaker_cli.settings import get_settings

from ._runtime import JudgeFailureError, _job_is_terminal, _sanitize_error, _update_job

log = logging.getLogger(__name__)

SCORING_JOB_TERMINAL_LOG: Final = "Scoring job %s stopping because job is terminal"


@dataclass(frozen=True)
class ScoringInput:
    mp3_path_rel: str
    meta: SongMeta | None
    judge_provider: str | None
    judge_model: str | None


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


def _judge_failure_reason(scores: SongScores) -> str | None:
    """Why the lyrical-coherence judge itself failed this run, if it did.

    Never for a legitimate skip (no lyrics, no transcript). A provider
    failure or a timeout means this run has no judge verdict, so the job must
    not look green even though the child scores remain useful data.
    """
    for run in scores.runs:
        if run.scorer == LYRICAL_COHERENCE_SCORER and run.outcome in (
            ScorerOutcome.FAILED,
            ScorerOutcome.TIMED_OUT,
        ):
            return run.detail
    return None


def run_scoring_job(
    job_id: str,
    gen_id: str,
    scorers: list[str] | None,
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
        child_scorers, judge_coherence = _split_by_host(scorers)

        def _score_progress(completed: int, total: int, scorer_name: str) -> None:
            _update_job(db_factory, job_id, JobStatus.RUNNING, progress=completed / total)

        if _job_is_terminal(db_factory, job_id):
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return

        song_scores = scorer.score(
            mp3_full,
            meta=scoring_input.meta,
            scorers=child_scorers,
            config=config,
            job_id=job_id,
            on_progress=_score_progress,
        )
        if _job_is_terminal(db_factory, job_id):
            log.info(SCORING_JOB_TERMINAL_LOG, job_id)
            return

        if judge_coherence:
            song_scores = judge_lyrical_coherence(
                song_scores,
                scoring_input.meta,
                CoherenceJudgeConfig(
                    provider=scoring_input.judge_provider,
                    model=scoring_input.judge_model,
                    timeout=settings.scorer_timeout_seconds,
                ),
            )
        judge_failure = _judge_failure_reason(song_scores) if judge_coherence else None

        if not _persist_scores(db_factory, job_id, gen_id, song_scores):
            return

        log.info(
            "Scored: %s (%d metrics written) — %s",
            scoring_input.mp3_path_rel,
            len(song_scores.to_dict()),
            song_scores.outcome_summary(),
        )
        _finish_scoring_job(db_factory, job_id, scorer, song_scores, judge_failure)

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
        judge_provider = get_judge_provider(session)
        return ScoringInput(
            mp3_path_rel=gen.mp3_path,
            meta=meta,
            judge_provider=judge_provider,
            judge_model=get_judge_model(session, judge_provider),
        )


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
    from songmaker_cli.db.models import Generation

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
            generation = session.query(Generation).filter_by(id=gen_id).first()
            if generation:
                generation.whisper_text = text_accuracy.transcript
                generation.whisper_cues = [cue.model_dump() for cue in text_accuracy.whisper_cues]
        session.commit()
    return True


def _finish_scoring_job(
    db_factory: sessionmaker[Session],
    job_id: str,
    scorer,
    song_scores: SongScores,
    judge_failure: str | None,
) -> None:
    if song_scores.any_child_scorer_timed_out:
        log.warning(
            "Scoring job %s left a scorer running past its budget — recycling the child",
            job_id,
        )
        scorer.recycle()
    if judge_failure is not None:
        _update_job(
            db_factory,
            job_id,
            JobStatus.PARTIAL,
            progress=1.0,
            error=_sanitize_error(JudgeFailureError(judge_failure), job_id),
            error_type="judge_error",
        )
        return
    _update_job(db_factory, job_id, JobStatus.COMPLETED, progress=1.0)
