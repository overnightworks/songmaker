"""Tests for admin API endpoints — voices, workers, model registry, retention."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_user

from songmaker_cli.cleanup import GENERATION_RETENTION_HOUR_UTC
from songmaker_cli.constants import INTERNAL_TOKEN_HEADER
from songmaker_cli.db.queries.loras import create_user_lora


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path)
    return client


def _login_as_admin(client: TestClient) -> None:
    from support.web_app import seed_session
    factory = client.app.state.ctx.db
    with factory() as session:
        seed_user(session, "admin", "admin")
        session.commit()
    seed_session(client, "admin")


def _login_as_user(client: TestClient) -> None:
    from support.web_app import seed_session
    factory = client.app.state.ctx.db
    with factory() as session:
        seed_user(session, "regular", "user")
        session.commit()
    seed_session(client, "regular")


# -- Access control -----------------------------------------------------------


def test_admin_endpoints_require_auth(client: TestClient) -> None:
    resp = client.get("/api/admin/voices")
    assert resp.status_code == 401


def test_admin_endpoints_require_admin_role(client: TestClient) -> None:
    _login_as_user(client)
    resp = client.get("/api/admin/voices")
    assert resp.status_code == 403


# -- List users ---------------------------------------------------------------


def test_admin_lists_every_musicians_active_voice(client: TestClient) -> None:
    _login_as_admin(client)
    factory = client.app.state.ctx.db
    with factory() as session:
        musician = seed_user(session, "musician")
        warm_tenor = create_user_lora(session, musician.id, "Warm Tenor", "warm-tenor")
        dry_spoken_word = create_user_lora(
            session, musician.id, "Dry Spoken Word", "dry-spoken-word",
        )
        warm_tenor_id = warm_tenor.id
        dry_spoken_word_id = dry_spoken_word.id
        session.commit()

    response = client.get("/api/admin/voices")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": dry_spoken_word_id,
            "name": "Dry Spoken Word",
            "owner_username": "musician",
            "status": "draft",
        },
        {
            "id": warm_tenor_id,
            "name": "Warm Tenor",
            "owner_username": "musician",
            "status": "draft",
        },
    ]


def test_non_admin_cannot_list_voices(client: TestClient) -> None:
    _login_as_user(client)

    response = client.get("/api/admin/voices")

    assert response.status_code == 403


# -- Worker pool / registry ---------------------------------------------------


def _seed_worker(client: TestClient, worker_id: str, **kwargs) -> None:
    from songmaker_cli.db.queries.workers import register_worker

    factory = client.app.state.ctx.db
    with factory() as session:
        register_worker(
            session,
            worker_id=worker_id,
            host=kwargs.get("host", worker_id),
            port=kwargs.get("port", 8001),
            gpu_id=kwargs.get("gpu_id", 0),
            vram_total_gb=kwargs.get("vram_total_gb", 24.0),
        )
        session.commit()


class _InMemoryAsyncRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex: int | None = None) -> None:
        self._store[key] = value

    async def incr(self, key: str) -> int:
        cur = int(self._store.get(key, 0)) + 1
        self._store[key] = str(cur)
        return cur

    async def decr(self, key: str) -> int:
        cur = int(self._store.get(key, 0)) - 1
        self._store[key] = str(cur)
        return cur


def _override_pool(client: TestClient, pool) -> None:
    from songmaker_cli.arq_pool import get_arq_pool_dep
    client.app.dependency_overrides[get_arq_pool_dep] = lambda: pool


def _make_fake_pool() -> _InMemoryAsyncRedis:
    return _InMemoryAsyncRedis()


def test_list_workers_empty(client: TestClient) -> None:
    _login_as_admin(client)
    _override_pool(client, _make_fake_pool())
    resp = client.get("/api/admin/workers")
    assert resp.status_code == 200
    assert resp.json() == {"workers": []}


def test_list_workers_online(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "acestep-worker-0")
    pool = _make_fake_pool()
    state = {
        "loaded": [{"mode": "sft", "size_gb": 6.0}],
        "target_loading": None,
        "loading_started_at": None,
        "vram_used_gb": 12.4,
        "vram_total_gb": 24.0,
        "available_modes": ["sft", "turbo"],
        "pinned": [],
        "last_heartbeat_at": "2026-04-07T12:00:00+00:00",
        "gpu_healthy": True,
    }
    pool._store[worker_state_key("acestep-worker-0")] = json.dumps(state)
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["workers"]) == 1
    w = data["workers"][0]
    assert w["identity"]["id"] == "acestep-worker-0"
    assert w["status"] == "online"
    assert w["state"]["loaded"] == [{"mode": "sft", "size_gb": 6.0}]
    assert w["state"]["available_modes"] == ["sft", "turbo"]
    assert w["state"]["pinned"] == []
    assert w["state"]["loading_last_log_line"] is None


def test_list_workers_propagates_loading_last_log_line(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {
            "loaded": [],
            "target_loading": "xl-turbo",
            "loading_last_log_line": "vllm: loading shard 3/4",
            "gpu_healthy": True,
        },
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    state = resp.json()["workers"][0]["state"]
    assert state["loading_last_log_line"] == "vllm: loading shard 3/4"


@pytest.mark.parametrize("heartbeat_kind", ["error", "fresh", "legacy", "missing"])
def test_list_workers_last_error_transport(
    client: TestClient, tmp_path: Path, heartbeat_kind: str,
) -> None:
    """S15-04: List workers last error transport."""
    import asyncio
    import json

    from acestep_worker.clock import utcnow
    from acestep_worker.heartbeat import HeartbeatLoop
    from acestep_worker.last_error import LastError
    from acestep_worker.model_cache import ModelCache
    from acestep_worker.task_store import TaskStore
    from acestep_worker.wrapper import WorkerDeps, build_state_payload
    from songmaker_cli.acestep_state import worker_state_key

    async def unused(*args, **kwargs):
        raise AssertionError("No model operation is expected")

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    # The payload provider needs TTL; FakeRedis supplies the real Redis contract.
    import fakeredis.aioredis

    redis = fakeredis.aioredis.FakeRedis()
    deps = WorkerDeps(
        worker_id="w1", cache=ModelCache(
            vram_budget_gb=24, model_sizes={}, loader=unused, unloader=unused,
        ),
        task_store=TaskStore(), heartbeat=None, redis=redis,
        registry_client=None, registration=None, checkpoint_dir=tmp_path,
        audio_output_dir=tmp_path, generate_runner=unused, internal_token="test-token",
    )
    error = LastError("ACE-Step failed\nworker diagnostic", utcnow())
    if heartbeat_kind == "error":
        deps.last_error = error

    async def publish():
        if heartbeat_kind == "missing":
            return
        if heartbeat_kind == "legacy":
            await pool.set(worker_state_key("w1"), json.dumps({"loaded": [], "gpu_healthy": True}))
            return
        heartbeat = HeartbeatLoop(
            redis=redis, worker_id="w1", state_provider=lambda: build_state_payload(deps),
        )
        await heartbeat.publish_once()
        await pool.set(worker_state_key("w1"), await redis.get(worker_state_key("w1")))

    asyncio.run(publish())
    _override_pool(client, pool)
    response = client.get("/api/admin/workers")
    assert response.status_code == 200
    state = response.json()["workers"][0]["state"]
    if heartbeat_kind == "missing":
        assert state is None
    else:
        assert state["last_error"] == (error.message if heartbeat_kind == "error" else None)
        expected_at = error.at.isoformat() if heartbeat_kind == "error" else None
        assert state["last_error_at"] == expected_at


@pytest.mark.parametrize("role", ["anonymous", "user", "admin"])
def test_last_error_worker_list_requires_admin(client: TestClient, role: str) -> None:
    """S15-06: Last error worker list requires admin."""
    import asyncio
    import json

    from songmaker_cli.acestep_state import worker_state_key

    if role == "admin":
        _login_as_admin(client)
    elif role == "user":
        _login_as_user(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    sentinel = "PRIVATE-WORKER-DIAGNOSTIC"
    asyncio.run(pool.set(worker_state_key("w1"), json.dumps({
        "loaded": [], "gpu_healthy": True,
        "last_error": sentinel, "last_error_at": "2026-10-18T10:00:00+00:00",
    })))
    _override_pool(client, pool)
    response = client.get("/api/admin/workers")
    assert response.status_code == {"anonymous": 401, "user": 403, "admin": 200}[role]
    assert (sentinel in response.text) is (role == "admin")


def test_last_error_stays_out_of_public_and_musician_paths(
    client: TestClient, mock_arq_pool,
) -> None:
    """S15-06: Last error stays out of public and musician paths."""
    import asyncio
    import json
    from unittest.mock import AsyncMock

    from acestep_worker.clock import utcnow
    from songmaker_cli.acestep_state import worker_state_key
    from songmaker_cli.arq_pool import init_arq_pool
    from songmaker_cli.constants import ARQ_MUSIC_HEALTH_KEY
    from songmaker_cli.db.queries.albums import create_album
    from songmaker_cli.db.queries.auth import get_user_by_username
    from songmaker_cli.db.queries.songs import create_song
    from songmaker_cli.health_types import BackgroundLoopName, BackgroundLoopRegistry
    from songmaker_cli.worker_liveness import WorkerLiveness, acestep_worker_liveness

    sentinel = "PRIVATE-WORKER-DIAGNOSTIC-18.5-GB"
    payload = json.dumps({
        "loaded": [], "gpu_healthy": True, "last_error": sentinel,
        "last_error_at": "2026-10-18T10:00:00+00:00",
    })
    redis = _make_fake_pool()

    async def prepare_pool():
        pool = await init_arq_pool()
        pool.get = AsyncMock(side_effect=redis.get)
        pool.set = AsyncMock(side_effect=redis.set)
        pool.exists = AsyncMock(return_value=True)
        pool.zcard = AsyncMock(return_value=0)
        await pool.set(worker_state_key("w1"), payload)
        await pool.set(ARQ_MUSIC_HEALTH_KEY, "healthy")

    asyncio.run(prepare_pool())
    client.app.state.background_loop_registry = BackgroundLoopRegistry(tuple(BackgroundLoopName))
    _seed_worker(client, "w1")
    for path in ("/health", "/metrics"):
        response = client.get(path)
        assert response.status_code == 200
        assert sentinel not in response.text
    _login_as_user(client)
    with client.app.state.ctx.db() as session:
        user = get_user_by_username(session, "regular")
        album = create_album(session, "last-error-proof", "Last error proof", created_by=user.id)
        song = create_song(
            session, "Proof", album.id, slug="proof", lyrics="Words", prompt="Jazz",
            created_by=user.id,
        )
        song_id = song.id
        session.commit()
    response = client.post(f"/api/songs/{song_id}/generate", json={"model": "sft"})
    assert response.status_code == 200
    assert sentinel not in response.text
    sync_redis = client.app.state.ctx.redis
    sync_redis.set(worker_state_key("w1"), payload)
    liveness = acestep_worker_liveness(sync_redis, ["w1"], now=utcnow())
    assert liveness is WorkerLiveness.ALIVE


def test_list_workers_loading(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {"loaded": [], "target_loading": "xl-sft", "gpu_healthy": True},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    assert resp.json()["workers"][0]["status"] == "loading"


def test_list_workers_offline_when_redis_missing(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_fake_pool())
    resp = client.get("/api/admin/workers")
    data = resp.json()
    assert data["workers"][0]["status"] == "offline"
    assert data["workers"][0]["state"] is None


def test_list_workers_offline_when_gpu_broken(client: TestClient) -> None:
    """Issue #367 finding 3: a worker whose GPU has gone away keeps
    heartbeating fine, so the worker pool must not show it as "online" on
    heartbeat presence alone — simulated NVML failure, not a lucky real
    GPU."""
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {"loaded": ["sft"], "gpu_healthy": False},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    data = resp.json()
    assert data["workers"][0]["status"] == "offline"


def test_list_workers_includes_queue_depth(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import queue_depth_key, worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps({"loaded": ["sft"]})
    pool._store[queue_depth_key("w1")] = "3"
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")
    assert resp.json()["workers"][0]["state"]["queue_depth"] == 3


def test_list_workers_ignores_invalid_heartbeat(client: TestClient, caplog) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "renamed-field")
    pool = _make_fake_pool()
    pool._store[worker_state_key("renamed-field")] = json.dumps(
        {"renamed_loaded": ["sft"], "gpu_healthy": True},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/workers")

    assert resp.status_code == 200
    assert resp.json()["workers"][0]["state"] is None
    assert resp.json()["workers"][0]["status"] == "offline"
    assert any(record.args == ("renamed-field",) for record in caplog.records)

    registry = client.get("/api/admin/registry")
    assert registry.status_code == 200
    sft = next(model for model in registry.json()["models"] if model["mode"] == "sft")
    assert sft["loaded_on"] == []


def test_registry_union_across_workers(client: TestClient) -> None:
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    _seed_worker(client, "w2")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {
            "loaded": ["sft"], "target_loading": None, "available_modes": ["sft"],
            "gpu_healthy": True,
        },
    )
    pool._store[worker_state_key("w2")] = json.dumps(
        {
            "loaded": [], "target_loading": "turbo", "available_modes": ["turbo"],
            "gpu_healthy": True,
        },
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/registry")
    assert resp.status_code == 200
    by_mode = {m["mode"]: m for m in resp.json()["models"]}
    assert by_mode["sft"]["availability"] == "downloaded"
    assert by_mode["sft"]["loaded_on"] == ["w1"]
    assert by_mode["sft"]["loading_on"] == []
    assert by_mode["turbo"]["availability"] == "downloaded"
    assert by_mode["turbo"]["loaded_on"] == []
    assert by_mode["turbo"]["loading_on"] == ["w2"]
    assert by_mode["xl-sft"]["availability"] == "not_downloaded"


def test_registry_unknown_availability_when_only_worker_gpu_broken(
    client: TestClient,
) -> None:
    """Same as "no worker online" (issue #252) — a worker whose only
    heartbeat says gpu_healthy: false must not make the registry think a
    real worker is answering."""
    import json

    from songmaker_cli.acestep_state import worker_state_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_fake_pool()
    pool._store[worker_state_key("w1")] = json.dumps(
        {"loaded": ["sft"], "available_modes": ["sft"], "gpu_healthy": False},
    )
    _override_pool(client, pool)

    resp = client.get("/api/admin/registry")
    assert resp.status_code == 200
    availabilities = {m["availability"] for m in resp.json()["models"]}
    assert availabilities == {"unknown_no_worker"}


def test_registry_unknown_availability_when_no_worker_online(client: TestClient) -> None:
    # The GPU worker sat on "Created" for five days without ever starting
    # (issue #252's live incident): the registry saw zero online workers and
    # called every model "not downloaded", as if the files were missing
    # rather than nobody being around to report on them. A model's download
    # state must read as unknown, not as a false negative, when no worker is
    # online to answer the question.
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": None}))

    resp = client.get("/api/admin/registry")
    assert resp.status_code == 200
    availabilities = {m["availability"] for m in resp.json()["models"]}
    assert availabilities == {"unknown_no_worker"}


def test_load_model_on_worker_enqueues_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/admin/workers/w1/load_model", json={"mode": "sft"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "load_model_on_worker"
    assert data["status"] == "queued"
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    mock_pool.enqueue_job.assert_called_once_with(
        "load_model_on_worker", data["id"], "w1", "sft",
        _queue_name=ARQ_MUSIC_QUEUE_NAME,
    )


def test_load_model_on_worker_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/load_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_load_model_on_worker_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/load_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_load_model_on_worker_queue_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/admin/workers/w1/load_model", json={"mode": "sft"},
        )
    assert resp.status_code == 503


def test_evict_model_proxies_to_worker(client: TestClient, internal_token: str) -> None:
    """1301-F10-FIXTURE: forward the configured internal token."""
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1", host="example", port=8001)

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/evict_model", json={"mode": "sft"},
        )

    assert resp.status_code == 200
    fake_client.post.assert_called_once()
    args, kwargs = fake_client.post.call_args
    assert args[0] == "http://example:8001/evict_model"
    assert kwargs["json"] == {"mode": "sft"}
    assert kwargs["headers"][INTERNAL_TOKEN_HEADER] == internal_token


def test_evict_model_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/evict_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_evict_model_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/evict_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_evict_model_worker_unreachable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    import httpx

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/evict_model", json={"mode": "sft"},
        )
    assert resp.status_code == 502


def test_evict_model_worker_returns_4xx(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock()
    fake_response.status_code = 500
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/evict_model", json={"mode": "sft"},
        )
    assert resp.status_code == 502


# ── pin_model_on_worker_endpoint ────────────────────────────────────


def test_pin_model_on_worker_success(client: TestClient, internal_token: str) -> None:
    """1301-F10-FIXTURE: forward the configured internal token."""
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=200)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/pin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 200
    args, kwargs = fake_client.post.call_args
    assert args[0].endswith("/pin_model")
    assert kwargs["json"] == {"mode": "sft"}
    assert kwargs["headers"][INTERNAL_TOKEN_HEADER] == internal_token


def test_pin_model_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/pin_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_pin_model_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/pin_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


def test_pin_model_worker_409_passes_through(client: TestClient) -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=409)
    fake_response.json = MagicMock(return_value={"detail": "Cannot pin sft: not loaded"})
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/pin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 409
    assert "not loaded" in resp.json()["detail"]


def test_pin_model_worker_unreachable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    import httpx

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/pin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 502


def test_pin_model_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/workers/w1/pin_model", json={"mode": "sft"})
    assert resp.status_code in (401, 403)


# ── unpin_model_on_worker_endpoint ──────────────────────────────────


def test_unpin_model_on_worker_success(client: TestClient, internal_token: str) -> None:
    """1301-F10-FIXTURE: forward the configured internal token."""
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=200)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post(
            "/api/admin/workers/w1/unpin_model", json={"mode": "sft"},
        )
    assert resp.status_code == 200
    args, kwargs = fake_client.post.call_args
    assert args[0].endswith("/unpin_model")
    assert kwargs["headers"][INTERNAL_TOKEN_HEADER] == internal_token


def test_unpin_model_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post(
        "/api/admin/workers/missing/unpin_model", json={"mode": "sft"},
    )
    assert resp.status_code == 404


def test_unpin_model_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    resp = client.post(
        "/api/admin/workers/w1/unpin_model", json={"mode": "bogus"},
    )
    assert resp.status_code == 400


# ── restart_worker_endpoint ─────────────────────────────────────────


def test_restart_worker_success(client: TestClient, internal_token: str) -> None:
    """1301-F10-FIXTURE: forward the configured internal token."""
    from unittest.mock import AsyncMock, MagicMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_response = MagicMock(status_code=200)
    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_response)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post("/api/admin/workers/w1/restart")
    assert resp.status_code == 200
    assert resp.json()["status"] == "restarting"
    args, kwargs = fake_client.post.call_args
    assert args[0].endswith("/restart")
    assert kwargs["headers"][INTERNAL_TOKEN_HEADER] == internal_token


def test_restart_worker_unknown_worker(client: TestClient) -> None:
    _login_as_admin(client)
    resp = client.post("/api/admin/workers/missing/restart")
    assert resp.status_code == 404


def test_restart_worker_unreachable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    import httpx

    _login_as_admin(client)
    _seed_worker(client, "w1")

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    with patch("songmaker_cli.admin_api.httpx.AsyncClient", return_value=fake_client):
        resp = client.post("/api/admin/workers/w1/restart")
    assert resp.status_code == 502
    # The restart button is the one thing someone reaches for on a dead
    # worker; it must say why it can't help instead of relaying a bare
    # connection error (issue #252).
    detail = resp.json()["detail"]
    assert "can't be asked to restart itself" in detail
    assert "restart the container directly" in detail.lower()


def test_restart_worker_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/workers/w1/restart")
    assert resp.status_code in (401, 403)


# ── download_model_endpoint ─────────────────────────────────────────


def _make_pool_with_state(
    states: dict[str, dict | None], *, gpu_healthy: bool = True,
) -> object:
    """Defaults every present worker's heartbeat to a healthy GPU so the
    many download-endpoint tests unrelated to issue #367 don't need to know
    about it. A state dict that already carries "gpu_healthy" (e.g. to
    simulate a broken worker) is never overridden."""
    import json

    from songmaker_cli.acestep_state import worker_state_key

    pool = _make_fake_pool()
    for wid, state in states.items():
        if state is not None:
            payload = dict(state)
            payload.setdefault("gpu_healthy", gpu_healthy)
            pool._store[worker_state_key(wid)] = json.dumps(payload)
    return pool


def test_download_endpoint_unknown_mode(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": {"available_modes": []}}))
    resp = client.post("/api/admin/registry/ghost/download")
    assert resp.status_code == 400


def test_download_endpoint_no_workers(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": None}))
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code == 503


def test_download_endpoint_no_workers_when_gpu_broken(client: TestClient) -> None:
    """Issue #367 finding 3: the download precheck must not treat a
    heartbeating-but-GPU-broken worker as available — it would otherwise
    fail asynchronously later with a generic "no workers", exactly the
    delayed-symptom pattern from issue #252."""
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(
        client,
        _make_pool_with_state({"w1": {"available_modes": [], "gpu_healthy": False}}),
    )
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code == 503
    assert "No online workers available to download" in resp.json()["detail"]


def test_download_endpoint_already_downloaded(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(
        client,
        _make_pool_with_state({"w1": {"available_modes": ["sft", "turbo"]}}),
    )
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code == 409
    assert "already downloaded" in resp.json()["detail"]


def test_download_endpoint_already_in_progress(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.acestep_state import download_key

    _login_as_admin(client)
    _seed_worker(client, "w1")
    pool = _make_pool_with_state({"w1": {"available_modes": []}})
    pool._store[download_key("xl-base")] = "previous-job-id"
    _override_pool(client, pool)

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())
    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/registry/xl-base/download")

    assert resp.status_code == 409
    assert "already being downloaded" in resp.json()["detail"]
    mock_pool.enqueue_job.assert_not_called()


def test_download_endpoint_enqueues_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": {"available_modes": []}}))

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=AsyncMock())
    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/registry/xl-base/download")

    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "download_model_on_worker"
    assert data["status"] == "queued"

    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    mock_pool.enqueue_job.assert_called_once_with(
        "download_model_on_worker", data["id"], "xl-base",
        _queue_name=ARQ_MUSIC_QUEUE_NAME,
    )


def test_download_endpoint_queue_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    _login_as_admin(client)
    _seed_worker(client, "w1")
    _override_pool(client, _make_pool_with_state({"w1": {"available_modes": []}}))

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(side_effect=ConnectionError("redis down"))
    with patch("songmaker_cli.arq_pool.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/admin/registry/xl-base/download")

    assert resp.status_code == 503


def test_download_endpoint_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/registry/sft/download")
    assert resp.status_code in (401, 403)


# -- Generation retention -----------------------------------------------------


def _seed_album_with_gens(client: TestClient) -> None:
    from songmaker_cli.db.models import Album, Generation, Song, Version
    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.add(
            Version(id="v1", song_id="s1", version_number=1, lyrics="", prompt=""),
        )
        session.add(
            Generation(
                id="g1", song_id="s1", version_id="v1",
                generation_number=1, mp3_path="a1/1.mp3",
            ),
        )
        session.commit()


def test_retention_preview_requires_admin(client: TestClient) -> None:
    resp = client.get("/api/admin/generation-retention/preview")
    assert resp.status_code in (401, 403)


def test_retention_run_requires_admin(client: TestClient) -> None:
    resp = client.post("/api/admin/generation-retention/run")
    assert resp.status_code in (401, 403)


def test_retention_preview_returns_counts(client: TestClient) -> None:
    _login_as_admin(client)
    _seed_album_with_gens(client)
    resp = client.get("/api/admin/generation-retention/preview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert {"archived_ids", "deleted_ids"} <= body.keys()
    assert body["retention_days"] >= 1
    assert body["hard_delete_days"] >= 1
    assert body["scheduled_hour_utc"] == GENERATION_RETENTION_HOUR_UTC


def test_retention_run_executes(client: TestClient) -> None:
    from datetime import datetime, timedelta, timezone

    from songmaker_cli.db.models import Generation

    _login_as_admin(client)
    _seed_album_with_gens(client)
    factory = client.app.state.ctx.db
    with factory() as session:
        gen = session.get(Generation, "g1")
        gen.created_at = datetime.now(timezone.utc) - timedelta(days=365)
        session.commit()

    resp = client.post("/api/admin/generation-retention/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert "g1" in body["archived_ids"]
