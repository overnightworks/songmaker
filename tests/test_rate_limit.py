"""Tests for rate limiting on generate/score endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.auth import TrustedProxies, hash_password
from songmaker_cli.db.models import Album, AvailableModel, Generation, Job, Song, Version
from songmaker_cli.db.queries import create_user
from songmaker_cli.middleware.rate_limit import RateLimitClass, _classify_path

_PROXY_NETWORK = "172.16.0.0/12"
_TRUSTED_PEER = "172.18.0.1"


def _trust_proxy_network(client: TestClient) -> None:
    client.app.state.ctx.trusted_proxies = TrustedProxies.parse(_PROXY_NETWORK)


def _seed_rate_limit_data(session) -> None:
    session.add(Album(id="rock", title="Rock", artist="Band"))
    session.add(Song(id="s1", title="Song", album_id="rock", track_number=1))
    session.add(Version(
        id="v1", song_id="s1", version_number=1, lyrics="hello", prompt="rock",
    ))
    session.add(Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="rock/song_v1.mp3",
    ))
    session.flush()
    session.query(AvailableModel).filter(
        AvailableModel.id == "sft",
    ).update({"is_active": True}, synchronize_session=False)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_rate_limit_data)
    yield client


def _login_as(client: TestClient, role: str) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        user = create_user(session, f"test_{role}", hash_password("t3stP@ssw0rd"), role=role)
        album = session.query(Album).filter_by(id="rock").first()
        if album and not album.created_by:
            album.created_by = user.id
        session.commit()
    from conftest import login_and_csrf
    login_and_csrf(client, f"test_{role}", "t3stP@ssw0rd")


def _get_user_id(client: TestClient) -> str:
    return client.get("/api/auth/me").json()["id"]


@contextmanager
def _mock_arq():
    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=AsyncMock()),
        patch("songmaker_cli.generation_api.is_music_worker_healthy", AsyncMock(return_value=True)),
        patch(
            "songmaker_cli.generation_api.is_scoring_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api._has_online_acestep_worker",
            AsyncMock(return_value=True),
        ),
    ):
        yield


# ── Generation rate limit ───────────────────────────────────────────


def test_generate_rate_limit_for_user(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        for i in range(3):
            session.add(Job(type="generate", user_id=user_id, status="completed"))
        session.commit()

    resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 429
    assert "Rate limit" in resp.json()["detail"]


def test_generate_no_rate_limit_for_admin(client: TestClient) -> None:
    _login_as(client, "admin")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        for i in range(10):
            session.add(Job(type="generate", user_id=user_id, status="completed"))
        session.commit()

    with _mock_arq():
        resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 200


# ── Scoring rate limit ──────────────────────────────────────────────


def test_score_rate_limit_for_user(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        for i in range(10):
            session.add(Job(type="score", user_id=user_id, status="completed"))
        session.commit()

    resp = client.post("/api/generations/g1/score", json={})

    assert resp.status_code == 429


# ── Active job limit ────────────────────────────────────────────────


def test_active_job_limit(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("MAX_USER_ACTIVE_JOBS", "1")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    _login_as(client, "user")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Job(type="generate", user_id=user_id, status="running"))
        session.commit()

    resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 429
    assert "active job" in resp.json()["detail"]


def test_stale_own_job_does_not_block_generate_at_active_job_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from songmaker_cli.constants import STALE_JOB_THRESHOLDS, JobType

    monkeypatch.setenv("MAX_USER_ACTIVE_JOBS", "1")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    _login_as(client, "user")
    user_id = _get_user_id(client)
    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=STALE_JOB_THRESHOLDS[JobType.GENERATE].heartbeat_seconds + 1,
    )

    factory = client.app.state.ctx.db
    with factory() as session:
        other_user = create_user(session, "other_user", hash_password("t3stP@ssw0rd"))
        own_job = Job(
            type="generate", user_id=user_id, status="running",
            started_at=stale_at, heartbeat_at=stale_at,
        )
        other_job = Job(
            type="generate", user_id=other_user.id, status="running",
            started_at=stale_at, heartbeat_at=stale_at,
        )
        session.add_all((own_job, other_job))
        session.commit()
        own_job_id, other_job_id = own_job.id, other_job.id

    with _mock_arq():
        resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 200
    with factory() as session:
        own_job = session.query(Job).filter_by(id=own_job_id).one()
        other_job = session.query(Job).filter_by(id=other_job_id).one()
        assert own_job.status == "failed"
        assert own_job.error_type == "heartbeat_lost"
        assert other_job.status == "running"


def test_score_job_does_not_block_generate(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Job(type="score", user_id=user_id, status="running"))
        session.commit()

    with _mock_arq():
        resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 200


def test_generate_job_does_not_block_score(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Job(type="generate", user_id=user_id, status="running"))
        session.commit()

    with _mock_arq():
        resp = client.post("/api/generations/g1/score", json={})

    assert resp.status_code == 200


# ── Queue depth limit ───────────────────────────────────────────────


def test_queue_depth_limit(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("MAX_QUEUE_DEPTH", "10")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    _login_as(client, "user")

    factory = client.app.state.ctx.db
    with factory() as session:
        for _ in range(10):
            session.add(Job(type="generate", status="queued"))
        session.commit()

    resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 429
    assert "Queue is full" in resp.json()["detail"]


# ── Per-IP exemptions ───────────────────────────────────────────────


@pytest.fixture
def ip_limited_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("IP_RATE_LIMIT", "2")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    client, _ = make_test_app(tmp_path, seed_db=_seed_rate_limit_data)
    build_dir = tmp_path / "frontend" / "build"
    (build_dir / "favicon.svg").write_text("<svg></svg>")
    (build_dir / "service-worker.js").write_text("// sw")
    (build_dir / "manifest.webmanifest").write_text("{}")
    (build_dir / "icon-192.png").write_bytes(b"\x89PNG\r\n")
    (build_dir / "icon-512.png").write_bytes(b"\x89PNG\r\n")
    yield client
    get_settings.cache_clear()


def test_ip_rate_limit_blocks_api_after_budget(ip_limited_client: TestClient) -> None:
    for _ in range(2):
        ip_limited_client.get("/api/auth/check")

    resp = ip_limited_client.get("/api/auth/check")

    assert resp.status_code == 429


@pytest.mark.parametrize("path", [
    "/manifest.webmanifest",
    "/robots.txt",
    "/favicon.svg",
    "/service-worker.js",
    "/icon-192.png",
    "/icon-512.png",
])
def test_exempt_static_paths_bypass_ip_rate_limit(ip_limited_client: TestClient, path: str) -> None:
    for _ in range(5):
        resp = ip_limited_client.get(path)

    assert resp.status_code != 429


def test_health_endpoint_is_not_exempt_from_ip_rate_limit(
    ip_limited_client: TestClient, mock_arq_pool,
) -> None:
    """/health is the priciest anonymous endpoint (DB + ~5 Redis round trips)
    and must share the same budget as every other request -- an anonymous
    caller must not be able to hammer it for free (see rate_limit.py)."""
    with (
        ip_limited_client,
        patch("songmaker_cli.arq_pool.is_music_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.is_scoring_worker_healthy", AsyncMock(return_value=False)),
        patch("songmaker_cli.arq_pool.get_music_queue_depth", AsyncMock(return_value=0)),
        patch("songmaker_cli.arq_pool.get_scoring_queue_depth", AsyncMock(return_value=0)),
    ):
        for _ in range(2):
            ip_limited_client.get("/health")
        resp = ip_limited_client.get("/health")

    assert resp.status_code == 429


def test_exempt_paths_do_not_consume_api_budget(ip_limited_client: TestClient) -> None:
    for _ in range(10):
        ip_limited_client.get("/favicon.svg")

    resp = ip_limited_client.get("/api/auth/check")

    assert resp.status_code != 429


# ── Per-IP budget keys behind a proxy ───────────────────────────────


def _check_from(client: TestClient, forwarded_for: str) -> int:
    peer_client = TestClient(client.app, client=(_TRUSTED_PEER, 55000))
    resp = peer_client.get("/api/auth/check", headers={"x-forwarded-for": forwarded_for})
    return resp.status_code


def test_ip_budget_is_per_forwarded_client_not_per_proxy(
    ip_limited_client: TestClient,
) -> None:
    """Behind a proxy every visitor arrives from one gateway address. The
    budget must follow the visitor, or the first one locks out all the rest."""
    _trust_proxy_network(ip_limited_client)

    for _ in range(2):
        _check_from(ip_limited_client, "203.0.113.1")

    assert _check_from(ip_limited_client, "203.0.113.1") == 429
    assert _check_from(ip_limited_client, "203.0.113.2") != 429


def test_a_malformed_chain_shares_the_peer_budget(ip_limited_client: TestClient) -> None:
    """Rotating nonsense through X-Forwarded-For must not mint fresh budgets:
    every malformed chain keys on the peer the request really came from."""
    _trust_proxy_network(ip_limited_client)

    _check_from(ip_limited_client, "garbage")
    _check_from(ip_limited_client, "   ")

    assert _check_from(ip_limited_client, "203.0.113.1, ") == 429


def test_ipv4_mapped_and_plain_forms_share_one_budget(
    ip_limited_client: TestClient,
) -> None:
    """Same client, one budget — a notation switch must not double it."""
    _trust_proxy_network(ip_limited_client)

    _check_from(ip_limited_client, "203.0.113.1")
    _check_from(ip_limited_client, "::ffff:203.0.113.1")

    assert _check_from(ip_limited_client, "203.0.113.1") == 429


# ── Path classification (_classify_path) ────────────────────────────

# Media: `/audio/*`, the authenticated queue-stream audio route (review
# finding 2a: previously untested), and every public share's audio route.
# Stream: the two SSE endpoints. Everything else, including a slug that
# literally reads "audio" hitting a real metadata route, is API -- fail
# closed, and the documented exception (finding 2b: previously untested)
# that `/shared/{slug}/cover` and `/shared/{slug}/stream` stay API however
# their slug is spelled.
@pytest.mark.parametrize(("path", "expected_class"), [
    ("/audio/owner/file.mp3", RateLimitClass.MEDIA),
    ("/api/queue-streams/some-id/audio", RateLimitClass.MEDIA),
    ("/shared/realslug/audio/owner/file.mp3", RateLimitClass.MEDIA),
    ("/shared/song/realslug/audio/owner/file.mp3", RateLimitClass.MEDIA),
    ("/shared/gen/realslug/audio/owner/file.mp3", RateLimitClass.MEDIA),
    ("/shared/playlist/realslug/audio/owner/file.mp3", RateLimitClass.MEDIA),
    ("/shared/queue-streams/some-id/audio", RateLimitClass.MEDIA),
    ("/api/resource-events/stream", RateLimitClass.STREAM),
    ("/api/jobs/some-job-id/stream", RateLimitClass.STREAM),
    ("/this-path-does-not-exist", RateLimitClass.API),
    ("/api/auth/check", RateLimitClass.API),
    ("/api/audio/upload", RateLimitClass.API),
    ("/api/queue-streams", RateLimitClass.API),
    ("/api/queue-streams/library", RateLimitClass.API),
    ("/api/queue-streams/some-id/pin", RateLimitClass.API),
    ("/shared/realslug", RateLimitClass.API),
    ("/shared/realslug/cover", RateLimitClass.API),
    ("/shared/realslug/stream", RateLimitClass.API),
    ("/shared/song/realslug", RateLimitClass.API),
    ("/shared/song/realslug/cover", RateLimitClass.API),
    ("/shared/gen/realslug", RateLimitClass.API),
    ("/shared/playlist/realslug", RateLimitClass.API),
    ("/shared/playlist/realslug/stream", RateLimitClass.API),
    # Regression (review finding 1): a slug that literally reads "audio"
    # must not slide a real metadata route into Media by shape alone.
    ("/shared/audio", RateLimitClass.API),
    ("/shared/audio/cover", RateLimitClass.API),
    ("/shared/audio/stream", RateLimitClass.API),
    ("/shared/song/audio", RateLimitClass.API),
    ("/shared/gen/audio", RateLimitClass.API),
    ("/shared/playlist/audio", RateLimitClass.API),
    # Blocker fix: the router resolves this to the playlist manifest POST
    # (`/shared/playlist/{slug}/stream`, slug="audio"), a metadata handler
    # -- not the bare-slug audio route ([^/]+="playlist", filename="stream").
    ("/shared/playlist/audio/stream", RateLimitClass.API),
    # ...but the genuine media route for a slug literally named "audio"
    # still classifies as Media -- it has a filename segment after "audio/".
    ("/shared/audio/audio/owner/file.mp3", RateLimitClass.MEDIA),
])
def test_classify_path(path: str, expected_class: RateLimitClass) -> None:
    assert _classify_path(path) == expected_class


# ── Rate limit classes (issue #257) ─────────────────────────────────


@pytest.fixture
def class_limited_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("IP_RATE_LIMIT", "2")
    monkeypatch.setenv("MEDIA_RATE_LIMIT", "2")
    monkeypatch.setenv("STREAM_RATE_LIMIT", "2")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    client, _ = make_test_app(tmp_path, seed_db=_seed_rate_limit_data)
    yield client
    get_settings.cache_clear()


def test_media_budget_exhausted_does_not_block_api_class(
    class_limited_client: TestClient,
) -> None:
    for _ in range(3):
        class_limited_client.get("/audio/someone/missing.mp3")

    resp = class_limited_client.get("/audio/someone/missing.mp3")
    assert resp.status_code == 429

    api_resp = class_limited_client.get("/api/auth/check")
    assert api_resp.status_code != 429


def test_api_budget_exhausted_does_not_block_media_class(
    class_limited_client: TestClient,
) -> None:
    for _ in range(3):
        class_limited_client.get("/api/auth/check")

    api_resp = class_limited_client.get("/api/auth/check")
    assert api_resp.status_code == 429

    media_resp = class_limited_client.get("/audio/someone/missing.mp3")
    assert media_resp.status_code != 429


def test_stream_budget_exhausted_does_not_block_api_class(
    class_limited_client: TestClient,
) -> None:
    for _ in range(3):
        class_limited_client.get("/api/resource-events/stream")

    stream_resp = class_limited_client.get("/api/resource-events/stream")
    assert stream_resp.status_code == 429

    api_resp = class_limited_client.get("/api/auth/check")
    assert api_resp.status_code != 429


def test_job_stream_path_is_in_stream_class(class_limited_client: TestClient) -> None:
    for _ in range(3):
        class_limited_client.get("/api/jobs/some-job-id/stream")

    resp = class_limited_client.get("/api/jobs/some-job-id/stream")
    assert resp.status_code == 429

    api_resp = class_limited_client.get("/api/auth/check")
    assert api_resp.status_code != 429


def test_unknown_path_falls_back_to_api_class(class_limited_client: TestClient) -> None:
    for _ in range(2):
        class_limited_client.get("/this-path-does-not-exist")

    resp = class_limited_client.get("/api/auth/check")

    assert resp.status_code == 429


# ── Shared audio is Media, shared metadata stays API (issue #257) ──


def _seed_shared_album_data(session) -> None:
    session.add(Album(id="shared_album", title="Shared Album", artist="Band"))
    session.add(Song(id="ss1", title="Song", album_id="shared_album", track_number=1))
    session.add(Version(
        id="sv1", song_id="ss1", version_number=1, lyrics="hi", prompt="pop",
    ))
    session.add(Generation(
        id="sg1", song_id="ss1", version_id="sv1", generation_number=1,
        mp3_path="admin_user/g1.mp3", is_picked=True,
    ))


@pytest.fixture
def shared_slug_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, str]:
    # Setup itself spends 2 API-class calls (login + share), so the budget
    # needs headroom above that before the test's own assertions run.
    monkeypatch.setenv("IP_RATE_LIMIT", "5")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    client, _ = make_test_app(tmp_path, seed_db=_seed_shared_album_data)
    admin_audio_dir = tmp_path / "audio" / "admin_user"
    admin_audio_dir.mkdir(parents=True, exist_ok=True)
    (admin_audio_dir / "g1.mp3").write_bytes(b"\xff\xfb\x90\x00" * 100)

    factory = client.app.state.ctx.db
    with factory() as session:
        admin = create_user(session, "admin", hash_password("t3stP@ssw0rd"), role="admin")
        album = session.query(Album).filter_by(id="shared_album").first()
        album.created_by = admin.id
        session.commit()
    from conftest import login_and_csrf
    login_and_csrf(client, "admin", "t3stP@ssw0rd")
    slug = client.post("/api/albums/shared_album/share").json()["share_slug"]
    client.cookies.clear()
    yield client, slug
    get_settings.cache_clear()


def test_shared_audio_does_not_consume_api_budget(
    shared_slug_client: tuple[TestClient, str],
) -> None:
    client, slug = shared_slug_client

    for _ in range(5):
        audio_resp = client.get(f"/shared/{slug}/audio/admin_user/g1.mp3")
        assert audio_resp.status_code != 429

    metadata_resp = client.get(f"/shared/{slug}")
    assert metadata_resp.status_code != 429


def test_shared_metadata_still_shares_the_api_budget(
    shared_slug_client: tuple[TestClient, str],
) -> None:
    client, slug = shared_slug_client

    for _ in range(6):
        client.get(f"/shared/{slug}")

    metadata_resp = client.get(f"/shared/{slug}")
    assert metadata_resp.status_code == 429


# ── Job gets user_id ────────────────────────────────────────────────


def test_generate_job_gets_user_id(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    with _mock_arq():
        resp = client.post("/api/songs/s1/generate", json={"count": 1, "model": "sft"})

    assert resp.status_code == 200
    job_id = resp.json()["id"]

    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(id=job_id).one()
        assert job.user_id == user_id


def test_score_job_gets_user_id(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    with _mock_arq():
        resp = client.post("/api/generations/g1/score", json={})

    assert resp.status_code == 200
    job_id = resp.json()["id"]

    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(id=job_id).one()
        assert job.user_id == user_id
