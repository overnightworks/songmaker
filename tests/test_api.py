"""Integration tests for the REST API endpoints."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    Generation,
    Job,
    Score,
    Song,
    User,
    Version,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

_DEFAULT_USER_ID = "u-test"


def _fake_user(user_id: str, username: str, role: str):
    """Return a dependency override for get_current_user."""
    user = AuthenticatedUser(id=user_id, username=username, role=role, is_active=True)
    return lambda: user


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=_DEFAULT_USER_ID, username="test_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        _seed_db(session, owner_id=_DEFAULT_USER_ID)

    audio_dir = tmp_path / "audio"
    wav_dir = audio_dir / "u-test"
    wav_dir.mkdir(parents=True, exist_ok=True)
    (wav_dir / "g1.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        _DEFAULT_USER_ID, "test_user", "user",
    )
    app.include_router(router)
    yield TestClient(app)


@pytest.fixture()
def unauthed_client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        _seed_db(session)

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.include_router(router)
    yield TestClient(app)


def _make_authed_client(
    tmp_path: Path, role: str = "user", user_id: str = "u-test",
) -> TestClient:
    """Create a TestClient with a fake authenticated user injected."""
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=user_id, username=f"test_{role}",
            password_hash="unused", role=role,
        ))
        session.flush()
        _seed_db(session, owner_id=user_id if role != "admin" else None)

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user(
        user_id, f"test_{role}", role,
    )
    app.include_router(router)
    return TestClient(app)


def _seed_db(session, owner_id: str | None = None) -> None:
    album = Album(id="rock", title="Rock Album", artist="TestBand", created_by=owner_id)
    session.add(album)
    song = Song(id="s1", title="Thunder", album_id="rock", track_number=1)
    session.add(song)
    ver = Version(id="v1", song_id="s1", version_number=1, lyrics="boom", prompt="hard rock")
    session.add(ver)
    gen1 = Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="u-test/g1.mp3", wav_path="u-test/g1.wav", seed=42,
        generation_params={"bpm": 140},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="u-test/g2.mp3", seed=77,
    )
    session.add_all([gen1, gen2])
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 65.0})
    session.add(score)
    session.commit()


def test_list_albums(client: TestClient) -> None:
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["offset"] == 0


def test_list_songs(client: TestClient) -> None:
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["generation_count"] == 2
    assert data["total"] == 1


def test_get_song(client: TestClient) -> None:
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["title"] == "Thunder"
    assert len(d["generations"]) == 2


def test_create_song(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Lightning", "album_id": "rock", "lyrics": "flash", "bpm": 160,
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Lightning"


def test_update_song(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={"lyrics": "kaboom"})
    assert resp.status_code == 200
    assert resp.json()["version_count"] == 2


def test_rename_song(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "Storm"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Storm"
    after = client.get("/api/songs/s1")
    assert after.json()["title"] == "Storm"


def test_rename_song_strips_whitespace(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "  Storm  "})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Storm"


def test_rename_song_rejects_empty(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": ""})
    assert resp.status_code == 422


def test_rename_song_rejects_whitespace_only(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "   "})
    assert resp.status_code == 422


def test_rename_song_rejects_too_long(client: TestClient) -> None:
    resp = client.put("/api/songs/s1/title", json={"title": "x" * 201})
    assert resp.status_code == 422


def test_rename_song_not_found(client: TestClient) -> None:
    resp = client.put("/api/songs/nonexistent/title", json={"title": "Storm"})
    assert resp.status_code == 404


def test_rename_album(client: TestClient) -> None:
    resp = client.put("/api/albums/rock/title", json={"title": "Metal Album"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Metal Album"
    after = client.get("/api/albums/rock")
    assert after.json()["title"] == "Metal Album"


def test_rename_album_strips_whitespace(client: TestClient) -> None:
    resp = client.put("/api/albums/rock/title", json={"title": "  Metal  "})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Metal"


def test_rename_album_rejects_empty(client: TestClient) -> None:
    resp = client.put("/api/albums/rock/title", json={"title": ""})
    assert resp.status_code == 422


def test_rename_album_rejects_whitespace_only(client: TestClient) -> None:
    resp = client.put("/api/albums/rock/title", json={"title": "   "})
    assert resp.status_code == 422


def test_rename_album_rejects_too_long(client: TestClient) -> None:
    resp = client.put("/api/albums/rock/title", json={"title": "x" * 201})
    assert resp.status_code == 422


def test_rename_album_not_found(client: TestClient) -> None:
    resp = client.put("/api/albums/nonexistent/title", json={"title": "Metal"})
    assert resp.status_code == 404


def test_rename_song_other_user_blocked(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id="u-other", username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.add(Song(id="s-other", title="Their Song", album_id="other", track_number=1))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.put("/api/songs/s-other/title", json={"title": "Hijacked"})
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Song).filter_by(id="s-other").first().title == "Their Song"


def test_rename_album_other_user_blocked(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id="u-other", username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(
            id="other", title="Other Album", artist="Them", created_by="u-other",
        ))
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.put("/api/albums/other/title", json={"title": "Hijacked"})
    assert resp.status_code == 404
    with factory() as session:
        assert session.query(Album).filter_by(id="other").first().title == "Other Album"


def test_song_versions(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["lyrics"] == "boom"


def test_get_generation(client: TestClient) -> None:
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["seed"] == 42
    assert resp.json()["model_mode"] == "sft"


def test_rate_generation(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/rate", json={"rating": 85.0, "notes": "awesome"})
    assert resp.status_code == 200

    resp = client.get("/api/generations/g1")
    assert resp.json()["scores"]["user_rating"] == 85.0


def test_rate_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/rate", json={"rating": 50.0})
    assert resp.status_code == 404


def test_rate_invalid(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/rate", json={"rating": 150.0})
    assert resp.status_code == 422


def test_capabilities(client: TestClient) -> None:
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    assert "generation" in resp.json()


# ── Delete endpoints ─────────────────────────────────────────────────


def test_delete_generation_api(client: TestClient) -> None:
    resp = client.delete("/api/generations/g2")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g2")
    assert resp.status_code == 404


def test_delete_generation_not_found(client: TestClient) -> None:
    resp = client.delete("/api/generations/nonexistent")
    assert resp.status_code == 404


def test_delete_version_keep_gens(client: TestClient) -> None:
    resp = client.delete("/api/versions/v1?delete_generations=false")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["version_id"] is None


def test_delete_version_with_gens(client: TestClient) -> None:
    resp = client.delete("/api/versions/v1?delete_generations=true")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 404


# ── Pick endpoints ───────────────────────────────────────────────────


def test_pick_generation_api(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/pick")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is True


def test_pick_replaces_previous(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    client.post("/api/generations/g2/pick")
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is False
    resp = client.get("/api/generations/g2")
    assert resp.json()["is_picked"] is True


def test_unpick_generation_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/generations/g1/unpick")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is False


def test_keep_generation_api(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/keep")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_kept"] is True


def test_unkeep_generation_api(client: TestClient) -> None:
    client.post("/api/generations/g1/keep")
    resp = client.post("/api/generations/g1/unkeep")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_kept"] is False


def test_unarchive_generation_api(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    from songmaker_cli.db.queries import archive_generation
    with factory() as session:
        archive_generation(session, "g1")
        session.commit()

    resp = client.get("/api/generations/g1")
    assert resp.json()["is_archived"] is True

    resp = client.post("/api/generations/g1/unarchive")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    body = resp.json()
    assert body["is_archived"] is False
    assert body["archived_at"] is None


def test_unarchive_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/unarchive")
    assert resp.status_code == 404


def test_cleanup_album_skips_kept_api(client: TestClient) -> None:
    client.post("/api/generations/g1/keep")
    resp = client.post("/api/albums/rock/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert client.get("/api/generations/g1").status_code == 200


def test_cleanup_album_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/albums/rock/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


def test_cleanup_song_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/songs/s1/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert client.get("/api/generations/g1").status_code == 200
    assert client.get("/api/generations/g2").status_code == 404


def test_cleanup_song_skips_kept(client: TestClient) -> None:
    client.post("/api/generations/g1/keep")
    resp = client.post("/api/songs/s1/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1
    assert client.get("/api/generations/g1").status_code == 200


def test_cleanup_song_not_found(client: TestClient) -> None:
    resp = client.post("/api/songs/nonexistent/cleanup")
    assert resp.status_code == 404


# ── Job endpoints ────────────────────────────────────────────────────


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/jobs/nonexistent")
    assert resp.status_code == 404


# ── Generation params ───────────────────────────────────────────────


def test_create_song_with_generation_params(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bolt", "album_id": "rock",
        "generation_params": {"inference_steps": 50, "shift": 2.0},
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"inference_steps": 50, "shift": 2.0}


def test_create_song_invalid_generation_params(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad", "album_id": "rock",
        "generation_params": {"bad_key": 1},
    })
    assert resp.status_code == 422


def test_update_song_sets_generation_params(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={
        "generation_params": {"guidance_scale": 5.5},
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"guidance_scale": 5.5}


def test_update_song_clears_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"inference_steps": 25},
    })
    resp = client.put("/api/songs/s1", json={
        "generation_params": None,
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] is None


def test_update_song_omit_keeps_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"shift": 4.0},
    })
    resp = client.put("/api/songs/s1", json={"lyrics": "new lyrics"})
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"shift": 4.0}


def test_update_song_invalid_generation_params(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={
        "generation_params": {"typo_key": 1},
    })
    assert resp.status_code == 422


def test_params_only_update_no_new_version(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/versions")
    version_count_before = len(resp.json())
    version_id_before = resp.json()[0]["id"]

    resp = client.get("/api/songs/s1")
    assert len(resp.json()["generations"]) > 0

    client.put("/api/songs/s1", json={
        "generation_params": {"inference_steps": 100},
    })
    resp = client.get("/api/songs/s1/versions")
    assert len(resp.json()) == version_count_before
    assert resp.json()[0]["id"] == version_id_before
    assert resp.json()[0]["generation_params"] == {"inference_steps": 100}


def test_version_includes_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"lm_temperature": 0.5},
    })
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    latest = resp.json()[0]
    assert latest["generation_params"] == {"lm_temperature": 0.5}


# ── Generation defaults ─────────────────────────────────────────────


def test_generation_defaults_roundtrip(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")

    resp = c.get("/api/settings/generation-defaults")
    assert resp.status_code == 200
    assert resp.json() == {}

    resp = c.put("/api/settings/generation-defaults", json={
        "turbo": {"inference_steps": 12},
        "sft": {"inference_steps": 60},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["turbo"] == {"inference_steps": 12}
    assert data["sft"] == {"inference_steps": 60}

    resp = c.get("/api/settings/generation-defaults")
    assert resp.json()["turbo"]["inference_steps"] == 12


def test_generation_defaults_rejects_unknown_keys(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    resp = c.put("/api/settings/generation-defaults", json={"turbo": {"bad_key": 1}})
    assert resp.status_code == 422


# ── 404 error branches ──────────────────────────────────────────────


def test_get_album_not_found(client: TestClient) -> None:
    resp = client.get("/api/albums/nonexistent")
    assert resp.status_code == 404


def test_get_song_not_found(client: TestClient) -> None:
    resp = client.get("/api/songs/nonexistent")
    assert resp.status_code == 404


def test_update_song_not_found(client: TestClient) -> None:
    resp = client.put("/api/songs/nonexistent", json={"lyrics": "x"})
    assert resp.status_code == 404


def test_song_versions_not_found(client: TestClient) -> None:
    resp = client.get("/api/songs/nonexistent/versions")
    assert resp.status_code == 404


def test_delete_version_not_found(client: TestClient) -> None:
    resp = client.delete("/api/versions/nonexistent")
    assert resp.status_code == 404


def test_get_generation_not_found(client: TestClient) -> None:
    resp = client.get("/api/generations/nonexistent")
    assert resp.status_code == 404


def test_pick_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/pick")
    assert resp.status_code == 404


def test_unpick_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/unpick")
    assert resp.status_code == 404


def test_keep_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/keep")
    assert resp.status_code == 404


def test_unkeep_generation_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/unkeep")
    assert resp.status_code == 404


def test_cleanup_album_not_found(client: TestClient) -> None:
    resp = client.post("/api/albums/nonexistent/cleanup")
    assert resp.status_code == 404


def test_rate_generation_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/nonexistent/rate",
        json={"rating": 50},
    )
    assert resp.status_code == 404


# ── Generate + Score endpoints ──────────────────────────────────────


def test_generate_song_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/nonexistent/generate",
        json={"count": 1, "model": "sft"},
    )
    assert resp.status_code == 404


def test_generate_song_no_lyrics(client: TestClient) -> None:
    from songmaker_cli.db.models import Song, Version

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Song(
            id="s_empty", title="Empty", album_id="rock",
        ))
        session.add(Version(
            id="v_empty", song_id="s_empty",
            version_number=1, lyrics="", prompt="",
        ))
        session.commit()

    resp = client.post(
        "/api/songs/s_empty/generate",
        json={"count": 1, "model": "sft"},
    )
    assert resp.status_code == 400


def _mock_worker(mock_pool=None):
    """Context manager that mocks arq pool and worker health for enqueue tests."""
    from contextlib import contextmanager
    from unittest.mock import AsyncMock, patch

    if mock_pool is None:
        mock_pool = AsyncMock()

    @contextmanager
    def _ctx():
        with (
            patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool),
            patch(
                "songmaker_cli.generation_api.is_music_worker_healthy",
                AsyncMock(return_value=True),
            ),
            patch(
                "songmaker_cli.generation_api.is_scoring_worker_healthy",
                AsyncMock(return_value=True),
            ),
            patch(
                "songmaker_cli.generation_api._has_online_acestep_worker",
                AsyncMock(return_value=True),
            ),
        ):
            yield mock_pool

    return _ctx()


def test_generate_song_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 2, "model": "sft"},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()


def test_generate_song_model_accepted(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()
    args = mock_pool.enqueue_job.call_args
    assert args[0][-1] == "sft"


def test_generate_song_passes_model_to_worker(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "turbo"},
        )

    assert resp.status_code == 200
    args = mock_pool.enqueue_job.call_args
    assert args[0][-1] == "turbo"


def test_generate_song_missing_model_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate",
        json={"count": 1},
    )
    assert resp.status_code == 422


def test_generate_song_invalid_model(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate",
        json={"count": 1, "model": "invalid"},
    )
    assert resp.status_code == 422


def test_generate_song_seed_accepted(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "seed": 42, "model": "turbo"},
        )
    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()
    call_args = mock_pool.enqueue_job.call_args[0]
    assert call_args[-2] == 42
    assert call_args[-1] == "turbo"


def test_generate_song_seed_invalid(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate", json={"count": 1, "seed": -2, "model": "sft"},
    )
    assert resp.status_code == 422


# ── Repaint ─────────────────────────────────────────────────────────


def test_repaint_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/repaint", json={
            "src_generation_id": "g1",
            "repainting_start": 0.2,
            "repainting_end": 0.8,
            "model": "sft",
        })

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()
    args = mock_pool.enqueue_job.call_args[0]
    repaint = args[-1]
    assert repaint["repainting_start"] == 0.2
    assert repaint["repainting_end"] == 0.8


def test_repaint_invalid_range(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/repaint", json={
        "src_generation_id": "g1",
        "repainting_start": 0.8,
        "repainting_end": 0.2,
        "model": "sft",
    })
    assert resp.status_code == 400
    assert "repainting_start" in resp.json()["detail"]


def test_repaint_no_audio(client: TestClient) -> None:
    resp = client.post("/api/generations/g2/repaint", json={
        "src_generation_id": "g2",
        "repainting_start": 0.0,
        "repainting_end": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 400
    assert "no audio file" in resp.json()["detail"]


def test_repaint_converts_mp3_to_wav(client: TestClient) -> None:
    from unittest.mock import patch

    audio_dir = Path(client.app.state.ctx.audio_dir)
    mp3_file = audio_dir / "u-test" / "g2.mp3"
    mp3_file.parent.mkdir(parents=True, exist_ok=True)
    mp3_file.write_bytes(b"fake-mp3-data")

    def fake_ffmpeg(cmd, **kwargs):
        wav_out = Path(cmd[-1])
        wav_out.write_bytes(b"RIFF" + b"\x00" * 40)
        return subprocess.CompletedProcess(cmd, 0)

    with (
        _mock_worker() as mock_pool,
        patch("songmaker_cli.generation_api.subprocess.run", side_effect=fake_ffmpeg),
    ):
        resp = client.post("/api/generations/g2/repaint", json={
            "src_generation_id": "g2",
            "repainting_start": 0.0,
            "repainting_end": 0.5,
            "model": "sft",
        })

    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()
    repaint = mock_pool.enqueue_job.call_args[0][-1]
    assert repaint["src_wav_path"].endswith(".wav")


def test_repaint_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/repaint", json={
        "src_generation_id": "nonexistent",
        "repainting_start": 0.0,
        "repainting_end": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 404


def test_repaint_with_lyrics_override(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/repaint", json={
            "src_generation_id": "g1",
            "repainting_start": 0.3,
            "repainting_end": 0.7,
            "lyrics": "new lyrics here",
            "prompt": "jazz ballad",
            "model": "sft",
        })

    assert resp.status_code == 200
    args = mock_pool.enqueue_job.call_args[0]
    repaint = args[-1]
    assert repaint["lyrics"] == "new lyrics here"
    assert repaint["prompt"] == "jazz ballad"


# ── Cover ───────────────────────────────────────────────────────────


def test_cover_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/cover", json={
            "src_generation_id": "g1",
            "audio_cover_strength": 0.7,
            "prompt": "jazz version",
            "model": "sft",
        })

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()
    args = mock_pool.enqueue_job.call_args[0]
    cover = args[-1]
    assert cover["audio_cover_strength"] == 0.7
    assert cover["prompt"] == "jazz version"


def test_cover_no_audio(client: TestClient) -> None:
    resp = client.post("/api/generations/g2/cover", json={
        "src_generation_id": "g2",
        "audio_cover_strength": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 400
    assert "no audio file" in resp.json()["detail"]


def test_cover_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/cover", json={
        "src_generation_id": "nonexistent",
        "audio_cover_strength": 0.5,
        "model": "sft",
    })
    assert resp.status_code == 404


def test_cover_default_strength(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post("/api/generations/g1/cover", json={
            "src_generation_id": "g1",
            "model": "sft",
        })

    assert resp.status_code == 200
    args = mock_pool.enqueue_job.call_args[0]
    cover = args[-1]
    assert cover["audio_cover_strength"] == 0.8


# ── No silent fallbacks: model required across all three endpoints ──


def _no_fallback_endpoint_payloads():
    return [
        ("/api/songs/s1/generate", {"count": 1}),
        ("/api/generations/g1/repaint", {
            "src_generation_id": "g1",
            "repainting_start": 0.1,
            "repainting_end": 0.5,
        }),
        ("/api/generations/g1/cover", {
            "src_generation_id": "g1",
            "audio_cover_strength": 0.5,
        }),
    ]


@pytest.mark.parametrize(
    ("url", "base_payload"), _no_fallback_endpoint_payloads(),
)
def test_endpoint_requires_model(
    client: TestClient, url: str, base_payload: dict,
) -> None:
    resp = client.post(url, json=base_payload)
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("url", "base_payload"), _no_fallback_endpoint_payloads(),
)
def test_endpoint_rejects_unknown_model(
    client: TestClient, url: str, base_payload: dict,
) -> None:
    resp = client.post(url, json={**base_payload, "model": "totally-fake"})
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("url", "base_payload"), _no_fallback_endpoint_payloads(),
)
def test_endpoint_rejects_inactive_model(
    client: TestClient, url: str, base_payload: dict,
) -> None:
    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        before = session.query(AvailableModel).filter_by(id="turbo").one()
        assert before.is_active, "fixture invariant: turbo starts active"
        session.query(AvailableModel).filter_by(id="turbo").update(
            {"is_active": False},
        )
        session.commit()
    resp = client.post(url, json={**base_payload, "model": "turbo"})
    assert resp.status_code == 400
    assert "not currently available" in resp.json()["detail"]


# ── Reference audio upload ──────────────────────────────────────────


def test_upload_reference_audio(client: TestClient) -> None:
    import io
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", io.BytesIO(b"RIFF" + b"\x00" * 200), "audio/wav")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["filename"] == "ref.wav"
    assert data["path"].endswith(".wav")
    assert "refs/" in data["path"]


def test_upload_reference_audio_bad_format(client: TestClient) -> None:
    import io
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.txt", io.BytesIO(b"hello world" * 20), "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported format" in resp.json()["detail"]


def test_upload_reference_audio_too_small(client: TestClient) -> None:
    import io
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", io.BytesIO(b"tiny"), "audio/wav")},
    )
    assert resp.status_code == 400
    assert "too small" in resp.json()["detail"]


def test_generate_song_redis_down(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "songmaker_cli.generation_api.is_music_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.is_scoring_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api._has_online_acestep_worker",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.get_arq_pool",
            side_effect=ConnectionError("redis down"),
        ),
    ):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 503
    assert "Job queue unavailable" in resp.json()["detail"]


def test_score_generation_redis_down(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "songmaker_cli.generation_api.is_music_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.is_scoring_worker_healthy",
            AsyncMock(return_value=True),
        ),
        patch(
            "songmaker_cli.generation_api.get_arq_pool",
            side_effect=ConnectionError("redis down"),
        ),
    ):
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 503
    assert "Job queue unavailable" in resp.json()["detail"]


def test_scoring_schema_endpoint(client: TestClient) -> None:
    from songmaker_cli.scoring.registry import SCORERS

    resp = client.get("/api/scoring/schema")
    assert resp.status_code == 200
    body = resp.json()
    assert "scorers" in body
    returned_names = {s["name"] for s in body["scorers"]}
    assert returned_names == set(SCORERS.keys())

    by_name = {s["name"]: s for s in body["scorers"]}
    assert by_name["audiobox"]["device"] == "gpu"
    assert by_name["audiobox"]["needs_audio"] is False
    assert by_name["lyrical_coherence"]["after_gpu"] is True
    assert "audiobox_enjoyment" in by_name["audiobox"]["output_keys"]
    assert "silence_gaps" in by_name["silence"]["output_keys"]


def test_score_generation_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/nonexistent/score",
        json={},
    )
    assert resp.status_code == 404


def test_score_generation_submits_job(client: TestClient) -> None:
    with _mock_worker() as mock_pool:
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "score"
    mock_pool.enqueue_job.assert_called_once()


# ── Song chat endpoint ──────────────────────────────────────────────


def _mock_acall():
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.text = "Hello from Claude"
    mock_fn = AsyncMock(return_value=mock_response)
    return patch("songmaker_cli.chat_api.acall_claude", mock_fn), mock_fn


def test_song_chat_send(client: TestClient) -> None:
    patcher, mock_fn = _mock_acall()
    with patcher:
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["content"] == "hi"
    assert data["assistant_message"]["role"] == "assistant"
    assert data["assistant_message"]["content"] == "Hello from Claude"


def test_song_chat_multi_turn(client: TestClient) -> None:
    patcher, mock_fn = _mock_acall()
    with patcher:
        client.post("/api/songs/s1/chat", json={"message": "first"})
        client.post("/api/songs/s1/chat", json={"message": "second"})

    last_call = mock_fn.call_args
    messages_arg = last_call.kwargs["messages"]
    assert len(messages_arg) == 3
    assert messages_arg[0]["role"] == "user"
    assert messages_arg[1]["role"] == "assistant"
    assert messages_arg[2]["role"] == "user"


def test_song_chat_history(client: TestClient) -> None:
    patcher, _ = _mock_acall()
    with patcher:
        client.post("/api/songs/s1/chat", json={"message": "hi"})

    resp = client.get("/api/songs/s1/chat")
    assert resp.status_code == 200
    msgs = resp.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_song_chat_clear(client: TestClient) -> None:
    patcher, _ = _mock_acall()
    with patcher:
        client.post("/api/songs/s1/chat", json={"message": "hi"})

    resp = client.delete("/api/songs/s1/chat")
    assert resp.status_code == 200

    history = client.get("/api/songs/s1/chat").json()
    assert len(history["messages"]) == 0


def test_song_chat_attaches_messages_to_active_conversation(
    client: TestClient,
) -> None:
    from songmaker_cli.db.models import ChatMessage, Conversation

    patcher, _ = _mock_acall()
    with patcher:
        r1 = client.post("/api/songs/s1/chat", json={"message": "first"})
        r2 = client.post("/api/songs/s1/chat", json={"message": "second"})
    assert r1.status_code == 200 and r2.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        convs = session.query(Conversation).filter_by(archived_at=None).all()
        assert len(convs) == 1, "expected one active conversation after 2 turns"
        conv_id = convs[0].id
        msgs = (
            session.query(ChatMessage)
            .order_by(ChatMessage.created_at).all()
        )
        # 4 messages (2 user, 2 assistant), every one linked to the same conversation.
        assert len(msgs) == 4
        assert all(m.conversation_id == conv_id for m in msgs)
        assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_song_chat_failure_leaves_no_empty_conversation(
    client: TestClient,
) -> None:
    """Regression guard: Claude failure must not persist an empty
    Conversation row. ``get_or_create_active_conversation`` runs on the
    success path only.
    """
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError
    from songmaker_cli.db.models import Conversation

    mock_acall = AsyncMock(side_effect=UnavailableError("no backend"))
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})
    assert resp.status_code == 503

    factory = client.app.state.ctx.db
    with factory() as session:
        assert session.query(Conversation).count() == 0


def test_song_chat_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError

    mock_acall = AsyncMock(side_effect=UnavailableError("no backend"))
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 503


def test_song_chat_builds_context(client: TestClient) -> None:
    from songmaker_cli.chat_api import CHAT_ROLE

    patcher, mock_fn = _mock_acall()
    with patcher:
        resp = client.post("/api/songs/s1/chat", json={"message": "write a verse"})

    assert resp.status_code == 200
    system_arg = mock_fn.call_args.kwargs["system"]
    assert CHAT_ROLE in system_arg
    messages_arg = mock_fn.call_args.kwargs["messages"]
    user_msg = messages_arg[-1]["content"]
    assert "<song_context>" in user_msg
    assert "Thunder" in user_msg


def test_song_chat_requires_auth(unauthed_client: TestClient) -> None:
    resp = unauthed_client.post("/api/songs/s1/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_get_album(client: TestClient) -> None:
    resp = client.get("/api/albums/rock")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Rock Album"


def test_get_job_found(client: TestClient) -> None:
    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


# ── Album creation ──────────────────────────────────────────────────


def test_create_album(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "New Album", "artist": "Me"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "new-album"
    assert data["title"] == "New Album"
    assert data["artist"] == "Me"


def test_create_album_slugifies_unicode(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "Über Nächte"})
    assert resp.status_code == 200
    assert resp.json()["id"] == "uber-nachte"


def test_create_album_duplicate_gets_suffix(client: TestClient) -> None:
    resp1 = client.post("/api/albums", json={"title": "Dupe"})
    assert resp1.json()["id"] == "dupe"
    resp2 = client.post("/api/albums", json={"title": "Dupe"})
    assert resp2.status_code == 200
    assert resp2.json()["id"] == "dupe-2"


def test_create_album_empty_title(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "  "})
    assert resp.status_code == 422


def test_create_album_slugify_special_chars(client: TestClient) -> None:
    resp = client.post("/api/albums", json={"title": "Don't Stop!"})
    assert resp.status_code == 200
    assert resp.json()["id"] == "don-t-stop"


# ── Song list (summary vs detail) ──────────────────────────────────


def test_list_songs_has_no_generations_field(client: TestClient) -> None:
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert "generations" not in items[0]
    assert items[0]["generation_count"] == 2


def test_get_song_has_generations(client: TestClient) -> None:
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    data = resp.json()
    assert "generations" in data
    assert len(data["generations"]) == 2


def test_get_song_best_scores_from_rated_gen(client: TestClient) -> None:
    from songmaker_cli.db.models import Rating

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Rating(generation_id="g1", rating=80))
        session.commit()

    resp = client.get("/api/songs/s1")
    data = resp.json()
    assert data["best_scores"] is not None
    assert "dynamics" in data["best_scores"]
    assert data["best_rating"] == 80


def test_get_song_best_scores_follow_audiobox_quality_when_unrated(
    client: TestClient,
) -> None:
    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Score(id="aq1", generation_id="g1", scorer="batch",
                          value={"audiobox_quality": 7.0}))
        session.add(Score(id="aq2", generation_id="g2", scorer="batch",
                          value={"audiobox_quality": 8.5}))
        session.commit()

    resp = client.get("/api/songs/s1")
    data = resp.json()
    assert data["best_scores"]["audiobox_quality"] == 8.5


def test_get_song_user_rating_outranks_higher_quality_take(
    client: TestClient,
) -> None:
    from songmaker_cli.db.models import Rating

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        session.add(Score(id="aq2", generation_id="g2", scorer="batch",
                          value={"audiobox_quality": 9.0}))
        session.add(Rating(generation_id="g1", rating=80))
        session.commit()

    resp = client.get("/api/songs/s1")
    data = resp.json()
    assert data["best_rating"] == 80
    assert "audiobox_quality" not in (data["best_scores"] or {})


# ── Ownership / access control ──────────────────────────────────────


def test_user_sees_own_album_only(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    resp = c.get("/api/albums")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == "rock"


def test_user_cannot_see_other_album(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Album(id="other", title="Other", artist="X", created_by="u-other"))
        session.commit()
    resp = c.get("/api/albums/other")
    assert resp.status_code == 404


def test_user_cannot_see_other_song(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Album(id="secret", title="Secret", artist="X", created_by="u-other"))
        session.add(Song(id="s-secret", title="Hidden", album_id="secret", track_number=1))
        session.add(Version(
            id="v-secret", song_id="s-secret", version_number=1,
            lyrics="x", prompt="x",
        ))
        session.commit()
    resp = c.get("/api/songs/s-secret")
    assert resp.status_code == 404


def test_admin_sees_all_albums(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    resp = c.get("/api/albums")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


def test_authed_user_creates_album_with_ownership(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    resp = c.post("/api/albums", json={"title": "My New Album"})
    assert resp.status_code == 200
    from songmaker_cli.db.queries import get_album
    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        album = get_album(session, "my-new-album")
        assert album is not None
        assert album.created_by == "u-test"


def test_job_ownership_blocks_other_user(tmp_path: Path) -> None:
    from songmaker_cli.db.models import User
    from songmaker_cli.db.queries import create_job

    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        other = User(
            id="u-other", username="other", password_hash="unused", role="user",
        )
        session.add(other)
        session.flush()
        job = create_job(session, "generate", user_id="u-other")
        session.commit()
        job_id = job.id

    resp = c.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 404


# ── Job cancellation ────────────────────────────────────────────────


def test_cancel_queued_job(client: TestClient) -> None:
    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_already_completed_job(client: TestClient) -> None:
    from songmaker_cli.db.queries import update_job_status

    with _mock_worker():
        resp = client.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
    job_id = resp.json()["id"]

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        update_job_status(session, job_id, "completed", progress=1.0)
        session.commit()

    resp = client.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 409


def test_cancel_job_not_found(client: TestClient) -> None:
    resp = client.post("/api/jobs/nonexistent/cancel")
    assert resp.status_code == 404


def test_cancel_job_other_user_blocked(tmp_path: Path) -> None:
    from songmaker_cli.db.models import User
    from songmaker_cli.db.queries import create_job

    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        other = User(
            id="u-other", username="other", password_hash="unused", role="user",
        )
        session.add(other)
        session.flush()
        job = create_job(session, "generate", user_id="u-other")
        session.commit()
        job_id = job.id

    resp = c.post(f"/api/jobs/{job_id}/cancel")
    assert resp.status_code == 404


# ── Job SSE streaming ─────────────────────────────────────────────────


def test_stream_job_initial_state(client: TestClient) -> None:
    import json

    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "completed", progress=1.0)
        session.commit()
        job_id = job.id

    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["x-accel-buffering"] == "no"
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    assert len(events) == 1
    assert events[0]["id"] == job_id
    assert events[0]["status"] == "completed"


def test_stream_job_sends_updates(client: TestClient) -> None:
    import json
    import threading

    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        session.commit()
        job_id = job.id

    def _complete_after_delay():
        import time
        time.sleep(0.3)
        with ctx.db() as session:
            update_job_status(session, job_id, "completed", progress=1.0)
            session.commit()

    updater = threading.Thread(target=_complete_after_delay, daemon=True)
    updater.start()

    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    updater.join(timeout=5)

    statuses = [e["status"] for e in events]
    assert "queued" in statuses
    assert "completed" in statuses


def test_stream_job_closes_on_terminal_status(client: TestClient) -> None:
    import json

    from songmaker_cli.db.queries import create_job, update_job_status

    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        job = create_job(session, "generate", user_id=_DEFAULT_USER_ID)
        update_job_status(session, job.id, "failed", error="test error")
        session.commit()
        job_id = job.id

    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))

    assert len(events) == 1
    assert events[0]["status"] == "failed"
    assert events[0]["error"] == "test error"


def test_stream_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/jobs/nonexistent/stream")
    assert resp.status_code == 404


def test_stream_job_auth_required(unauthed_client: TestClient) -> None:
    resp = unauthed_client.get("/api/jobs/some-job/stream")
    assert resp.status_code in (401, 403)


# ── Coverage gap tests ───────────────────────────────────────────────


def test_create_song_gen_param_out_of_range(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Params",
        "album_id": "rock",
        "generation_params": {"inference_steps": 500},
    })
    assert resp.status_code == 422


def test_create_song_gen_param_invalid_infer_method(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Infer",
        "album_id": "rock",
        "generation_params": {"infer_method": "euler"},
    })
    assert resp.status_code == 422


def test_create_song_gen_param_invalid_thinking(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Think",
        "album_id": "rock",
        "generation_params": {"thinking": "not-a-bool"},
    })
    assert resp.status_code == 422


def test_create_song_gen_param_thinking_accepts_bool(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Good Think",
        "album_id": "rock",
        "generation_params": {"thinking": True},
    })
    assert resp.status_code == 200


def test_score_request_invalid_scorer_name(client: TestClient) -> None:
    import pytest

    from songmaker_cli.api_models import ScoreRequest

    with pytest.raises(Exception):
        ScoreRequest(scorers=["nonexistent_scorer"])


def test_generation_params_invalid_infer_method_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import GenerationParams

    with pytest.raises(ValidationError, match="infer_method"):
        GenerationParams(infer_method="euler")


def test_generation_params_invalid_thinking_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import GenerationParams

    with pytest.raises(ValidationError):
        GenerationParams(thinking="not-a-bool")


def test_score_request_invalid_scorer_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import ScoreRequest

    with pytest.raises(ValidationError, match="Unknown scorers"):
        ScoreRequest(scorers=["fake_scorer"])


def test_check_song_access_ownership_denied(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")

    ctx: AppContext = c.app.state.ctx
    with ctx.db() as session:
        session.add(User(
            id="u-other", username="other", password_hash="unused", role="user",
        ))
        session.flush()
        session.add(Album(id="private", title="Private", artist="X", created_by="u-other"))
        session.add(Song(id="s-private", title="Hidden", album_id="private", track_number=1))
        session.commit()

    resp = c.get("/api/songs/s-private/versions")
    assert resp.status_code == 404


def test_create_album_integrity_error(client: TestClient) -> None:
    from unittest.mock import patch

    with patch("songmaker_cli.album_api.unique_album_id", return_value="rock"):
        resp = client.post("/api/albums", json={"title": "Rock Album"})

    assert resp.status_code == 409
    assert "conflict" in resp.json()["detail"].lower()


def test_update_song_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    with patch("songmaker_cli.song_api.update_song", side_effect=ValueError("Song not found")):
        resp = client.put("/api/songs/s1", json={"lyrics": "x"})

    assert resp.status_code == 404


def test_delete_version_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Version not found")
    with patch("songmaker_cli.song_api.delete_version", side_effect=err):
        resp = client.delete("/api/versions/v1")

    assert resp.status_code == 404


def test_delete_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.delete_generation", side_effect=err):
        resp = client.delete("/api/generations/g1")

    assert resp.status_code == 404


def test_pick_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.pick_generation", side_effect=err):
        resp = client.post("/api/generations/g1/pick")

    assert resp.status_code == 404


def test_unpick_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.unpick_generation", side_effect=err):
        resp = client.post("/api/generations/g1/unpick")

    assert resp.status_code == 404


def test_keep_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.keep_generation", side_effect=err):
        resp = client.post("/api/generations/g1/keep")

    assert resp.status_code == 404


def test_unkeep_generation_value_error(client: TestClient) -> None:
    from unittest.mock import patch

    err = ValueError("Generation not found")
    with patch("songmaker_cli.generation_api.unkeep_generation", side_effect=err):
        resp = client.post("/api/generations/g1/unkeep")

    assert resp.status_code == 404


# ── Audit trail tests ────────────────────────────────────────────────


def test_create_album_records_audit(client: TestClient) -> None:
    from songmaker_cli.db.queries import list_audit_log

    client.post("/api/albums", json={"title": "Audited"})
    ctx: AppContext = client.app.state.ctx
    with ctx.db() as session:
        entries = list_audit_log(session)
    assert any(e.action == "create" and e.resource_type == "album" for e in entries)


def test_audit_log_admin_endpoint(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    c.post("/api/albums", json={"title": "Audit Test"})
    resp = c.get("/api/admin/audit-log")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["action"] == "create"
    assert "created_at" in data["items"][0]
    assert data["total"] >= 1


# ── Chat rate limiting ───────────────────────────────────────────────


def test_chat_rate_limit(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RATE_LIMIT_USER", "2")
    monkeypatch.setenv("CHAT_RATE_LIMIT_ADMIN", "300")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    patcher, _ = _mock_acall()
    with patcher:
        for _ in range(2):
            r = client.post("/api/songs/s1/chat", json={"message": "hi"})
            assert r.status_code == 200

        r = client.post("/api/songs/s1/chat", json={"message": "hi"})
        assert r.status_code == 429


# ── Admin rate limits ────────────────────────────────────────────────


def test_admin_has_rate_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_RATE_LIMIT_USER", "3")
    monkeypatch.setenv("GENERATION_RATE_LIMIT_ADMIN", "1")
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()

    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")

    with _mock_worker():
        r = c.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
        assert r.status_code == 200

        r = c.post(
            "/api/songs/s1/generate", json={"count": 1, "model": "sft"},
        )
        assert r.status_code == 429


# ── Body size limit middleware ───────────────────────────────────────


def test_body_size_limit_rejects_large_request(tmp_path: Path) -> None:
    from songmaker_cli.api import router
    from songmaker_cli.middleware.body_size import BodySizeLimitMiddleware

    factory = init_db(tmp_path / "test.db")
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test", "user")
    app.add_middleware(BodySizeLimitMiddleware)
    app.include_router(router)

    tc = TestClient(app)
    large_body = b"x" * 2_000_000
    resp = tc.post(
        "/api/albums",
        content=large_body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


# ── Error sanitization ──────────────────────────────────────────────


def test_sanitize_error_known_type() -> None:
    from songmaker_cli.jobs import _sanitize_error

    assert _sanitize_error(ConnectionError("x")) == "ACE-Step server not reachable"
    assert _sanitize_error(TimeoutError("x")) == "Generation timed out"
    assert _sanitize_error(RuntimeError("x")) == "Internal error during processing"


def test_sanitize_error_unknown_type() -> None:
    from songmaker_cli.jobs import _sanitize_error

    assert _sanitize_error(KeyError("x")) == "An unexpected error occurred"


def test_sanitize_error_generation_setup() -> None:
    from songmaker_cli.jobs import GenerationSetupError, _sanitize_error

    assert _sanitize_error(GenerationSetupError("Song not found")) == "Song not found"


def test_chat_success_finalizes_job(client: TestClient) -> None:
    patcher, _ = _mock_acall()
    with patcher:
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 200

    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").first()
        assert job is not None
        assert job.status == "completed"
        assert job.completed_at is not None


def test_chat_failure_finalizes_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError

    mock_acall = AsyncMock(side_effect=UnavailableError("down"))
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 503

    factory = client.app.state.ctx.db
    with factory() as session:
        job = session.query(Job).filter_by(type="chat").first()
        assert job is not None
        assert job.status == "failed"
        assert job.completed_at is not None


def test_chat_unavailable_hides_details(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    from songmaker_cli.claude.provider import UnavailableError

    err = UnavailableError("Claude CLI error: /home/user/.local/bin...")
    mock_acall = AsyncMock(side_effect=err)
    with patch("songmaker_cli.chat_api.acall_claude", mock_acall):
        resp = client.post("/api/songs/s1/chat", json={"message": "hi"})

    assert resp.status_code == 503
    assert "Claude is currently unavailable" in resp.json()["detail"]
    assert "/home/" not in resp.json()["detail"]


# ── System prompt ──────────────────────────────────────────────────


def test_system_prompt_contains_role_and_structure() -> None:
    from songmaker_cli.chat_api import CHAT_ROLE, STRUCTURAL_PROMPT, SYSTEM_PROMPT

    assert CHAT_ROLE in SYSTEM_PROMPT
    assert STRUCTURAL_PROMPT in SYSTEM_PROMPT


def test_system_prompt_contains_untrusted_data_notice() -> None:
    from songmaker_cli.chat_api import SYSTEM_PROMPT, UNTRUSTED_DATA_NOTICE

    assert UNTRUSTED_DATA_NOTICE in SYSTEM_PROMPT


# ── Pagination ────────────────────────────────────────────────────


def test_list_songs_pagination_offset_limit(client: TestClient) -> None:
    resp = client.get("/api/songs?offset=0&limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1
    assert data["offset"] == 0
    assert data["limit"] == 1


def test_list_songs_offset_beyond_total(client: TestClient) -> None:
    resp = client.get("/api/songs?offset=100")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 0
    assert data["total"] == 1


def test_list_albums_pagination(client: TestClient) -> None:
    resp = client.get("/api/albums?offset=0&limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 1


def test_list_songs_limit_validation(client: TestClient) -> None:
    resp = client.get("/api/songs?limit=0")
    assert resp.status_code == 422

    resp = client.get("/api/songs?limit=999")
    assert resp.status_code == 422

    resp = client.get("/api/songs?offset=-1")
    assert resp.status_code == 422


# ── Default generation config ────────────────────────────────────────


def test_default_config_get_returns_null(client: TestClient) -> None:
    resp = client.get("/api/settings/default-config")
    assert resp.status_code == 200
    assert resp.json()["config"] is None


def test_default_config_set_builtin(client: TestClient) -> None:
    resp = client.put("/api/settings/default-config", json={"config": "sft"})
    assert resp.status_code == 200
    assert resp.json()["config"] == "sft"

    resp = client.get("/api/settings/default-config")
    assert resp.json()["config"] == "sft"


def test_default_config_set_null(client: TestClient) -> None:
    client.put("/api/settings/default-config", json={"config": "turbo"})
    resp = client.put("/api/settings/default-config", json={"config": None})
    assert resp.status_code == 200
    assert resp.json()["config"] is None


def test_default_config_invalid_id(client: TestClient) -> None:
    resp = client.put("/api/settings/default-config", json={"config": "nonexistent-uuid"})
    assert resp.status_code == 400


def test_default_config_set_own_preset(client: TestClient) -> None:
    preset = client.post("/api/settings/presets", json={
        "name": "my config", "model_mode": "sft", "params": {"inference_steps": 50},
    }).json()

    resp = client.put("/api/settings/default-config", json={"config": preset["id"]})
    assert resp.status_code == 200
    assert resp.json()["config"] == preset["id"]


def test_presets_include_shared_flag(client: TestClient) -> None:
    resp = client.get("/api/settings/presets")
    assert resp.status_code == 200
    for p in resp.json():
        assert "is_shared" in p


# ── Available models ─────────────────────────────────────────────────


def test_list_active_models(client: TestClient) -> None:
    resp = client.get("/api/settings/models")
    assert resp.status_code == 200
    models = resp.json()
    active_ids = [m["id"] for m in models]
    assert "sft" in active_ids
    assert "turbo" in active_ids

    by_id = {m["id"]: m for m in models}
    turbo_caps = by_id["turbo"]["capabilities"]
    assert turbo_caps["max_inference_steps"] == 20
    assert "guidance_scale" in turbo_caps["hidden_params"]
    sft_caps = by_id["sft"]["capabilities"]
    assert sft_caps["max_inference_steps"] == 200
    assert sft_caps["hidden_params"] == []
    assert "use_adg" not in sft_caps["hidden_params"]


def test_build_model_response_raises_on_unregistered_model() -> None:
    """If a row in available_models has an id that's not in
    _BUILTIN_DEFAULTS / ACESTEP_PROFILES, that's a registration bug —
    fail loudly instead of silently returning empty defaults."""
    from types import SimpleNamespace

    from songmaker_cli.settings_api import _build_model_response

    fake_model = SimpleNamespace(id="acestep-quantum-v999", is_active=True)
    with pytest.raises(RuntimeError, match="missing from get_builtin_defaults"):
        _build_model_response(fake_model)


def test_create_preset_inactive_model_rejected(client: TestClient) -> None:
    factory = client.app.state.ctx.db
    with factory() as session:
        session.query(AvailableModel).filter_by(id="turbo").update({"is_active": False})
        session.commit()

    resp = client.post("/api/settings/presets", json={
        "name": "turbo test", "model_mode": "turbo", "params": {"inference_steps": 8},
    })
    assert resp.status_code == 400

    with factory() as session:
        session.query(AvailableModel).filter_by(id="turbo").update({"is_active": True})
        session.commit()


# ── Claude model settings ───────────────────────────────────────────


def test_claude_models_get_requires_admin(client: TestClient) -> None:
    resp = client.get("/api/settings/claude-models")
    assert resp.status_code == 403


def test_claude_models_put_requires_admin(client: TestClient) -> None:
    resp = client.put("/api/settings/claude-models", json={
        "chat_model": "claude-sonnet-4-6",
        "scoring_model": "claude-sonnet-4-6",
    })
    assert resp.status_code == 403


def test_claude_models_get_defaults(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    resp = c.get("/api/settings/claude-models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_model"] == "claude-opus-4-6"
    assert data["scoring_model"] == "claude-opus-4-6"
    assert "claude-opus-4-6" in data["allowed_models"]
    assert "claude-sonnet-4-6" in data["allowed_models"]
    assert "claude-haiku-4-5-20251001" in data["allowed_models"]


def test_claude_models_roundtrip(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    resp = c.put("/api/settings/claude-models", json={
        "chat_model": "claude-sonnet-4-6",
        "scoring_model": "claude-haiku-4-5-20251001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_model"] == "claude-sonnet-4-6"
    assert data["scoring_model"] == "claude-haiku-4-5-20251001"

    resp = c.get("/api/settings/claude-models")
    data = resp.json()
    assert data["chat_model"] == "claude-sonnet-4-6"
    assert data["scoring_model"] == "claude-haiku-4-5-20251001"


def test_claude_models_rejects_invalid(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    resp = c.put("/api/settings/claude-models", json={
        "chat_model": "gpt-4",
        "scoring_model": "claude-opus-4-6",
    })
    assert resp.status_code == 400

    resp = c.put("/api/settings/claude-models", json={
        "chat_model": "claude-opus-4-6",
        "scoring_model": "not-a-real-model",
    })
    assert resp.status_code == 400


def test_capabilities_reflects_db_model(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin")
    c.put("/api/settings/claude-models", json={
        "chat_model": "claude-sonnet-4-6",
        "scoring_model": "claude-haiku-4-5-20251001",
    })
    resp = c.get("/api/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_model"] == "claude-sonnet-4-6"
    assert data["scoring_model"] == "claude-haiku-4-5-20251001"


# ── Bulk delete generations ─────────────────────────────────────────


def test_bulk_delete_generations(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1", "g2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    assert client.get("/api/generations/g1").status_code == 404
    assert client.get("/api/generations/g2").status_code == 404


def test_bulk_delete_empty_list(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": []},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0


def test_bulk_delete_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1", "nonexistent"]},
    )
    assert resp.status_code == 404


def test_bulk_delete_other_user(tmp_path: Path) -> None:
    other_user_id = "u-other"

    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.add(User(
            id=other_user_id, username="other_user",
            password_hash="unused", role="user",
        ))
        session.flush()

        album_mine = Album(id="mine", title="My Album", artist="Me", created_by="u-test")
        album_other = Album(
            id="other", title="Other Album", artist="Them", created_by=other_user_id,
        )
        session.add_all([album_mine, album_other])

        song_mine = Song(id="s-mine", title="My Song", album_id="mine", track_number=1)
        song_other = Song(id="s-other", title="Other Song", album_id="other", track_number=1)
        session.add_all([song_mine, song_other])

        ver_mine = Version(id="v-mine", song_id="s-mine", version_number=1, lyrics="a", prompt="b")
        ver_other = Version(
            id="v-other", song_id="s-other", version_number=1, lyrics="c", prompt="d",
        )
        session.add_all([ver_mine, ver_other])

        gen_mine = Generation(
            id="g-mine", song_id="s-mine", version_id="v-mine",
            generation_number=1, mp3_path="mine.mp3",
        )
        gen_other = Generation(
            id="g-other", song_id="s-other", version_id="v-other",
            generation_number=1, mp3_path="other.mp3",
        )
        session.add_all([gen_mine, gen_other])
        session.commit()

    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g-mine", "g-other"]},
    )
    assert resp.status_code == 404

    with factory() as session:
        assert session.query(Generation).filter_by(id="g-mine").first() is not None
        assert session.query(Generation).filter_by(id="g-other").first() is not None


def test_bulk_delete_cleans_up_files(tmp_path: Path) -> None:
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id="u-test", username="test_user",
            password_hash="unused", role="user",
        ))
        session.flush()
        _seed_db(session, owner_id="u-test")

    audio_dir = tmp_path / "audio"
    gen_dir = audio_dir / "u-test"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "g1.mp3").write_bytes(b"fake")
    (gen_dir / "g1.wav").write_bytes(b"fake")
    (gen_dir / "g2.mp3").write_bytes(b"fake")

    ctx = AppContext(
        db=factory,
        audio_dir=audio_dir,
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router

    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "test_user", "user")
    app.include_router(router)
    tc = TestClient(app)

    resp = tc.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1", "g2"]},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

    assert not (gen_dir / "g1.mp3").exists()
    assert not (gen_dir / "g1.wav").exists()
    assert not (gen_dir / "g2.mp3").exists()


def test_bulk_delete_requires_auth(unauthed_client: TestClient) -> None:
    resp = unauthed_client.post(
        "/api/generations/bulk-delete",
        json={"generation_ids": ["g1"]},
    )
    assert resp.status_code in (401, 403)
