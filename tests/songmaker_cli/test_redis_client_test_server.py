"""The Redis test server helpers."""

import pytest
from support.redis_server import configured_redis_url, database_number


def test_redis_cases_without_a_server_fail_naming_the_variable():
    with pytest.raises(pytest.fail.Exception, match="TEST_REDIS_URL"):
        configured_redis_url({})


@pytest.mark.parametrize(
    ("worker_id", "number"),
    [("master", 0), ("gw0", 0), ("gw3", 3)],
    ids=["without-xdist", "first-worker", "fourth-worker"],
)
def test_each_worker_selects_its_own_redis_database(worker_id, number):
    assert database_number(worker_id, database_count=16) == number


def test_a_worker_beyond_the_servers_databases_fails_naming_both():
    with pytest.raises(pytest.fail.Exception, match=r"gw16.*16 databases"):
        database_number("gw16", database_count=16)
