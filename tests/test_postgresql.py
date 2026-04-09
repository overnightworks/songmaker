"""PostgreSQL-specific tests.

Tests requiring a live PostgreSQL instance are skipped unless
TEST_DATABASE_URL is set to a PostgreSQL URL.

Run with: TEST_DATABASE_URL=postgresql://user:pass@localhost/test pytest tests/test_postgresql.py
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from songmaker_cli.db.engine import (
    init_test_db,
    resolve_database_url,
)
from songmaker_cli.db.models import Base, Job, User
from songmaker_cli.db.queries import create_job, job_duration_stats
from songmaker_cli.settings import get_settings

TEST_PG_URL = os.environ.get("TEST_DATABASE_URL", "")
SKIP_NO_PG = pytest.mark.skipif(
    not TEST_PG_URL.startswith("postgresql"),
    reason="TEST_DATABASE_URL not set to a PostgreSQL URL",
)


def _pg_session_factory() -> sessionmaker[Session]:
    settings = get_settings()
    engine = create_engine(
        TEST_PG_URL,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture()
def sqlite_factory(tmp_path: Path) -> sessionmaker[Session]:
    return init_test_db(tmp_path / "test.db")


@pytest.fixture()
def pg_factory():
    if not TEST_PG_URL.startswith("postgresql"):
        pytest.skip("No PostgreSQL URL")
    factory = _pg_session_factory()
    yield factory
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    engine.dispose()


# ── resolve_database_url ──────────────────────────────────────────


def test_resolve_database_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    url = resolve_database_url()
    assert url == "postgresql://user:pass@host/db"


# ── PostgreSQL-specific tests ─────────────────────────────────────


@SKIP_NO_PG
def test_duration_stats_postgresql_values(pg_factory) -> None:
    now = datetime.now(timezone.utc)
    with pg_factory() as session:
        j1 = Job(type="generate", status="completed")
        j1.started_at = now - timedelta(seconds=10)
        j1.completed_at = now
        j2 = Job(type="generate", status="completed")
        j2.started_at = now - timedelta(seconds=30)
        j2.completed_at = now
        session.add_all([j1, j2])
        session.commit()

    with pg_factory() as session:
        stats = job_duration_stats(session)
    assert stats["min"] == pytest.approx(10.0, abs=1.0)
    assert stats["max"] == pytest.approx(30.0, abs=1.0)
    assert stats["avg"] == pytest.approx(20.0, abs=1.0)


@SKIP_NO_PG
def test_concurrent_job_creation(pg_factory) -> None:
    with pg_factory() as session:
        session.add(User(id="u1", username="testuser", password_hash="x", role="user"))
        session.commit()

    errors: list[Exception] = []
    results: list[str] = []

    def _create_job(thread_id: int) -> None:
        try:
            with pg_factory() as session:
                job = create_job(session, "generate", user_id="u1")
                session.commit()
                results.append(job.id)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_create_job, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors during concurrent job creation: {errors}"
    assert len(results) == 10
    assert len(set(results)) == 10


@SKIP_NO_PG
def test_alembic_migrations_on_postgresql() -> None:
    from alembic import command
    from alembic.config import Config

    engine = create_engine(TEST_PG_URL)
    Base.metadata.drop_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        conn.commit()
    engine.dispose()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_PG_URL)
    command.upgrade(cfg, "head")

    engine = create_engine(TEST_PG_URL)
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    expected = {"users", "albums", "songs", "versions", "generations", "scores",
                "ratings", "jobs", "user_sessions", "login_attempts", "audit_log",
                "generation_presets", "alembic_version"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"
