"""Shared fixtures and builders for API, database, and audio tests."""

from __future__ import annotations

import asyncio
import logging
import os

# Required env vars for Settings construction at module-import time. Real values from the
# environment win — these are only safe defaults so importing songmaker_cli.music_worker
# (which constructs Settings at class-definition time) does not fail in unit tests.
os.environ["SONGMAKER_SKIP_ENV_FILE"] = "1"
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "x" * 64)
os.environ.setdefault("SONGMAKER_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("WORKER_ID", "test-worker")
os.environ.setdefault("PUBLIC_BASE_URL", "https://songmaker.test")
os.environ.setdefault(
    "ALLOWED_HOSTS", "testserver,localhost,127.0.0.1,songmaker-web,songmaker.test")
os.environ.setdefault("OIDC_ISSUER", "https://issuer.test/realms/test")
os.environ.setdefault("OIDC_CLIENT_ID", "songmaker-test")

import functools  # noqa: E402
import shutil  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import wave  # noqa: E402
from collections.abc import Callable, Mapping, Sequence  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from http.client import HTTPResponse  # noqa: E402
from io import BytesIO  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Final  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import fakeredis  # noqa: E402
import httpx  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import structlog  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from webauth.cookies import DEFAULT_CSRF_COOKIE_NAME  # noqa: E402
from webauth.ports import AuthenticatedUser  # noqa: E402
from worker_http_peer import generation_worker_peer  # noqa: E402, F401

from acestep_engine.errors import AudioDownloadError  # noqa: E402
from songmaker_cli.app_context import AppContext  # noqa: E402
from songmaker_cli.scheduler import (  # noqa: E402
    NoCapacityError,
    WorkerGenerationUnavailable,
    WorkerGpuOutOfMemory,
)

pytest_plugins = ["redis_server", "oidc_world"]

TEST_CLIENT_SECRET = "test-client-secret"


def _write_test_client_secret() -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".secret", delete=False) as secret_file:
        secret_file.write(TEST_CLIENT_SECRET)
    return secret_file.name


os.environ.setdefault("OIDC_CLIENT_SECRET_FILE", _write_test_client_secret())

TEST_SECRET = b"a" * 64
TEST_ORIGIN: Final = "https://testserver"
REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
COMPOSE_CONFIG_TIMEOUT_SECONDS: Final = 60


GENERATION_SETUP_MESSAGES = [
    "Song not found",
    "Version not found",
    "Reference audio not found",
    "Selected voice is unavailable for this generation",
]

OTHER_GENERATION_ERROR_TYPES = [
    None,
    "server_restart",
    "no_worker_alive",
    "queued_full_queue_bound",
    "queued_too_long",
    "setup_error",
    "unknown",
]


SONGMAKER_FAILURE_CASES = [
    pytest.param(
        (
            TimeoutError, "private timeout",
            "Generation timed out", "Generation timed out", "generation_error",
        ),
        id="S5-B-D-timeout",
    ),
    pytest.param(
        (
            AudioDownloadError, "private download",
            "Failed to download generated audio", "Failed to download generated audio",
            "generation_error",
        ),
        id="S5-B-D-download",
    ),
    pytest.param(
        (
            ConnectionError, "private connection",
            "ACE-Step server not reachable", "ACE-Step server not reachable", "generation_error",
        ),
        id="S5-B-D-connection",
    ),
    pytest.param(
        (
            NoCapacityError, "private capacity",
            "No ACE-Step workers available", "Generating isn't available right now.",
            "generation_unavailable",
        ),
        id="S5-B-L10-capacity",
    ),
    pytest.param(
        (
            RuntimeError, "private runtime",
            "Internal error during processing", "Internal error during processing",
            "generation_error",
        ),
        id="S5-B-D-runtime",
    ),
    pytest.param(
        (
            ValueError, "private unknown",
            "An unexpected error occurred", "An unexpected error occurred", "generation_error",
        ),
        id="S5-B-D-unknown",
    ),
]


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


