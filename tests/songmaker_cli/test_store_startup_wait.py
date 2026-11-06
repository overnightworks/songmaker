"""Web and workers wait a bounded time for PostgreSQL and Redis at start."""

from __future__ import annotations

import logging

import psycopg2
import pytest
from redis.exceptions import AuthenticationError, ConnectionError, TimeoutError
from sqlalchemy.exc import OperationalError

from songmaker_cli.constants import STORE_STARTUP_WAIT_SECONDS
from songmaker_cli.db.engine import wait_for_database
from songmaker_cli.redis_client import build_arq_redis_settings, wait_for_redis

SECRET_URL = "postgresql://user:hunter2@db.example:5432/songs"


class FakeClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.sleeps = 0

    def now(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.seconds += seconds


def _driver_failure(message: str) -> OperationalError:
    return OperationalError("connect", {}, psycopg2.OperationalError(message))


def _server_fatal(text: str) -> OperationalError:
    prefix = 'connection to server at "db" (10.0.0.5), port 5432 failed'
    return _driver_failure(f"{prefix}: FATAL:  {text}")


class ScriptedProbe:
    """Raises the scripted errors in order, then answers."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def __call__(self, *_args: object) -> bool:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return True


class FakeRedis:
    def __init__(self, probe: ScriptedProbe) -> None:
        self.ping = probe


def _wait_database(probe: ScriptedProbe, clock: FakeClock, url: str = SECRET_URL) -> None:
    wait_for_database(url, probe=probe, now=clock.now, sleep=clock.sleep)


def _wait_redis(probe: ScriptedProbe, clock: FakeClock) -> None:
    wait_for_redis(FakeRedis(probe), "redis.example:6379", now=clock.now, sleep=clock.sleep)


@pytest.mark.parametrize(
    "failure",
    [
        _driver_failure('connection to server at "127.0.0.1", port 1 failed: Connection refused'),
        _driver_failure(
            'could not translate host name "no-such-host.invalid" to address: '
            "Name or service not known",
        ),
        _driver_failure('connection to server at "db", port 5432 failed: timeout expired'),
        _driver_failure("server closed the connection unexpectedly"),
        _server_fatal("the database system is starting up"),
        _server_fatal("the database system is shutting down"),
        _server_fatal("the database system is in recovery mode"),
    ],
    ids=[
        "refused", "name-not-resolved", "timeout", "closed-unexpectedly",
        "starting-up", "shutting-down", "recovery-mode",
    ],
)
def test_database_that_answers_after_failures_is_waited_for(failure: OperationalError) -> None:
    probe = ScriptedProbe(failure, failure)
    clock = FakeClock()

    _wait_database(probe, clock)

    assert probe.calls == 3
    assert clock.sleeps == 2


def test_database_that_never_answers_raises_after_the_bound() -> None:
    probe = ScriptedProbe(*[_driver_failure("Connection refused")] * 10_000)
    clock = FakeClock()

    with pytest.raises(OperationalError):
        _wait_database(probe, clock)

    assert STORE_STARTUP_WAIT_SECONDS <= clock.seconds < STORE_STARTUP_WAIT_SECONDS + 10


@pytest.mark.parametrize(
    "failure",
    [
        _server_fatal('password authentication failed for user "user"'),
        _server_fatal('database "songs" does not exist'),
        _server_fatal('no pg_hba.conf entry for host "10.0.0.9", user "user", database "songs"'),
    ],
    ids=["password", "unknown-database", "pg-hba"],
)
def test_database_server_rejection_raises_at_once(
    failure: OperationalError,
) -> None:
    probe = ScriptedProbe(failure)
    clock = FakeClock()

    with pytest.raises(OperationalError):
        _wait_database(probe, clock)

    assert probe.calls == 1
    assert clock.sleeps == 0


def test_database_wait_logs_one_line_at_start_and_one_on_answer_without_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    probe = ScriptedProbe(*[_driver_failure("Connection refused")] * 5)

    with caplog.at_level(logging.INFO):
        _wait_database(probe, FakeClock())

    assert len(caplog.records) == 2
    assert "hunter2" not in caplog.text


@pytest.mark.parametrize("failure", [ConnectionError("refused"), TimeoutError("slow")])
def test_redis_that_answers_after_failures_is_waited_for(failure: Exception) -> None:
    probe = ScriptedProbe(failure, failure)
    clock = FakeClock()

    _wait_redis(probe, clock)

    assert probe.calls == 3
    assert clock.sleeps == 2


def test_redis_that_never_answers_raises_after_the_bound() -> None:
    probe = ScriptedProbe(*[ConnectionError("refused")] * 10_000)
    clock = FakeClock()

    with pytest.raises(RuntimeError, match="redis.example:6379"):
        _wait_redis(probe, clock)

    assert STORE_STARTUP_WAIT_SECONDS <= clock.seconds < STORE_STARTUP_WAIT_SECONDS + 10


def test_redis_authentication_error_raises_at_once() -> None:
    probe = ScriptedProbe(AuthenticationError("bad password"))
    clock = FakeClock()

    with pytest.raises(AuthenticationError):
        _wait_redis(probe, clock)

    assert probe.calls == 1
    assert clock.sleeps == 0


def test_redis_wait_logs_one_line_at_start_and_one_on_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    probe = ScriptedProbe(*[ConnectionError("refused")] * 5)

    with caplog.at_level(logging.INFO):
        _wait_redis(probe, FakeClock())

    assert len(caplog.records) == 2


def test_arq_connect_retry_window_covers_the_startup_bound() -> None:
    settings = build_arq_redis_settings("redis://redis:6379/0")

    assert isinstance(settings.conn_retry_delay, int)
    assert settings.conn_retries * settings.conn_retry_delay >= STORE_STARTUP_WAIT_SECONDS
