"""Tests for the scoring worker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.scoring_worker as sw_mod


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _mock_db_factory():
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    return mock_factory, mock_session


def test_score_skips_completed_job() -> None:
    with (
        patch("songmaker_cli.scoring_worker.check_job_still_valid", return_value=False),
        patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run,
    ):
        _run(sw_mod.score(_mock_ctx(), "j1", "g1", None))

    mock_run.assert_not_called()


def test_score_runs_queued_job() -> None:
    with (
        patch("songmaker_cli.scoring_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run,
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=MagicMock()),
        patch("songmaker_cli.scoring_worker._audio_dir", return_value="audio"),
    ):
        _run(sw_mod.score(_mock_ctx(), "j1", "g1", ["silence"]))

    mock_run.assert_called_once()


def test_score_passes_device_from_env() -> None:
    with (
        patch("songmaker_cli.scoring_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run,
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=MagicMock()),
        patch("songmaker_cli.scoring_worker._audio_dir", return_value="audio"),
        patch.dict("os.environ", {"SCORING_DEVICE": "cuda"}),
    ):
        _run(sw_mod.score(_mock_ctx(), "j1", "g1", None))

    assert mock_run.call_args.kwargs["device"] == "cuda"


def test_score_defaults_to_cpu() -> None:
    with (
        patch("songmaker_cli.scoring_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.scoring_worker.run_scoring_job") as mock_run,
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=MagicMock()),
        patch("songmaker_cli.scoring_worker._audio_dir", return_value="audio"),
        patch.dict("os.environ", {}, clear=True),
    ):
        _run(sw_mod.score(_mock_ctx(), "j1", "g1", None))

    assert mock_run.call_args.kwargs["device"] == "cpu"


def test_cleanup_stale_commits_on_recovery() -> None:
    mock_factory, mock_session = _mock_db_factory()

    with (
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
            return_value=3,
        ),
    ):
        _run(sw_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_called_once()


def test_cleanup_stale_no_commit_when_zero() -> None:
    mock_factory, mock_session = _mock_db_factory()

    with (
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
            return_value=0,
        ),
    ):
        _run(sw_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_not_called()


def test_on_startup_initializes_scorer() -> None:
    mock_factory, mock_session = _mock_db_factory()
    mock_scorer = MagicMock()
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.db.queries.recover_stale_jobs_by_type"),
        patch("songmaker_cli.scoring_worker.common_startup", new_callable=AsyncMock),
        patch(
            "songmaker_cli.scoring.subprocess_runner.ScorerProcess",
            return_value=mock_scorer,
        ),
        patch("songmaker_cli.scoring.subprocess_runner.set_scorer_process") as mock_set,
    ):
        _run(sw_mod.on_startup(ctx))

    mock_set.assert_called_once_with(mock_scorer)


def test_on_startup_recovers_stale_score_jobs() -> None:
    mock_factory, mock_session = _mock_db_factory()
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.scoring_worker._get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_type",
        ) as mock_recover,
        patch("songmaker_cli.scoring_worker.common_startup", new_callable=AsyncMock),
        patch(
            "songmaker_cli.scoring.subprocess_runner.ScorerProcess",
            return_value=MagicMock(),
        ),
        patch("songmaker_cli.scoring.subprocess_runner.set_scorer_process"),
    ):
        _run(sw_mod.on_startup(ctx))

    mock_recover.assert_called_once_with(mock_session, "score")
    mock_session.commit.assert_called_once()


def test_on_shutdown_stops_scorer() -> None:
    mock_scorer = MagicMock()
    ctx = _mock_ctx()

    with (
        patch(
            "songmaker_cli.scoring.subprocess_runner.get_scorer_process",
            return_value=mock_scorer,
        ),
        patch("songmaker_cli.scoring_worker.common_shutdown", new_callable=AsyncMock),
    ):
        _run(sw_mod.on_shutdown(ctx))

    mock_scorer.shutdown.assert_called_once()


def test_on_shutdown_handles_missing_scorer() -> None:
    ctx = _mock_ctx()

    with (
        patch(
            "songmaker_cli.scoring.subprocess_runner.get_scorer_process",
            side_effect=RuntimeError("not initialized"),
        ),
        patch("songmaker_cli.scoring_worker.common_shutdown", new_callable=AsyncMock),
    ):
        _run(sw_mod.on_shutdown(ctx))


def test_scoring_worker_settings_queue_name() -> None:
    from songmaker_cli.constants import ARQ_SCORING_QUEUE_NAME
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    assert ScoringWorkerSettings.queue_name == ARQ_SCORING_QUEUE_NAME


def test_scoring_worker_settings_has_cron() -> None:
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    assert len(ScoringWorkerSettings.cron_jobs) == 1


def test_scoring_worker_settings_functions() -> None:
    from songmaker_cli.scoring_worker import ScoringWorkerSettings
    func_names = [f.__name__ for f in ScoringWorkerSettings.functions]
    assert "score" in func_names
    assert "generate" not in func_names
