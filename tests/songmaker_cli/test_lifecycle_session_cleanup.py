"""defect:#1590: database expiry owns periodic session cleanup."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from support.web_app import TEST_SECRET

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import BACKGROUND_LOOP_FAILURE_THRESHOLD
from songmaker_cli.db.models import User, UserSession
from songmaker_cli.health_types import (
    BackgroundLoopName,
    BackgroundLoopRegistry,
    BackgroundLoopStatus,
)
from songmaker_cli.lifecycle import _cleanup_sessions, session_cleanup_loop


@pytest.fixture
def cleanup_context(tmp_path, pg_factory):
    return AppContext(
        db=pg_factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=None,
    )


@pytest.fixture
def seed_cleanup_sessions(cleanup_context):
    def seed(*, expired_ids=("expired",), live_expiry=None):
        with cleanup_context.db() as db:
            db.add(User(id="user", username="user"))
            db.add_all(
                UserSession(
                    id=session_id, user_id="user",
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                )
                for session_id in expired_ids
            )
            if live_expiry is not None:
                db.add(UserSession(id="live", user_id="user", expires_at=live_expiry))
            db.commit()

    return seed


@pytest.mark.parametrize("expired_count", [0, 1, 3])
def test_cleanup_commits_expiry_without_redis_or_changing_live_sessions(
    cleanup_context, expired_count, seed_cleanup_sessions,
):
    """defect:#1590: purge only DB-expired sessions, durably and idempotently."""
    now = datetime.now(timezone.utc)
    live_expiry = now + timedelta(days=1)
    seed_cleanup_sessions(
        expired_ids=[f"expired-{i}" for i in range(expired_count)], live_expiry=live_expiry,
    )

    assert _cleanup_sessions(cleanup_context) == expired_count
    assert _cleanup_sessions(cleanup_context) == 0

    with cleanup_context.db() as db:
        remaining = db.query(UserSession).all()
        assert [session.id for session in remaining] == ["live"]
        assert remaining[0].expires_at.replace(tzinfo=timezone.utc) == live_expiry


def test_failed_cleanup_commit_preserves_expired_sessions(
    cleanup_context, seed_cleanup_sessions, session_commit_failure,
):
    """defect:#1590: a commit failure surfaces and rolls the deletion back."""
    seed_cleanup_sessions()
    factory = cleanup_context.db
    with session_commit_failure(factory, message="commit unavailable"), pytest.raises(
        RuntimeError, match="commit unavailable",
    ):
        _cleanup_sessions(cleanup_context)

    with factory() as db:
        assert db.get(UserSession, "expired") is not None


def test_cleanup_loop_runs_without_redis_and_recovers_after_database_failure(
    cleanup_context, seed_cleanup_sessions,
):
    """defect:#1590: failed ticks remain observable and the next tick retries."""
    app = FastAPI()
    app.state.ctx = cleanup_context
    registry = BackgroundLoopRegistry()
    app.state.background_loop_registry = registry
    factory = cleanup_context.db
    seed_cleanup_sessions()

    def unavailable_database():
        raise RuntimeError("database unavailable")

    cleanup_context.db = unavailable_database
    ticks = 0

    async def advance_tick(_seconds):
        nonlocal ticks
        ticks += 1
        health = registry.loop_health()[BackgroundLoopName.SESSION_CLEANUP]
        if ticks == 2:
            assert health.consecutive_failures == 1
            assert health.last_error == "RuntimeError"
            cleanup_context.db = factory
        elif ticks == 3:
            assert health.consecutive_failures == 0
            assert health.last_error is None
            raise asyncio.CancelledError

    cleanup_loop = session_cleanup_loop(app, wait=advance_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(cleanup_loop)

    with factory() as db:
        assert db.get(UserSession, "expired") is None


def test_cleanup_loop_keeps_a_live_session_and_resets_a_failing_loop_when_nothing_expired(
    cleanup_context, seed_cleanup_sessions,
):
    app = FastAPI()
    app.state.ctx = cleanup_context
    registry = BackgroundLoopRegistry()
    app.state.background_loop_registry = registry
    for _ in range(BACKGROUND_LOOP_FAILURE_THRESHOLD):
        registry.record_failure(BackgroundLoopName.SESSION_CLEANUP, RuntimeError("earlier"))
    seed_cleanup_sessions(
        expired_ids=(), live_expiry=datetime.now(timezone.utc) + timedelta(days=1),
    )
    ticks = 0

    async def advance_tick(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(session_cleanup_loop(app, wait=advance_tick))

    health = registry.loop_health()[BackgroundLoopName.SESSION_CLEANUP]
    assert health.status is BackgroundLoopStatus.OK
    with cleanup_context.db() as db:
        assert db.get(UserSession, "live") is not None