def queries_without_session_auth(statements: Sequence[str]) -> list[str]:
    """defect:#1590: route budgets exclude DB session lookup and touch SQL.

    Session authentication owns this per-request cost independently of the
    route's row count; all other statements remain in the route budget.
    """
    session_prefixes = ("select user_sessions.", "update user_sessions set ")
    removed, kept = [], []
    for statement in statements:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith(session_prefixes):
            removed.append(normalized)
        else:
            kept.append(statement)
    expected = ("select user_sessions.", "update user_sessions set expires_at")
    assert len(removed) == 2 and all(
        sum(statement.startswith(prefix) for statement in removed) == 1 for prefix in expected
    ), f"Expected exactly one {expected[0]!r} and one {expected[1]!r}; removed: {removed!r}"
    return kept


def web_client(app, **kwargs) -> TestClient:
    """Build a TestClient that reaches a songmaker web app over its real HTTPS origin.

    A request naming neither `Origin` nor `Sec-Fetch-Site` carries what a same-origin
    browser sends; one naming either goes out as written."""
    client = TestClient(app, base_url=TEST_ORIGIN, **kwargs)
    client.event_hooks = {"request": [_add_same_origin_fetch_metadata]}
    return client


def _add_same_origin_fetch_metadata(request: httpx.Request) -> None:
    if "origin" not in request.headers and "sec-fetch-site" not in request.headers:
        request.headers["Sec-Fetch-Site"] = "same-origin"


_fake_cli_processes: list[MagicMock] = []


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
    for proc in _fake_cli_processes:
        for stream_name in (
            "stdin", "stdout", "stderr", "_stdin_reader", "_stdout_writer", "_stderr_writer",
        ):
            stream = getattr(proc, stream_name)
            if not stream.closed:
                stream.close()
    _fake_cli_processes.clear()


def fake_cli_process(
    first_line: bytes | None, *, still_running: bool = False, stdin_blocked: bool = False,
) -> MagicMock:
    """Build a pipe-backed stand-in for the ``subprocess.Popen`` CLI handle."""
    proc = MagicMock()
    proc.pid = 4343
    proc.poll.return_value = None if still_running else 0
    stdin_reader, stdin_writer = os.pipe()
    stdout_reader, stdout_writer = os.pipe()
    stderr_reader, stderr_writer = os.pipe()
    proc.stdin = os.fdopen(stdin_writer, "wb", buffering=0)
    proc.stdout = os.fdopen(stdout_reader, "rb", buffering=0)
    proc.stderr = os.fdopen(stderr_reader, "rb", buffering=0)
    proc._stdin_reader = os.fdopen(stdin_reader, "rb", buffering=0)
    proc._stdout_writer = os.fdopen(stdout_writer, "wb", buffering=0)
    proc._stderr_writer = os.fdopen(stderr_writer, "wb", buffering=0)
    proc._stderr_writer.close()
    if stdin_blocked:
        os.set_blocking(proc.stdin.fileno(), False)
        try:
            while True:
                os.write(proc.stdin.fileno(), b"x" * 65536)
        except BlockingIOError:
            pass
    if first_line is not None:
        proc._stdout_writer.write(first_line)
        proc._stdout_writer.close()
    proc.wait.return_value = None
    _fake_cli_processes.append(proc)
    return proc


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
def _configure_agent_provider_runtime():
    """Give every test the provider runtime songmaker installs at startup.

    ``agent_providers`` refuses to run unconfigured, and production installs
    its configuration exactly once — in ``server.create_app`` and in
    ``WorkerBase.on_startup``. Tests reach provider code directly, so each one
    starts from a configuration built the same way and drops it afterwards.
    """
    from agent_providers.config import reset_config

    from songmaker_cli.agent_runtime import configure_agent_providers
    from songmaker_cli.settings import Settings

    configure_agent_providers(Settings())
    yield
    reset_config()


def override_provider_runtime(**deployment_facts) -> None:
    """Replace named provider deployment facts for the current test only.

    Test doubles for a mounted binary, credential mirror, or resource
    directory belong here rather than in a patched module constant: the
    provider layer reads them from the injected configuration, which the
    autouse fixture above rebuilds for every test.

    Deliberately replaces the installation rather than adding to it, because
    ``configure()`` refuses a differing second value. A test that overrides
    before building its app therefore fails loudly when ``create_app``
    installs songmaker's own facts over it, instead of silently losing them.
    """
    from agent_providers.config import (
        ProviderRuntimeConfig,
        configure,
        current_config,
        reset_config,
    )

    replacement = ProviderRuntimeConfig(
        **{**current_config().model_dump(), **deployment_facts},
    )
    reset_config()
    configure(replacement)


