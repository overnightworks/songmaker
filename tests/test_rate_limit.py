"""Tests for rate limiting on generate/score endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.auth import hash_password
from songmaker_cli.db.models import Album, Generation, Job, Song, Version
from songmaker_cli.db.queries import create_user


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


@pytest.fixture()
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

    resp = client.post("/api/songs/s1/generate", json={"count": 1})

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
        resp = client.post("/api/songs/s1/generate", json={"count": 1})

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


def test_active_job_limit(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    with patch("songmaker_cli.api_helpers.MAX_USER_ACTIVE_JOBS", 1):
        factory = client.app.state.ctx.db
        with factory() as session:
            session.add(Job(type="generate", user_id=user_id, status="running"))
            session.commit()

        resp = client.post("/api/songs/s1/generate", json={"count": 1})

        assert resp.status_code == 429
        assert "active job" in resp.json()["detail"]


def test_score_job_does_not_block_generate(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    factory = client.app.state.ctx.db
    with factory() as session:
        session.add(Job(type="score", user_id=user_id, status="running"))
        session.commit()

    with _mock_arq():
        resp = client.post("/api/songs/s1/generate", json={"count": 1})

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


def test_queue_depth_limit(client: TestClient) -> None:
    _login_as(client, "user")

    with patch("songmaker_cli.api_helpers.MAX_QUEUE_DEPTH", 10):
        factory = client.app.state.ctx.db
        with factory() as session:
            for _ in range(10):
                session.add(Job(type="generate", status="queued"))
            session.commit()

        resp = client.post("/api/songs/s1/generate", json={"count": 1})

        assert resp.status_code == 429
        assert "Queue is full" in resp.json()["detail"]


# ── Job gets user_id ────────────────────────────────────────────────


def test_generate_job_gets_user_id(client: TestClient) -> None:
    _login_as(client, "user")
    user_id = _get_user_id(client)

    with _mock_arq():
        resp = client.post("/api/songs/s1/generate", json={"count": 1})

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
