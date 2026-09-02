"""Shared test fixtures for WAV generation and song markdown creation."""

from __future__ import annotations

import os

# Required env vars for Settings construction at module-import time.
# Real values from the environment win — these are only safe defaults
# so importing songmaker_cli.music_worker (which constructs Settings at
# class-definition time) does not fail in unit tests.
os.environ["SONGMAKER_SKIP_ENV_FILE"] = "1"
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSION_SECRET", "x" * 64)
os.environ.setdefault("SONGMAKER_INTERNAL_TOKEN", "test-internal-token")
os.environ.setdefault("WORKER_ID", "test-worker")
os.environ.setdefault("PUBLIC_BASE_URL", "https://songmaker.test")

import struct  # noqa: E402
import wave  # noqa: E402
from collections.abc import Callable  # noqa: E402
from http.client import HTTPResponse  # noqa: E402
from io import BytesIO  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import fakeredis  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TEST_SECRET = b"a" * 64


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
            "songmaker_cli.claude.provider.verify_cli_tool_surface", AsyncMock(),
        ),
        patch(
            "songmaker_cli.claude.provider.averify_no_builtin_cli_tools", AsyncMock(),
        ),
        patch(
            "songmaker_cli.claude.provider.verify_no_builtin_cli_tools", MagicMock(),
        ),
    ):
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
def fake_redis():
    """Provide a fresh fakeredis instance for tests that need Redis."""
    return fakeredis.FakeRedis(decode_responses=True)


def make_fake_redis():
    """Non-fixture factory for test helpers that build AppContext directly."""
    return fakeredis.FakeRedis(decode_responses=True)


def apply_csrf_header(client) -> None:
    """Extract the csrf_token cookie and set it as a default X-CSRF-Token header.

    Call after login/setup to enable CSRF-protected mutating requests in tests.
    """
    token = client.cookies.get("csrf_token")
    if token:
        client.headers["X-CSRF-Token"] = token


def login_and_csrf(client, username: str, password: str) -> None:
    """Login and configure CSRF header for subsequent requests."""
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
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


@pytest.fixture
def make_sine_wav_bytes():
    """Factory fixture: build stereo WAV bytes containing a sine wave."""

    def _make(
        frequency: float = 440.0,
        duration: float = 2.0,
        sample_rate: int = 44100,
    ) -> bytes:
        n = int(sample_rate * duration)
        t = np.arange(n, dtype=np.float64)
        signal = 0.3 * np.sin(2.0 * np.pi * frequency * t / sample_rate)
        int16 = np.clip(signal * 32768.0, -32768.0, 32767.0).astype(np.int16)

        interleaved = np.empty(n * 2, dtype=np.int16)
        interleaved[0::2] = int16
        interleaved[1::2] = int16

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


def make_test_app(
    tmp_path: Path,
    seed_db: Callable | None = None,
) -> tuple:
    """Create a full test app with real middleware.

    Returns (TestClient, sessionmaker) so callers can seed data or log in.
    The optional ``seed_db`` callback receives a SQLAlchemy Session and can
    add models before the app starts.
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
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    factory = init_db(data_dir / "songmaker.db")
    if seed_db is not None:
        with factory() as session:
            seed_db(session)
            session.commit()

    redis = make_fake_redis()
    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=data_dir,
        session_secret=TEST_SECRET, redis=redis,
    )
    app = create_app(audio_dir, data_dir, project_root, ctx=ctx)
    client = TestClient(app, cookies={})
    return client, factory


@pytest.fixture
def make_song_md():
    """Factory fixture: create a song markdown file in a lyrics directory."""

    def _make(lyrics_dir: Path, stem: str = "01_test_song") -> Path:
        md = lyrics_dir / f"{stem}.md"
        md.write_text(
            "---\ntitle: Test\nprompt: rock\nlanguage: en\n---\n\n## Lyrics\n\n"
            "[verse]\nHello world\nSecond line\n",
        )
        return md

    return _make
