"""Fixtures for tests that run several web processes against one database and one Redis."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.app_processes import web_processes
from support.redis_proxy import redis_proxy


@pytest.fixture
def case_factory(extra_pg_factory):
    """A session factory on a database of the case's own, which the per-test reset leaves alone."""
    return extra_pg_factory()


@pytest.fixture
def database_url(case_factory) -> str:
    return case_factory.kw["bind"].url.render_as_string(hide_password=False)


@pytest.fixture
def web_cluster(tmp_path: Path, case_factory, database_url: str, redis_url: str):
    """The processes of one case, on a database and a Redis of its own; none is started yet."""
    with web_processes(tmp_path, database_url=database_url, redis_url=redis_url) as cluster:
        yield cluster, case_factory


@pytest.fixture
def two_processes(web_cluster):
    """A and B, running against one database and one Redis."""
    cluster, factory = web_cluster
    return cluster, factory, cluster.start("a"), cluster.start("b")


@pytest.fixture
def proxied_cluster(tmp_path: Path, case_factory, database_url: str, redis_url: str):
    """The processes of one case reach Redis through a proxy that cuts the line on demand."""
    with redis_proxy(redis_url) as proxy:
        with web_processes(tmp_path, database_url=database_url, redis_url=proxy.url) as cluster:
            yield cluster, case_factory, proxy
