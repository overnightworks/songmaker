"""Shared fixtures and builders for API, database, and audio tests."""

from __future__ import annotations

import logging
import os

# Required env vars for Settings construction at module-import time. Real values from the
# environment win — these are only safe defaults so importing songmaker_cli.music_worker
# (which constructs Settings at class-definition time) does not fail in unit tests.
os.environ["SONGMAKER_SKIP_ENV_FILE"] = "1"
# No dialect has this name, so an engine built from settings fails at once instead of
# reaching SQLite or whatever database the shell names; database tests get an owned URL.
os.environ["DATABASE_URL"] = "unconfigured+no_database_in_tests://"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "x" * 64)
os.environ.setdefault("SONGMAKER_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("SONGMAKER_MONITORING_TOKEN", "test-monitoring-token")
os.environ.setdefault("WORKER_ID", "test-worker")
os.environ.setdefault("PUBLIC_BASE_URL", "https://songmaker.test")
os.environ.setdefault(
    "ALLOWED_HOSTS", "testserver,localhost,127.0.0.1,songmaker-web,songmaker.test")
os.environ.setdefault("OIDC_ISSUER", "https://issuer.test/realms/test")
os.environ.setdefault("OIDC_CLIENT_ID", "songmaker-test")

import struct  # noqa: E402
import wave  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from io import BytesIO  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import structlog  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from support.fake_cli_process import close_fake_cli_processes  # noqa: E402
from support.generation_failures import SONGMAKER_FAILURE_CASES  # noqa: E402
from support.oidc_client import write_test_client_secret  # noqa: E402
from support.web_app import make_fake_redis  # noqa: E402
from support.worker_http_peer import generation_worker_peer  # noqa: E402, F401

from songmaker_cli.scheduler import (  # noqa: E402
    WorkerGenerationUnavailable,
    WorkerGpuOutOfMemory,
)

pytest_plugins = [
    "support.redis_server",
    "support.oidc_world",
    "support.fake_acestep_child",
    "support.admin_client_fixture",
    "support.cover_album_world",
    "support.generation_job_world",
    "support.reference_link_migration",
    "support.database_case_record",
    "pytester",
]

os.environ.setdefault("OIDC_CLIENT_SECRET_FILE", write_test_client_secret())


@pytest.fixture(params=SONGMAKER_FAILURE_CASES)
def generation_failure_case(request):
    """S5-C/D, L6: Historical stored lines retain their read contract."""
    error_class, cause, historical, _, _ = request.param
    return error_class(cause), historical


@pytest.fixture(
    params=[
        *SONGMAKER_FAILURE_CASES,
        pytest.param(
            (WorkerGpuOutOfMemory, "need 18.5 GB", None,
             "Too long for the GPU right now — try a shorter duration.", "gpu_out_of_memory"),
            id="S8-A-oom",
        ),
        pytest.param(
            (
                WorkerGenerationUnavailable,
                "need 18.5 GB",
                None,
                "Generating isn't available right now.",
                "generation_unavailable",
            ),
            id="S5-A-B-L6-L10-load-http",
        ),
    ]
)
def generation_write_failure_case(request):
    """S8-A; S5-B, L6/L10: New writes select the line and type together."""
    error_class, cause, _, message, error_type = request.param
    return error_class(cause), message, error_type


@pytest.fixture
def isolated_logging():
    managed_loggers = (
        logging.getLogger(),
        logging.getLogger("alembic"),
        logging.getLogger("sqlalchemy.engine"),
    )
    logger_states = [
        (logger, logger.handlers[:], logger.level, logger.disabled, logger.propagate)
        for logger in managed_loggers
    ]
    structlog_state = structlog.get_config()
    yield
    for logger, handlers, level, disabled, propagate in logger_states:
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.disabled = disabled
        logger.propagate = propagate
    structlog.configure(**structlog_state)


@pytest.fixture(scope="module", autouse=True)
def _close_fake_cli_pipes():
    """Close the pipe-backed fake Claude CLI streams after each test module."""
    yield
    close_fake_cli_processes()


@pytest.fixture
def internal_token() -> str:
    """1301-F10-FIXTURE: configured credential expected at worker boundaries."""
    from songmaker_cli.settings import get_settings

    return get_settings().songmaker_internal_token.get_secret_value()


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the Settings lru_cache between tests so monkeypatched env wins."""
    from acestep_worker.settings import get_worker_settings
    from songmaker_cli.settings import get_settings

    get_settings.cache_clear()
    get_worker_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_worker_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_worker_singletons():
    yield
    from songmaker_cli import music_worker as mw_mod
    from songmaker_cli import scoring_worker as sw_mod

    for worker in (mw_mod._music_worker, sw_mod._scoring_worker):
        worker._db_factory = None
        worker._db_engine = None


@pytest.fixture
def mock_arq_pool():
    """Prevent lifespan from connecting to real Redis via arq."""
    from unittest.mock import AsyncMock

    import songmaker_cli.arq_pool as arq_mod

    saved = arq_mod._pool

    async def _fake_init():
        arq_mod._pool = AsyncMock(
            zcard=AsyncMock(return_value=0), keys=AsyncMock(return_value=[]),
            get=AsyncMock(return_value=None), exists=AsyncMock(return_value=0),
            aclose=AsyncMock(),
        )
        return arq_mod._pool

    async def _fake_close():
        arq_mod._pool = None

    with (
        patch("songmaker_cli.arq_pool.init_arq_pool", side_effect=_fake_init),
        patch("songmaker_cli.arq_pool.close_arq_pool", side_effect=_fake_close),
    ):
        yield
    arq_mod._pool = saved


@pytest.fixture
def monitoring_headers() -> dict[str, str]:
    """The request header Prometheus sends to ``/metrics``."""
    return {"Authorization": f"Bearer {os.environ['SONGMAKER_MONITORING_TOKEN']}"}


@pytest.fixture
def fresh_settings():
    """Let a test shape the environment before ``get_settings()`` first reads it."""
    from songmaker_cli.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_redis():
    """Provide a fresh fakeredis instance for tests that need Redis."""
    return make_fake_redis()


@pytest.fixture
def make_wav_bytes():
    """Factory fixture: build a minimal WAV byte buffer for testing."""

    def _make(
        audio_data: bytes,
        n_channels: int = 1,
        sampwidth: int = 2,
        sample_rate: int = 44100,
        audio_format: int = 1,
    ) -> bytes:
        fmt_chunk = struct.pack(
            "<HHIIHH",
            audio_format,
            n_channels,
            sample_rate,
            sample_rate * n_channels * sampwidth,
            n_channels * sampwidth,
            sampwidth * 8,
        )
        fmt_size = len(fmt_chunk)
        data_size = len(audio_data)
        riff_size = 4 + (8 + fmt_size) + (8 + data_size)

        buf = bytearray()
        buf += b"RIFF"
        buf += struct.pack("<I", riff_size)
        buf += b"WAVE"
        buf += b"fmt "
        buf += struct.pack("<I", fmt_size)
        buf += fmt_chunk
        buf += b"data"
        buf += struct.pack("<I", data_size)
        buf += audio_data
        return bytes(buf)

    return _make


@pytest.fixture
def make_stereo_wav_bytes():
    """Factory fixture: build stereo WAV bytes (int16) for testing."""

    def _make(sample_rate: int = 44100, duration: float = 0.1) -> bytes:
        n = int(sample_rate * duration)
        signal = np.zeros(n, dtype=np.int16)
        interleaved = np.empty(n * 2, dtype=np.int16)
        interleaved[0::2] = signal
        interleaved[1::2] = signal
        buf = BytesIO()
        with wave.open(buf, "w") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(interleaved.tobytes())
        return buf.getvalue()

    return _make


@pytest.fixture
def fake_queue_stream_build(monkeypatch: pytest.MonkeyPatch) -> None:
    import songmaker_cli.queue_streams as queue_streams

    def _write_stream(_concat_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"\xff\xfb\x90\x00" * 100)

    monkeypatch.setattr(queue_streams, "probe_audio_duration", lambda _path: 10.0)
    monkeypatch.setattr(queue_streams, "run_ffmpeg_concat", _write_stream)


@pytest.fixture
def session_deletion_failure():
    """defect:#1590: fail a session DELETE after it executes, before commit."""
    from songmaker_cli.db.models import UserSession

    @contextmanager
    def fail_deletion(factory, *, after=1, message="session deletion failed"):
        with factory() as db:
            engine = db.get_bind()
        deletions = 0

        def fail_after_delete(conn, cursor, statement, parameters, context, executemany):
            nonlocal deletions
            if (
                context.isdelete
                and context.compiled.statement.table.name == UserSession.__tablename__
            ):
                deletions += 1
                if deletions == after:
                    raise RuntimeError(message)

        event.listen(engine, "after_cursor_execute", fail_after_delete)
        try:
            yield
        finally:
            event.remove(engine, "after_cursor_execute", fail_after_delete)

    return fail_deletion


@pytest.fixture
def session_commit_failure():
    """defect:#1590: fail matching commits, optionally observing uncommitted state."""
    @contextmanager
    def fail_commit(target, *, message="commit failed", observe=None, when=None):
        def refuse_commit(session):
            if when is not None and not when(session):
                return
            if observe is not None:
                observe(session)
            raise RuntimeError(message)

        event.listen(target, "before_commit", refuse_commit)
        try:
            yield
        finally:
            event.remove(target, "before_commit", refuse_commit)

    return fail_commit


_DATABASE_SERVER_VARIABLE = "TEST_DATABASE_URL"


@pytest.fixture
def environment_with_database_server():
    """Builds a child process's environment with the database server setting replaced, or
    removed when given None, so a test can start a run without a usable server."""

    def with_server(environment: dict[str, str], server_url: str | None) -> dict[str, str]:
        child = dict(environment)
        child.pop(_DATABASE_SERVER_VARIABLE, None)
        if server_url is not None:
            child[_DATABASE_SERVER_VARIABLE] = server_url
        return child

    return with_server


@pytest.fixture(scope="session")
def postgresql_databases(testrun_uid: str, worker_id: str):
    """The owner of this run's and worker's databases; the only reader of `TEST_DATABASE_URL`.

    A missing, malformed or unreachable server fails every database test; none skips.
    """
    from support.postgresql import PostgresqlTestDatabases

    from songmaker_cli.db.database_url import database_url_with_password

    configured = os.environ.get(_DATABASE_SERVER_VARIABLE, "")
    if not configured:
        pytest.fail(
            "TEST_DATABASE_URL is not set: run database tests through "
            "scripts/test_postgresql.sh, which starts a disposable PostgreSQL."
        )
    administration_url = database_url_with_password(configured, None)
    if administration_url.get_backend_name() != "postgresql":
        pytest.fail("TEST_DATABASE_URL must name a PostgreSQL server")
    databases = PostgresqlTestDatabases(
        administration_url, run_id=testrun_uid, worker_id=worker_id,
    )
    yield databases
    databases.close()


@pytest.fixture
def postgresql_url(postgresql_databases):
    """This worker's migrated database; it is reset to its migrated baseline after the test."""
    yield postgresql_databases.worker_url
    postgresql_databases.reset()


@pytest.fixture
def empty_postgresql_url(postgresql_databases):
    """An additional empty database for a test that migrates it itself; dropped afterwards."""
    url = postgresql_databases.create_empty_database()
    yield url
    postgresql_databases.drop_database(url)


@pytest.fixture
def pg_factory(postgresql_url):
    """A session factory on this worker's migrated database, closed before its reset.

    A test that also takes ``fresh_settings`` lists ``pg_factory`` first, because
    ``pg_factory`` reads and caches the settings.
    """
    from sqlalchemy import create_engine

    from songmaker_cli.settings import get_settings

    settings = get_settings()
    engine = create_engine(
        postgresql_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )
    yield sessionmaker(bind=engine)
    engine.dispose()
