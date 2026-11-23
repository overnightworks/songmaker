"""A generation is admitted while the music signal is alive, a restart inside its grace included."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.web_app import (
    arrange_fake_async_redis,
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    settle_owner_leases,
    web_client,
)

from songmaker_cli import arq_pool
from songmaker_cli.acestep_state import worker_state_key
from songmaker_cli.db.models import Album, AvailableModel, Song, User, Version
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_liveness import MUSIC_LAST_ALIVE_KEY

OWNER_ID = "owner"
GENERATE = "/api/songs/song/generate"
GPU_WORKER_ID = "gpu-worker"


def _seed_song_and_gpu_worker(session: Session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id="album", title="Album", artist="X", created_by=OWNER_ID))
    session.add(Song(id="song", title="Song", album_id="album", track_number=1, slug="song"))
    session.add(Version(id="version", song_id="song", version_number=1, lyrics="l", prompt="p"))
    session.query(AvailableModel).filter(AvailableModel.id == "sft").update({"is_active": True})
    register_worker(
        session, worker_id=GPU_WORKER_ID, host="h", port=8001, gpu_id=0, vram_total_gb=24.0,
    )
    session.commit()


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> TestClient:
    with pg_factory() as session:
        _seed_song_and_gpu_worker(session)
    ctx = make_router_ctx(tmp_path, db=pg_factory)
    arrange_fake_async_redis(ctx.async_redis, settle_owner_leases)
    app = make_router_app(ctx, user=make_authenticated_user(OWNER_ID, username="owner"))
    return web_client(app)


@pytest.fixture
def online_gpu_worker(
    client: TestClient, redis_url: str, monkeypatch, fresh_settings: None,
) -> Iterator[None]:
    """The arq pool the app starts with, on the configured Redis, holds the GPU worker's heartbeat.

    The pool starts on the loop that serves the requests, which a Redis connection stays on.
    """
    monkeypatch.setenv("REDIS_URL", redis_url)
    gpu_heartbeat = {"loaded": [{"mode": "sft", "size_gb": 0}], "gpu_healthy": True}

    async def start_the_pool_with_a_heartbeat() -> None:
        pool = await arq_pool.init_arq_pool()
        await pool.set(worker_state_key(GPU_WORKER_ID), json.dumps(gpu_heartbeat))

    with client:
        client.portal.call(start_the_pool_with_a_heartbeat)
        yield
        client.portal.call(arq_pool.close_arq_pool)


@pytest.mark.parametrize(
    ("music_last_alive_seconds_ago", "expected_status"),
    [
        pytest.param(5, 200, id="a restart inside the grace"),
        pytest.param(None, 503, id="never seen alive"),
    ],
)
@pytest.mark.usefixtures("online_gpu_worker")
def test_generation_follows_the_music_signal_while_no_music_worker_holds_a_lease(
    client: TestClient, music_last_alive_seconds_ago: int | None, expected_status: int,
) -> None:
    ctx = client.app.state.ctx
    if music_last_alive_seconds_ago is not None:
        seen_at = utcnow() - timedelta(seconds=music_last_alive_seconds_ago)
        ctx.redis.set(MUSIC_LAST_ALIVE_KEY, seen_at.isoformat())

    with patch.object(ctx.wake_channel, "publish", AsyncMock()):
        response = client.post(GENERATE, json={"count": 1, "model": "sft"})

    assert response.status_code == expected_status
