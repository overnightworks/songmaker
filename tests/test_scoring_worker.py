"""Tests for the scoring worker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.scoring_worker as sw_mod
from songmaker_cli.scoring_worker import ScoringWorker


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _make_worker() -> ScoringWorker:
    worker = ScoringWorker()
    worker.check_job_still_valid = MagicMock(return_value=True)
    worker.audio_dir = MagicMock(return_value="audio")
    worker.get_db_factory = MagicMock(return_value=MagicMock())
    return worker


def test_score_skips_completed_job() -> None:
    worker = _make_worker()
    worker.check_job_still_valid = MagicMock(return_value=False)

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


def test_on_startup_initializes_scorer() -> None:
    worker = ScoringWorker()
    worker._recover_on_startup = AsyncMock(return_value=0)

    mock_scorer = MagicMock()
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.logging_config.configure_logging"),
        patch(
            "songmaker_cli.scoring.subprocess_runner.ScorerProcess",
            return_value=mock_scorer,
        ),
        patch("songmaker_cli.scoring.subprocess_runner.set_scorer_process") as mock_set,
    ):
        _run(worker.on_startup(ctx))

    mock_set.assert_called_once_with(mock_scorer)
    worker._recover_on_startup.assert_called_once_with(ctx)


def test_on_shutdown_stops_scorer() -> None:
    worker = ScoringWorker()
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
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value={},
        ),
    ):
        _run(worker.on_shutdown(ctx))

    mock_scorer.shutdown.assert_called_once()


def test_on_shutdown_handles_missing_scorer() -> None:
    worker = ScoringWorker()
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
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value={},
        ),
    ):
        _run(worker.on_shutdown(ctx))


def test_scoring_worker_settings_queue_name() -> None:
    from songmaker_cli.constants import ARQ_SCORING_QUEUE_NAME
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    assert ScoringWorkerSettings.queue_name == ARQ_SCORING_QUEUE_NAME


def test_scoring_worker_settings_has_cron() -> None:
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    assert len(ScoringWorkerSettings.cron_jobs) == 1


def test_scoring_worker_settings_functions() -> None:
    from songmaker_cli.constants import JobFunction
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    func_names = {f.name for f in ScoringWorkerSettings.functions}
    assert JobFunction.SCORE in func_names
    assert JobFunction.GENERATE not in func_names


def test_scoring_worker_settings_uses_singleton_methods() -> None:
    """The arq Settings shim must expose bound methods of _scoring_worker."""
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    for func in ScoringWorkerSettings.functions:
        assert func.coroutine.__self__ is sw_mod._scoring_worker


def test_scoring_worker_functions_registered_under_job_function_names() -> None:
    """Regression: arq must register ``score`` under the plain JobFunction
    name, not ``ScoringWorker.score``.
    """
    import asyncio as _asyncio

    from arq.worker import Worker

    from songmaker_cli.constants import JobFunction
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
