"""A shared Redis server for wire-protocol integration tests, one database per xdist worker.

The server is the one `TEST_REDIS_URL` names: a service container in CI, the throwaway
container of `scripts/test_postgresql.sh` locally. A worker selects the database numbered
like its worker and flushes it before each case, so no case sees another's keys.
"""

import os
import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

import pytest
from redis import Redis

REDIS_SERVER_VARIABLE = "TEST_REDIS_URL"
WITHOUT_XDIST = "master"
XDIST_WORKER = re.compile(r"gw(\d+)")
CONNECT_TIMEOUT_SECONDS = 5


def configured_redis_url(environment: Mapping[str, str]) -> str:
    """The server URL the run is given; a run without one fails every Redis case."""
    url = environment.get(REDIS_SERVER_VARIABLE, "")
    if not url:
        pytest.fail(
            f"{REDIS_SERVER_VARIABLE} is not set: run Redis tests through "
            "scripts/test_postgresql.sh, which starts a disposable Redis.",
            pytrace=False,
        )
    return url


def database_number(worker_id: str, *, database_count: int) -> int:
    """The Redis database of an xdist worker; the run without xdist takes the first."""
    number = 0 if worker_id == WITHOUT_XDIST else int(XDIST_WORKER.fullmatch(worker_id)[1])
    if number >= database_count:
        pytest.fail(
            f"worker {worker_id} has no Redis database: the server at "
            f"{REDIS_SERVER_VARIABLE} has {database_count} databases; run fewer workers.",
            pytrace=False,
        )
    return number


@pytest.fixture(scope="session")
def redis_database_url(worker_id: str) -> str:
    """The URL of this worker's database on the configured server."""
    server_url = configured_redis_url(os.environ)
    with Redis.from_url(server_url, socket_connect_timeout=CONNECT_TIMEOUT_SECONDS) as server:
        database_count = int(server.config_get("databases")["databases"])
    number = database_number(worker_id, database_count=database_count)
    return urlunsplit(urlsplit(server_url)._replace(path=f"/{number}"))


@pytest.fixture
def redis_url(redis_database_url: str) -> str:
    """The worker's database URL, empty at the start of the case."""
    with Redis.from_url(redis_database_url) as database:
        database.flushdb()
    return redis_database_url
