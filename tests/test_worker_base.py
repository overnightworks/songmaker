"""Tests for worker_base shared infrastructure."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.worker_base as wb_mod


def _run(coro):
    return asyncio.run(coro)


def test_check_job_still_valid_returns_false_for_completed() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "completed"

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker_base.get_job", return_value=mock_job),
    ):
        assert wb_mod.check_job_still_valid("j1") is False


def test_check_job_still_valid_returns_false_for_missing() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker_base.get_job", return_value=None),
    ):
        assert wb_mod.check_job_still_valid("j1") is False


def test_check_job_still_valid_returns_true_for_queued() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "queued"

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker_base.get_job", return_value=mock_job),
    ):
        assert wb_mod.check_job_still_valid("j1") is True


def test_check_job_still_valid_returns_false_for_cancelled() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "cancelled"

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker_base.get_job", return_value=mock_job),
    ):
        assert wb_mod.check_job_still_valid("j1") is False


def test_get_db_factory_caches() -> None:
    wb_mod._db_factory = None
    wb_mod._db_engine = None

    mock_engine = MagicMock()
    mock_factory = MagicMock()
    mock_factory.kw = {"bind": mock_engine}

    with (
        patch("songmaker_cli.worker_base.init_db", return_value=mock_factory) as mock_init,
        patch("songmaker_cli.worker_base.resolve_database_url", return_value="sqlite:///:memory:"),
    ):
        result1 = wb_mod._get_db_factory()
        result2 = wb_mod._get_db_factory()

    assert result1 is result2
    mock_init.assert_called_once()

    wb_mod._db_factory = None
    wb_mod._db_engine = None


def test_common_startup_warns_on_redis_url_mismatch() -> None:
    mock_log = MagicMock()

    with (
        patch.dict("os.environ", {"REDIS_URL": "redis://prod:6379/0"}),
        patch.object(wb_mod, "log", mock_log),
    ):
        _run(wb_mod.common_startup({}, "redis://localhost:6379/0"))

    warning_calls = [
        c for c in mock_log.warning.call_args_list if "redis://prod:6379/0" in str(c)
    ]
    assert len(warning_calls) == 1


def test_common_startup_no_warning_when_urls_match() -> None:
    mock_log = MagicMock()

    with (
        patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"}),
        patch.object(wb_mod, "log", mock_log),
    ):
        _run(wb_mod.common_startup({}, "redis://localhost:6379/0"))

    warning_calls = [
        c for c in mock_log.warning.call_args_list if "REDIS_URL" in str(c)
    ]
    assert len(warning_calls) == 0


def test_common_shutdown_recovers_jobs() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    redis = AsyncMock()

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value=2,
        ) as mock_recover,
    ):
        _run(wb_mod.common_shutdown("test:lock", "generate", redis))

    mock_recover.assert_called_once_with(mock_session, "generate")
    mock_session.commit.assert_called_once()


def test_common_shutdown_skips_when_lock_held() -> None:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=False)

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type",
    ) as mock_recover:
        _run(wb_mod.common_shutdown("test:lock", "generate", redis))

    mock_recover.assert_not_called()


def test_recover_on_startup_acquires_lock_and_recovers() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    ctx = {"redis": AsyncMock()}

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value=3,
        ) as mock_recover,
    ):
        result = _run(wb_mod.recover_on_startup(ctx, "test:lock", "generate"))

    assert result == 3
    mock_recover.assert_called_once_with(mock_session, "generate")
    mock_session.commit.assert_called_once()
    ctx["redis"].delete.assert_called_once_with("test:lock")


def test_recover_on_startup_skips_when_lock_held() -> None:
    ctx = {"redis": AsyncMock()}
    ctx["redis"].set = AsyncMock(return_value=False)

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type",
    ) as mock_recover:
        result = _run(wb_mod.recover_on_startup(ctx, "test:lock", "score"))

    assert result == 0
    mock_recover.assert_not_called()


def test_recover_on_startup_releases_lock_on_error() -> None:
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(
        side_effect=RuntimeError("db error"),
    )
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    ctx = {"redis": AsyncMock()}

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.db.queries.recover_stale_jobs_by_type"),
    ):
        try:
            _run(wb_mod.recover_on_startup(ctx, "test:lock", "generate"))
        except RuntimeError:
            pass

    ctx["redis"].delete.assert_called_once_with("test:lock")


def test_make_cleanup_cron_commits_on_recovery() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    cleanup = wb_mod.make_cleanup_cron("generate")

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
            return_value=2,
        ) as mock_recover,
    ):
        result = _run(cleanup({"redis": AsyncMock()}))

    assert result == 2
    mock_recover.assert_called_once_with(mock_session, "generate")
    mock_session.commit.assert_called_once()


def test_make_cleanup_cron_no_commit_when_zero() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    cleanup = wb_mod.make_cleanup_cron("score")

    with (
        patch.object(wb_mod, "_get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
            return_value=0,
        ),
    ):
        result = _run(cleanup({"redis": AsyncMock()}))

    assert result == 0
    mock_session.commit.assert_not_called()


def test_build_redis_settings() -> None:
    settings = wb_mod.build_redis_settings()
    assert settings is not None