def use_codex_process_pool(monkeypatch, process_pool) -> None:
    """Give every Codex module that admits a process the same test pool.

    Admission is asked for in three places — the tool transport, the image
    route, and the shared runner that binds and reaps a reservation — so a
    test that sizes the pool has to reach all three or it silently measures
    the process-wide one.
    """
    from agent_providers.codex import image, protocol, transport

    for module in (image, protocol, transport):
        monkeypatch.setattr(module, "get_codex_process_pool", lambda: process_pool)


@pytest.fixture(autouse=True)
def _isolate_codex_process_pool():
    """Keep each test independent of Codex CLI process reservations."""
    import agent_providers.codex.pool as pool_mod

    pool_mod._process_pool = None
    yield
    pool_mod._process_pool = None


@pytest.fixture(autouse=True)
def _no_claude_cli_tool_surface_probe():
    """Never let a test spawn the real Claude CLI to read its tool surface.

    Server startup, every co-writer turn, the legacy per-song chat endpoint,
    and the lyrical-coherence judge each ask the mounted binary which tools
    it offers before running it (#351); on a developer machine that binary
    exists, so without this a lifespan, co-writer, chat, or scoring test
    would start a real CLI session. Each probe's own behaviour is pinned in
    ``test_claude_provider.py``.
    """
    from unittest.mock import AsyncMock

    with (
        patch(
            "agent_providers.claude.provider.verify_cli_tool_surface", AsyncMock(),
        ),
        patch(
            "agent_providers.claude.provider.averify_no_builtin_cli_tools", AsyncMock(),
        ),
        patch(
            "agent_providers.claude.provider.verify_no_builtin_cli_tools", MagicMock(),
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _no_codex_cover_sandbox_runtime_probe():
    """Keep ordinary app-lifecycle tests independent of the host sandbox.

    The cover path itself verifies its fail-closed sandbox requirement. Tests
    that enter the web lifespan only need the boot contract, so they must not
    depend on bubblewrap or user namespaces being available in their runner.
    """
    with patch(
        "songmaker_cli.server.report_codex_image_sandbox_runtime",
        return_value="ready",
    ):
        yield


@pytest.fixture(autouse=True)
def _no_provider_status_probe():
    """Keep TestClient lifespans from probing installed provider CLIs or APIs.

    The provider-status loop refreshes immediately at application startup. A
    developer machine can have all three CLIs installed, which would otherwise
    make ordinary TestClient tests start login probes (and, with credentials,
    reach provider model catalogs). The lifecycle-loop tests opt back into the
    real loop where they provide its dependencies explicitly.
    """
    async def _idle_provider_status_loop(app) -> None:
        from songmaker_cli.lifecycle import BackgroundLoopName, background_loop_registry

        background_loop_registry(app).record_success(BackgroundLoopName.PROVIDER_STATUS_REFRESH)
        await asyncio.Future()

    with patch("songmaker_cli.server.provider_status_refresh_loop", _idle_provider_status_loop):
        yield


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
        arq_mod._pool = AsyncMock()
        arq_mod._pool.zcard = AsyncMock(return_value=0)
        arq_mod._pool.keys = AsyncMock(return_value=[])
        arq_mod._pool.get = AsyncMock(return_value=None)
        arq_mod._pool.aclose = AsyncMock()
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
def fresh_settings():
    """Let a test shape the environment before ``get_settings()`` first reads it."""
    from songmaker_cli.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_redis():
    """Provide a fresh fakeredis instance for tests that need Redis."""
    return fakeredis.FakeRedis(decode_responses=True)


def make_fake_redis():
    """Non-fixture factory for test helpers that build AppContext directly."""
    return fakeredis.FakeRedis(decode_responses=True)


def install_app_context(app, ctx) -> None:
    """Give a bare test app what ``create_app`` installs on the real one.

    An app that serves any auth-protected or rate-limited route needs both the
    context and the ``WebAuthConfig`` built from it, or it fails loudly on the
    first request. The settings are read uncached, so a test that shapes its
    environment after building its app still gets its own values back from
    ``get_settings()``.
    """
    from webauth.config import install_web_auth_config

    from songmaker_cli.app_context import build_web_auth_config
    from songmaker_cli.settings import Settings

    app.state.ctx = ctx
    install_web_auth_config(app, build_web_auth_config(ctx, Settings()))


def apply_csrf_header(client) -> None:
    """Extract the csrf_token cookie and set it as a default X-CSRF-Token header.

    Call after login/setup to enable CSRF-protected mutating requests in tests.
    """
    token = client.cookies.get(DEFAULT_CSRF_COOKIE_NAME)
    if token:
        client.headers["X-CSRF-Token"] = token


def issued_cookies(session_id: str, config) -> dict[str, str]:
    """The session and CSRF cookies the library issues for ``session_id``, by name."""
    from fastapi import Response
    from webauth.cookies import issue_session_cookies

    carrier = Response()
    issue_session_cookies(carrier, session_id, config)
    return {
        name: rest.partition(";")[0]
        for name, _, rest in (h.partition("=") for h in carrier.headers.getlist("set-cookie"))
    }


def login_and_csrf(client, username: str) -> None:
    """Open a session for the seeded ``username`` and configure the CSRF header.

    Writes the session row straight to the database and issues the cookies the
    callback would, because signing in itself needs the issuer.
    """
    from datetime import datetime, timedelta, timezone

    from webauth.config import installed_web_auth_config

    from songmaker_cli.auth_stores import DatabaseSessionRecordStore
    from songmaker_cli.db.models import User

    config = installed_web_auth_config(client.app)
    now = datetime.now(timezone.utc)
    with client.app.state.ctx.db() as session:
        user_id = session.query(User).filter_by(username=username).one().id
        idle = timedelta(seconds=config.session_lifetime.idle_seconds)
        record = DatabaseSessionRecordStore(session).create(
            user_id, now=now, expires_at=now + idle, refresh_token=None,
        )
        session.commit()
        session_id = record.id
    for name, value in issued_cookies(session_id, config).items():
        client.cookies.set(name, value)
    apply_csrf_header(client)


def mock_http_response(data: bytes, status: int = 200) -> MagicMock:
    """Build a mock urllib HTTPResponse for ACE-Step client tests.

    Supports both full reads (``resp.read()``) and chunked reads
    (``resp.read(n)``) so the same mock works with the deadline-based
    chunked download in ``_download_audio``.
    """
    resp = MagicMock(spec=HTTPResponse)
    resp.status = status
    buf = BytesIO(data)

    def _read(size: int = -1) -> bytes:
        return buf.read(size) if size != -1 else buf.read()

    resp.read = _read
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


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


def write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """Write a float32/float64 numpy array to a 16-bit WAV file (stdlib only)."""
    int16 = np.clip(audio * 32768.0, -32768.0, 32767.0).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int16.tobytes())


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """Read a WAV file into a float32 numpy array + sample rate (stdlib only)."""
    with wave.open(str(path), "r") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        int16 = np.frombuffer(frames, dtype=np.int16)
        return int16.astype(np.float32) / 32768.0, sr


def seed_judge_route(session) -> None:
    """Settings-only TestClients skip the startup pin and retain the old API route."""
    from songmaker_cli.constants import SETTING_JUDGE_ROUTE
    from songmaker_cli.db.queries.settings import set_claude_model

    set_claude_model(session, SETTING_JUDGE_ROUTE, "api")


def make_authenticated_user(
    user_id: str,
    *,
    role: str = "user",
    username: str | None = None,
) -> AuthenticatedUser:
    """Build a user, using the ID as the default username."""
    return AuthenticatedUser(
        id=user_id,
        username=user_id if username is None else username,
        role=role,
    )


def make_router_ctx(
    tmp_path: Path,
    *,
    db: sessionmaker[Session] | None = None,
    seed_db: Callable[[Session], None] | None = None,
) -> AppContext:
    """Build a router context, preserving an existing DB and committing seed data."""
    from songmaker_cli.db.engine import init_test_db

    ctx = AppContext(
        db=db if db is not None else init_test_db(tmp_path / "test.db"),
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        signing_key=TEST_SECRET,
        redis=make_fake_redis(),
    )
    if seed_db is not None:
        with ctx.db() as session:
            seed_db(session)
            session.commit()
    return ctx


def make_router_app(ctx: AppContext, *, user: AuthenticatedUser | None = None) -> FastAPI:
    """Mount the API router on an existing context, without middleware or lifecycle.

    Without a user override, requests exercise real authentication.
    """
    from songmaker_cli.api import router
    from songmaker_cli.audio_paths import AudioPathRejectedError
    from songmaker_cli.auth_dependencies import get_current_user
    from songmaker_cli.server import audio_path_rejected_handler

    app = FastAPI()
    app.add_exception_handler(AudioPathRejectedError, audio_path_rejected_handler)
    install_app_context(app, ctx)
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    app.include_router(router)
    return app


def seed_user(
    session: Session, username: str, role: str = "user", *, user_id: str | None = None,
):
    """Add an account the way admission would: its id is the issuer's subject."""
    import uuid

    from songmaker_cli.db.queries.auth import create_user

    return create_user(session, user_id or str(uuid.uuid4()), username, role)


def make_test_app(
    tmp_path: Path,
    seed_db: Callable | None = None,
    index_html: str = "<html>Songmaker</html>",
    factory: sessionmaker[Session] | None = None,
) -> tuple:
    """Create a full test app with real middleware on ``factory`` or a fresh SQLite file.

    Returns (TestClient, sessionmaker) so callers can seed data or log in.
    ``seed_db`` receives a Session to add models before the app starts;
    ``index_html`` is the built page whose inline scripts the policy hashes.
    """
    from songmaker_cli.app_context import AppContext
    from songmaker_cli.db.engine import init_test_db as init_db
    from songmaker_cli.server import create_app

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True, exist_ok=True)
    (sk_dir / "index.html").write_text(index_html)

    factory = factory or init_db(data_dir / "songmaker.db")
    with factory() as session:
        seed_judge_route(session)
        if seed_db is not None:
            seed_db(session)
        session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        signing_key=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = web_client(app, cookies={})
    return client, factory


