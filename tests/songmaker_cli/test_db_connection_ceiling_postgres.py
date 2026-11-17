"""A pooled engine honours the configured pool and overflow against a real PostgreSQL."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from songmaker_cli.db.engine import connect_db


def _backend_pid_of_new_session(factory) -> int:
    with factory() as session:
        return session.execute(text("SELECT pg_backend_pid()")).scalar_one()


@pytest.mark.parametrize(("pool_size", "max_overflow"), [(2, 1), (1, 3)])
def test_a_process_never_holds_more_server_connections_than_pool_plus_overflow(
    postgresql_url, fresh_settings, monkeypatch, pool_size, max_overflow,
) -> None:
    monkeypatch.setenv("DATABASE_POOL_SIZE", str(pool_size))
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", str(max_overflow))
    factory = connect_db(postgresql_url)
    ceiling = pool_size + max_overflow
    held = [factory() for _ in range(ceiling)]
    try:
        held_backends = {s.execute(text("SELECT pg_backend_pid()")).scalar_one() for s in held}
        assert len(held_backends) == ceiling

        with ThreadPoolExecutor(max_workers=1) as executor:
            beyond_ceiling = executor.submit(_backend_pid_of_new_session, factory)
            held.pop().close()
            assert beyond_ceiling.result(timeout=10) in held_backends
    finally:
        for session in held:
            session.close()
        factory.kw["bind"].dispose()
