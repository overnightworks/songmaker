"""Web and workers wait a bounded time for PostgreSQL and Redis at start."""

from __future__ import annotations

import logging

import psycopg
import pytest
from redis.exceptions import AuthenticationError, ConnectionError, TimeoutError
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError

from songmaker_cli.constants import STORE_STARTUP_WAIT_SECONDS
from songmaker_cli.db.engine import wait_for_database
from songmaker_cli.redis_client import wait_for_redis

SECRET_URL = "postgresql://user:hunter2@db.example:5432/songs"


class FakeClock:
    def __init__(self, sleep_advance: float | None = None) -> None:
        self.seconds = 0.0
        self.sleeps = 0
        self._sleep_advance = sleep_advance

    def now(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.seconds += seconds if self._sleep_advance is None else self._sleep_advance


def _driver_failure(message: str) -> OperationalError:
    return OperationalError("connect", {}, psycopg.OperationalError(message))


def _server_fatal(text: str) -> OperationalError:
    prefix = 'connection failed: connection to server at "10.0.0.5", port 5432 failed'
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
        _driver_failure(
            'connection failed: connection to server at "127.0.0.1", port 1 failed: '
            "Connection refused",
        ),
        _driver_failure(
            "failed to resolve host 'no-such-host.invalid': [Errno -2] Name or service not known",
        ),
        _driver_failure("connection timeout expired"),
        _driver_failure(
            "Multiple connection attempts failed. All failures were:\n"
            "- host: 'db-a', port: '5432': Connection refused\n"
            "- host: 'db-b', port: '5432': Connection refused",
        ),
        _driver_failure("server closed the connection unexpectedly"),
        _server_fatal("the database system is starting up"),
        _server_fatal("the database system is shutting down"),
        _server_fatal("the database system is in recovery mode"),
        _server_fatal("the database system is not yet accepting connections"),
    ],
    ids=[
        "refused", "name-not-resolved", "timeout", "multiple-attempts", "closed-unexpectedly",
        "starting-up", "shutting-down", "recovery-mode", "not-yet-accepting",
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


@pytest.fixture
def real_database_failures(postgresql_databases, refused_port) -> dict[str, URL]:
    """Addresses that make the real psycopg 3 connect fail, keyed by what is wrong."""
    served = postgresql_databases.administration_url
    return {
        "refused-port": served.set(host="127.0.0.1", port=refused_port),
        "unresolvable-host": served.set(host="no-such-host.invalid"),
        "wrong-password": served.set(password="not-the-password"),
        "unknown-database": served.set(database="no_such_database"),
    }


@pytest.mark.parametrize("failure", ["refused-port", "unresolvable-host"])
def test_real_connect_to_an_unreachable_database_is_retried_until_the_bound(
    real_database_failures: dict[str, URL], failure: str,
) -> None:
    clock = FakeClock(sleep_advance=STORE_STARTUP_WAIT_SECONDS / 3)

    with pytest.raises(OperationalError):
        wait_for_database(
            real_database_failures[failure], now=clock.now, sleep=clock.sleep,
        )

    assert clock.sleeps == 3


@pytest.mark.parametrize("failure", ["wrong-password", "unknown-database"])
def test_real_connect_the_server_rejects_raises_at_once(
    real_database_failures: dict[str, URL], failure: str,
) -> None:
    clock = FakeClock()

    with pytest.raises(OperationalError):
        wait_for_database(
            real_database_failures[failure], now=clock.now, sleep=clock.sleep,
        )

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

