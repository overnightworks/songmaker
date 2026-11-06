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


def _driver_failure(message: str, pgcode: str | None = None) -> OperationalError:
    driver_error_type = type("DriverError", (psycopg2.OperationalError,), {"pgcode": pgcode})
    return OperationalError("connect", {}, driver_error_type(message))


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
        _driver_failure('connection to server at "db" failed: Connection refused'),
        _driver_failure('could not translate host name "db" to address: Name or service not known'),
        _driver_failure("FATAL:  the database system is starting up", pgcode="57P03"),
    ],
    ids=["refused", "name-not-resolved", "starting-up"],
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
        _driver_failure('FATAL:  password authentication failed for user "user"', pgcode="28P01"),
        _driver_failure('FATAL:  database "songs" does not exist'),
    ],
    ids=["authentication", "configuration"],
)
def test_database_authentication_or_configuration_error_raises_at_once(
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
