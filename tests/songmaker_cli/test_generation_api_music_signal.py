"""A generation is admitted while the music signal is alive, a restart inside its grace included."""

from __future__ import annotations

import json
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

from songmaker_cli.db.models import Album, AvailableModel, Song, User, Version
from songmaker_cli.db.queries.workers import register_worker
from songmaker_cli.timestamps import utcnow
from songmaker_cli.worker_liveness import MUSIC_LAST_ALIVE_KEY

OWNER_ID = "owner"
GENERATE = "/api/songs/song/generate"


def _seed_song_and_gpu_worker(session: Session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id="album", title="Album", artist="X", created_by=OWNER_ID))
    session.add(Song(id="song", title="Song", album_id="album", track_number=1, slug="song"))
    session.add(Version(id="version", song_id="song", version_number=1, lyrics="l", prompt="p"))
    session.query(AvailableModel).filter(AvailableModel.id == "sft").update({"is_active": True})
    register_worker(
        session, worker_id="gpu-worker", host="h", port=8001, gpu_id=0, vram_total_gb=24.0,
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


@pytest.mark.parametrize(
    ("music_last_alive_seconds_ago", "expected_status"),
    [
        pytest.param(5, 200, id="a restart inside the grace"),
        pytest.param(None, 503, id="never seen alive"),
    ],
)
def test_generation_follows_the_music_signal_while_no_music_worker_holds_a_lease(
    client: TestClient, music_last_alive_seconds_ago: int | None, expected_status: int,
) -> None:
    ctx = client.app.state.ctx
    if music_last_alive_seconds_ago is not None:
        seen_at = utcnow() - timedelta(seconds=music_last_alive_seconds_ago)
        ctx.redis.set(MUSIC_LAST_ALIVE_KEY, seen_at.isoformat())
    gpu_heartbeat = {"loaded": [{"mode": "sft", "size_gb": 0}], "gpu_healthy": True}
    pool = AsyncMock(get=AsyncMock(return_value=json.dumps(gpu_heartbeat).encode()))

    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=pool),
        patch(
            "songmaker_cli.generation_api.is_scoring_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch.object(ctx.wake_channel, "publish", AsyncMock()),
    ):
        response = client.post(GENERATE, json={"count": 1, "model": "sft"})

    assert response.status_code == expected_status
