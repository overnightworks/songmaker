"""Recovery contracts for the lifecycle-owned Redis session reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_SECRET, make_fake_redis

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import User, UserSession
from songmaker_cli.lifecycle import _sync_sessions
from songmaker_cli.redis_client import SessionCache


class _FixedClock:
    now_value = datetime(2030, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz: timezone) -> datetime:
        assert tz is timezone.utc
        return cls.now_value


@pytest.fixture
def ctx(tmp_path):
    factory = init_test_db(tmp_path / "songmaker.db")
    return AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("songmaker_cli.lifecycle.datetime", _FixedClock)
    monkeypatch.setattr("songmaker_cli.db.queries.auth.datetime", _FixedClock)


def _store_cached_session(
    session_cache: SessionCache,
    session_id: str,
    user_id: str,
    expires_at: datetime,
    ttl: int,
) -> None:
    session_cache.store(
        session_id,
        user_id,
        user_id,
        "user",
        True,
        "127.0.0.1",
        "test-agent",
        expires_at,
        _FixedClock.now_value,
        ttl,
    )


def test_session_sync_updates_live_sessions_and_evicts_stale_cache_entries(
    ctx: AppContext,
    fixed_clock: None,
) -> None:
    now = _FixedClock.now_value
    with ctx.db() as session:
        session.add_all((
            User(id="active", username="active", password_hash="x"),
            User(id="inactive", username="inactive", password_hash="x", is_active=False),
            UserSession(id="live", user_id="active", expires_at=now + timedelta(days=1)),
            UserSession(
                id="inactive-session",
                user_id="inactive",
                expires_at=now + timedelta(days=1),
            ),
            UserSession(
                id="expired",
                user_id="active",
                expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            ),
        ))
        session.commit()

    session_cache = SessionCache(ctx.redis)
    _store_cached_session(session_cache, "live", "active", now + timedelta(days=1), 300)
    _store_cached_session(
        session_cache,
        "inactive-session",
        "inactive",
        now + timedelta(days=1),
        200,
    )
    _store_cached_session(session_cache, "missing", "active", now + timedelta(days=1), 100)

    synced = _sync_sessions(ctx, session_cache)

    assert synced == 1
    assert {session_id for session_id, _ in session_cache.get_all_sessions()} == {"live"}
    assert session_cache.get("missing") is None
    assert session_cache.get("inactive-session") is None
    with ctx.db() as session:
        live = session.get(UserSession, "live")
        assert live is not None
        assert now < live.expires_at.replace(tzinfo=timezone.utc) <= now + timedelta(seconds=300)
        assert session.get(UserSession, "inactive-session") is not None
        assert session.get(UserSession, "expired") is None


def test_session_sync_purges_database_expiry_when_redis_has_no_sessions(
    ctx: AppContext,
    fixed_clock: None,
) -> None:
    now = _FixedClock.now_value
    with ctx.db() as session:
        session.add(User(id="u1", username="u1", password_hash="x"))
        session.add(
            UserSession(
                id="expired",
                user_id="u1",
                expires_at=now - timedelta(seconds=1),
            ),
        )
        session.commit()

    session_cache = SessionCache(ctx.redis)

    assert _sync_sessions(ctx, session_cache) == 0
    with ctx.db() as session:
        assert session.get(UserSession, "expired") is None