def refresh_provider_snapshots() -> None:
    """Refresh every provider after a test changes its catalog dependencies."""
    from agent_providers.constants import COWRITER_PROVIDERS

    from songmaker_cli.provider_status import refresh_provider_snapshot

    for provider in COWRITER_PROVIDERS:
        refresh_provider_snapshot(provider)


@pytest.fixture
def every_provider_is_configured(monkeypatch):
    override_provider_runtime(
        anthropic_api_key="test-key",
        xai_api_key="test-key",
        openai_api_key="test-key",
    )
    monkeypatch.setattr(
        "agent_providers.catalog._cli_is_logged_in",
        lambda _provider: True,
    )
    monkeypatch.setattr(
        "agent_providers.catalog._anthropic_sdk_available",
        lambda: True,
    )
    refresh_provider_snapshots()


@functools.cache
def _require_docker_compose() -> None:
    if shutil.which("docker") is None:
        pytest.fail("docker is not on PATH; this test drives the real `docker compose config`")
    version = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        timeout=COMPOSE_CONFIG_TIMEOUT_SECONDS,
        check=False,
    )
    if version.returncode != 0:
        pytest.fail(f"`docker compose` is unavailable: {version.stderr.strip()}")


def run_compose_config(
    compose_args: Sequence[str],
    config_args: Sequence[str],
    *,
    env_file: Path,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run the real ``docker compose config`` from the repository root.

    ``--env-file`` replaces the project's ``.env`` and the process environment is
    cleared down to PATH and HOME plus ``environment``, so neither the operator's
    file nor the test session's own environment reaches the rendering. ``config``
    needs only the Docker CLI's compose plugin, not a daemon.
    """
    _require_docker_compose()
    return subprocess.run(
        ["docker", "compose", "--env-file", str(env_file), *compose_args, "config", *config_args],
        cwd=REPOSITORY_ROOT,
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **environment},
        capture_output=True,
        text=True,
        timeout=COMPOSE_CONFIG_TIMEOUT_SECONDS,
        check=False,
    )


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


def _pg_session_factory() -> sessionmaker[Session]:
    from sqlalchemy import create_engine

    from songmaker_cli.db.models import Base
    from songmaker_cli.settings import get_settings

    settings = get_settings()
    engine = create_engine(
        os.environ["TEST_DATABASE_URL"],
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


@pytest.fixture
def pg_factory():
    from songmaker_cli.db.models import Base

    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        pytest.skip("No PostgreSQL URL")
    factory = _pg_session_factory()
    yield factory
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    engine.dispose()
