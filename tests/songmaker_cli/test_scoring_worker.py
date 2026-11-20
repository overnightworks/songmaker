"""Tests for the scoring worker."""

from __future__ import annotations

import asyncio
import os
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from logline.testing import configured
from support.job_owner import an_owner
from tandem.testing import FakeWakeBus

from songmaker_cli.job_queue import ClaimedJob
from songmaker_cli.job_types import JobType
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.settings import get_settings

STOP_WITHIN_SECONDS = 5
SHUTDOWN_HOLD_SECONDS = 0.5


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _make_worker() -> ScoringWorker:
    worker = ScoringWorker()
    worker.owner = an_owner(worker.owner_id)
    worker.claim_job = MagicMock(return_value=True)
    worker.audio_dir = MagicMock(return_value="audio")
    worker.get_db_factory = MagicMock(return_value=MagicMock())
    return worker


def test_score_skips_a_job_it_cannot_claim() -> None:
    worker = _make_worker()
    worker.claim_job = MagicMock(return_value=False)

    with patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run:
        _run(worker.score(_mock_ctx(), "j1", "g1", None))

    mock_run.assert_not_called()


def test_score_runs_queued_job() -> None:
    worker = _make_worker()
    with patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run:
        _run(worker.score(_mock_ctx(), "j1", "g1", ["silence"]))

    mock_run.assert_called_once()


def test_score_passes_device_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("SCORING_DEVICE", "cuda")
    worker = _make_worker()
    with patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run:
        _run(worker.score(_mock_ctx(), "j1", "g1", None))

    assert mock_run.call_args.kwargs["device"] == "cuda"


def test_score_defaults_to_cpu() -> None:
    worker = _make_worker()
    with patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run:
        _run(worker.score(_mock_ctx(), "j1", "g1", None))

    assert mock_run.call_args.kwargs["device"] == "cpu"


def test_score_names_the_worker_as_the_owner() -> None:
    worker = _make_worker()
    with patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run:
        _run(worker.score(_mock_ctx(), "j1", "g1", None))

    assert mock_run.call_args.kwargs["owner"] is worker.owner


def test_on_startup_initializes_scorer() -> None:
    worker = ScoringWorker()
    worker.owner = an_owner(worker.owner_id)
    worker.get_db_factory = MagicMock()

    mock_scorer = MagicMock()
    ctx = _mock_ctx()

    with (
        configured("restored-after-the-test"),
        patch(
            "songmaker_cli.scoring.subprocess_runner.ScorerProcess",
            return_value=mock_scorer,
        ),
        patch("songmaker_cli.scoring.subprocess_runner.set_scorer_process") as mock_set,
    ):
        _run(worker.on_startup(ctx))

    mock_set.assert_called_once_with(mock_scorer)


def test_on_shutdown_stops_scorer() -> None:
    worker = ScoringWorker()
    worker.owner = an_owner(worker.owner_id)
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)

    mock_scorer = MagicMock()
    ctx = _mock_ctx()

    with (
        patch(
            "songmaker_cli.scoring.subprocess_runner.get_scorer_process",
            return_value=mock_scorer,
        ),
    ):
        _run(worker.on_shutdown(ctx))

    mock_scorer.shutdown.assert_called_once()


def test_on_shutdown_handles_missing_scorer() -> None:
    worker = ScoringWorker()
    worker.owner = an_owner(worker.owner_id)
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)

    ctx = _mock_ctx()

    with (
        patch(
            "songmaker_cli.scoring.subprocess_runner.get_scorer_process",
            side_effect=RuntimeError("not initialized"),
        ),
    ):
        _run(worker.on_shutdown(ctx))


def test_scoring_worker_settings_queue_name() -> None:
    from songmaker_cli.constants import ARQ_SCORING_QUEUE_NAME
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    assert ScoringWorkerSettings.queue_name == ARQ_SCORING_QUEUE_NAME


def test_scoring_worker_has_no_periodic_job_reaper() -> None:
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    assert ScoringWorkerSettings.cron_jobs == []


