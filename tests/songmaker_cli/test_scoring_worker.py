"""Tests for the scoring worker."""

from __future__ import annotations

import asyncio
import itertools
import os
import signal
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from logline.testing import configured
from redis import Redis
from support.app_processes import leased_owner_ids
from support.score_jobs import a_scoreable_take, queued_score_job

from songmaker_cli.db.queries.jobs import get_job
from songmaker_cli.job_payloads import ScorePayload
from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobStatus, JobType
from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.settings import get_settings

STOP_WITHIN_SECONDS = 10
SHUTDOWN_HOLD_SECONDS = 0.5
SCORER_WAIT_SECONDS = 10
TIME_LIMIT_SECONDS = 3
TOOK_TOO_LONG_KEY = "jobFailure.tookTooLong"


def _run(coro):
    return asyncio.run(coro)


def test_a_stop_signal_lets_a_running_job_finish_before_the_scorer_and_the_lease_end(
    stop_signal_handlers, installed_scorer_restored, redis_url, readiness_file,
) -> None:
    job_started, job_may_finish = asyncio.Event(), asyncio.Event()
    ended: list[str | tuple[str, set[str]]] = []

    with Redis.from_url(redis_url, decode_responses=True) as reader:
        scorer = MagicMock()
        scorer.shutdown.side_effect = lambda: ended.append(("scorer", leased_owner_ids(reader)))
        worker = ScoringWorker(
            get_settings().model_copy(update={"redis_url": redis_url}),
            scorer=scorer, readiness_file=readiness_file,
        )
        worker.get_db_factory = MagicMock()
        worker.claim_next_job = MagicMock(
            side_effect=itertools.chain(
                [ClaimedJob("j1", JobType.SCORE, None)], itertools.repeat(None),
            ),
        )

        async def run_claimed(_claimed: ClaimedJob) -> None:
            job_started.set()
            await job_may_finish.wait()
            ended.append("job")

        worker.run_claimed = run_claimed

        async def scenario() -> bool:
            running = asyncio.create_task(worker.run())
            async with asyncio.timeout(STOP_WITHIN_SECONDS):
                await job_started.wait()
                os.kill(os.getpid(), signal.SIGTERM)
                done, _ = await asyncio.wait([running], timeout=SHUTDOWN_HOLD_SECONDS)
                ended_with_job_running = bool(done)
                job_may_finish.set()
                await running
            return ended_with_job_running

        with configured("restored-after-the-test"):
            ended_with_job_running = _run(scenario())

        leases_after = leased_owner_ids(reader)

    assert ended_with_job_running is False
    assert ended == ["job", ("scorer", {worker.owner_id})]
    assert leases_after == set()


@pytest.fixture
def scoring_worker_on_pg(workers_on_db, readiness_file: Path, tmp_path: Path):
    """A scoring worker with a short time limit, on this test's database."""
    settings = get_settings().model_copy(
        update={"audio_dir": str(tmp_path), "worker_job_timeout": TIME_LIMIT_SECONDS},
    )
    return ScoringWorker(settings, readiness_file=readiness_file)


def test_a_score_job_outlasting_its_time_limit_fails_as_too_slow_and_frees_the_worker(
    scoring_worker_on_pg, pg_factory, scorer_requests, tmp_path,
) -> None:
    take = a_scoreable_take(pg_factory, tmp_path)
    scorer_may_answer = threading.Event()
    answers = itertools.chain([scorer_may_answer], itertools.repeat(None))

    def score(*_args, **_kwargs) -> SongScores:
        if (blocker := next(answers)) is not None:
            blocker.wait(SCORER_WAIT_SECONDS)
        return SongScores()

    scorer_requests.side_effect = score
    with pg_factory() as session:
        slow = queued_score_job(session, payload=ScorePayload(gen_id=take)).id
        fast = queued_score_job(session, payload=ScorePayload(gen_id=take)).id
        session.commit()

    async def run_both_then_let_the_slow_scorer_answer() -> None:
        for _ in range(2):
            await scoring_worker_on_pg.run_claimed(scoring_worker_on_pg.claim_next_job())
        scorer_may_answer.set()

    _run(run_both_then_let_the_slow_scorer_answer())

    with pg_factory() as session:
        slow_row, fast_row = get_job(session, slow), get_job(session, fast)
        assert (slow_row.status, slow_row.error_type, slow_row.error_message.key) == (
            JobStatus.FAILED, "timeout", TOOK_TOO_LONG_KEY,
        )
        assert fast_row.status == JobStatus.COMPLETED