def test_scoring_worker_settings_functions() -> None:
    from songmaker_cli.job_types import JobFunction
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    func_names = {f.name for f in ScoringWorkerSettings.functions}
    assert JobFunction.SCORE in func_names
    assert JobFunction.GENERATE not in func_names


def test_scoring_worker_functions_registered_under_job_function_names() -> None:
    """Regression: arq must register ``score`` under the plain JobFunction
    name, not ``ScoringWorker.score``.
    """
    import asyncio as _asyncio

    from arq.worker import Worker

    from songmaker_cli.job_types import JobFunction
    from songmaker_cli.scoring_worker import ScoringWorkerSettings

    async def _build_and_inspect() -> set[str]:
        worker = Worker(
            functions=ScoringWorkerSettings.functions,
            queue_name=ScoringWorkerSettings.queue_name,
            redis_settings=ScoringWorkerSettings.redis_settings,
            handle_signals=False,
        )
        return set(worker.functions.keys())

    registered = _asyncio.run(_build_and_inspect())
    assert JobFunction.SCORE in registered


@pytest.fixture
def stop_signal_handlers():
    """Leave the process's handlers of the stop signals as the test found them."""
    stop_signals = (signal.SIGINT, signal.SIGTERM)
    before = {number: signal.getsignal(number) for number in stop_signals}
    yield
    for number, handler in before.items():
        signal.signal(number, handler)


def test_a_stop_signal_ends_the_claiming_though_the_loops_own_handler_still_gets_it(
    stop_signal_handlers,
) -> None:
    worker = ScoringWorker()
    worker.wake_channel = FakeWakeBus().pod()
    worker.claim_next_job = MagicMock(return_value=None)

    async def scenario() -> tuple[bool, bool]:
        loop = asyncio.get_running_loop()
        arq_was_told = asyncio.Event()
        loop.add_signal_handler(signal.SIGTERM, arq_was_told.set)
        queue_task = asyncio.create_task(worker.serve_queued_jobs())
        worker.stop_claiming_on_stop_signal(queue_task)
        os.kill(os.getpid(), signal.SIGTERM)
        async with asyncio.timeout(STOP_WITHIN_SECONDS):
            await arq_was_told.wait()
            await asyncio.wait([queue_task])
        loop.remove_signal_handler(signal.SIGTERM)
        return arq_was_told.is_set(), queue_task.cancelled()

    assert _run(scenario()) == (True, True)


def test_a_stop_signal_lets_a_running_job_finish_before_the_worker_shuts_down(
    stop_signal_handlers, scorer_requests, postgresql_url, redis_url,
) -> None:
    settings = get_settings().model_copy(
        update={"database_url": postgresql_url, "redis_url": redis_url},
    )
    worker = ScoringWorker(settings)
    worker.claim_next_job = MagicMock(side_effect=[ClaimedJob("j1", JobType.SCORE, None), None])
    job_started, job_may_finish, job_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def run_claimed(_claimed: ClaimedJob) -> None:
        job_started.set()
        await job_may_finish.wait()
        job_finished.set()

    worker.run_claimed = run_claimed

    async def scenario() -> tuple[bool, bool]:
        loop = asyncio.get_running_loop()
        arq_was_told = asyncio.Event()
        loop.add_signal_handler(signal.SIGTERM, arq_was_told.set)
        await worker.on_startup(_mock_ctx())
        async with asyncio.timeout(STOP_WITHIN_SECONDS):
            await job_started.wait()
            os.kill(os.getpid(), signal.SIGTERM)
            await arq_was_told.wait()
            shutting_down = asyncio.create_task(worker.on_shutdown({}))
            ended, _ = await asyncio.wait([shutting_down], timeout=SHUTDOWN_HOLD_SECONDS)
            ended_with_job_running = bool(ended)
            job_may_finish.set()
            await shutting_down
        loop.remove_signal_handler(signal.SIGTERM)
        return ended_with_job_running, job_finished.is_set()

    assert _run(scenario()) == (False, True)
