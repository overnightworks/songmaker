"""Integration tests for the REST API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
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
        mp3_path="u-test/g1.mp3", seed=42,
        generation_params={"bpm": 140},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="u-test/g2.mp3", seed=77,
    )
    session.add_all([gen1, gen2])
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


def test_cleanup_album_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/albums/rock/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


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
        json={"count": 1},
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
        json={"count": 1},
    )
    assert resp.status_code == 400


def test_generate_song_submits_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 2},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_pool.enqueue_job.assert_called_once()


def test_generate_song_model_mismatch(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool),
        patch("songmaker_cli.generation_api.get_active_model", AsyncMock(return_value="sft")),
    ):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "turbo"},
        )

    assert resp.status_code == 409
    assert "turbo" in resp.json()["detail"]
    mock_pool.enqueue_job.assert_not_called()


def test_generate_song_model_unavailable(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool),
        patch("songmaker_cli.generation_api.get_active_model", AsyncMock(return_value=None)),
    ):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 503
    mock_pool.enqueue_job.assert_not_called()


def test_generate_song_model_match(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool),
        patch("songmaker_cli.generation_api.get_active_model", AsyncMock(return_value="sft")),
    ):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1, "model": "sft"},
        )

    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()


def test_generate_song_no_model_skips_check(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1},
        )

    assert resp.status_code == 200
    mock_pool.enqueue_job.assert_called_once()


def test_generate_song_invalid_model(client: TestClient) -> None:
    resp = client.post(
        "/api/songs/s1/generate",
        json={"count": 1, "model": "invalid"},
    )
    assert resp.status_code == 422


def test_generate_song_redis_down(client: TestClient) -> None:
    from unittest.mock import patch

    with patch(
        "songmaker_cli.generation_api.get_arq_pool",
        side_effect=ConnectionError("redis down"),
    ):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 1},
        )

    assert resp.status_code == 503
    assert "Job queue unavailable" in resp.json()["detail"]


def test_score_generation_redis_down(client: TestClient) -> None:
    from unittest.mock import patch

    with patch(
        "songmaker_cli.generation_api.get_arq_pool",
        side_effect=ConnectionError("redis down"),
    ):
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 503
    assert "Job queue unavailable" in resp.json()["detail"]


def test_score_generation_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/nonexistent/score",
        json={},
    )
    assert resp.status_code == 404


def test_score_generation_submits_job(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool):
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "score"
    mock_pool.enqueue_job.assert_called_once()


# ── Chat endpoint ───────────────────────────────────────────────────


def test_chat_success(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    c = _make_authed_client(tmp_path)
    mock_response = MagicMock()
    mock_response.text = "Hello from Claude"

    with patch("songmaker_cli.chat_api.call_claude", return_value=mock_response):
        resp = c.post("/api/chat", json={
            "message": "hi",
            "context": "Song: Test",
        })

    assert resp.status_code == 200
    assert resp.json()["response"] == "Hello from Claude"


def test_chat_unavailable(tmp_path: Path) -> None:
    from unittest.mock import patch

    from songmaker_cli.claude.provider import UnavailableError

    c = _make_authed_client(tmp_path)
    with patch(
        "songmaker_cli.chat_api.call_claude",
        side_effect=UnavailableError("no backend"),
    ):
        resp = c.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 503


def test_chat_with_context(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    c = _make_authed_client(tmp_path)
    mock_response = MagicMock()
    mock_response.text = "Rock on!"

    with patch("songmaker_cli.chat_api.call_claude", return_value=mock_response) as mock_call:
        resp = c.post("/api/chat", json={
            "message": "write a verse",
            "context": "Title: My Song\nLyrics: hello world",
        })

    assert resp.status_code == 200
    prompt_arg = mock_call.call_args.args[0]
    assert "<song_context>" in prompt_arg
    assert "My Song" in prompt_arg
    assert "write a verse" in prompt_arg


def test_chat_default_style(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    from songmaker_cli.chat_api import DEFAULT_CHAT_STYLE

    c = _make_authed_client(tmp_path)
    mock_response = MagicMock()
    mock_response.text = "Hello"

    with patch("songmaker_cli.chat_api.call_claude", return_value=mock_response) as mock_call:
        resp = c.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 200
    system_arg = mock_call.call_args.kwargs["system"]
    assert DEFAULT_CHAT_STYLE in system_arg
    assert "```songmaker" in system_arg


def test_chat_requires_auth(unauthed_client: TestClient) -> None:
    resp = unauthed_client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 401


def test_get_album(client: TestClient) -> None:
    resp = client.get("/api/albums/rock")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Rock Album"


def test_get_job_found(client: TestClient) -> None:
    from unittest.mock import AsyncMock, patch

    mock_pool = AsyncMock()

    with patch("songmaker_cli.generation_api.get_arq_pool", return_value=mock_pool):
        resp = client.post("/api/songs/s1/generate", json={"count": 1})
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


def test_create_song_gen_param_invalid_think_mode(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad Think",
        "album_id": "rock",
        "generation_params": {"think_mode": "invalid"},
    })
    assert resp.status_code == 422


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


def test_generation_params_invalid_think_mode_direct() -> None:
    from pydantic import ValidationError

    from songmaker_cli.api_models import GenerationParams

    with pytest.raises(ValidationError, match="think_mode"):
        GenerationParams(think_mode="invalid")


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


def test_chat_rate_limit(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    import songmaker_cli.auth as auth_mod

    original = auth_mod.CHAT_RATE_LIMIT_USER
    auth_mod.CHAT_RATE_LIMIT_USER = 2
    import songmaker_cli.api_helpers as api_mod
    api_mod._RATE_LIMITS["chat"] = (2, 300)

    c = _make_authed_client(tmp_path)
    mock_resp = MagicMock()
    mock_resp.text = "ok"

    try:
        with patch("songmaker_cli.chat_api.call_claude", return_value=mock_resp):
            for _ in range(2):
                r = c.post("/api/chat", json={"message": "hi"})
                assert r.status_code == 200

            r = c.post("/api/chat", json={"message": "hi"})
            assert r.status_code == 429
    finally:
        auth_mod.CHAT_RATE_LIMIT_USER = original
        api_mod._RATE_LIMITS["chat"] = (
            auth_mod.CHAT_RATE_LIMIT_USER, auth_mod.CHAT_RATE_LIMIT_ADMIN,
        )


# ── Admin rate limits ────────────────────────────────────────────────


def test_admin_has_rate_limit(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    import songmaker_cli.api_helpers as api_mod

    original_limits = api_mod._RATE_LIMITS["generate"]
    api_mod._RATE_LIMITS["generate"] = (3, 1)

    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")

    try:
        with patch("songmaker_cli.generation_api.get_arq_pool", return_value=AsyncMock()):
            r = c.post("/api/songs/s1/generate", json={"count": 1})
            assert r.status_code == 200

            r = c.post("/api/songs/s1/generate", json={"count": 1})
            assert r.status_code == 429
    finally:
        api_mod._RATE_LIMITS["generate"] = original_limits


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


def test_chat_unavailable_hides_details(tmp_path: Path) -> None:
    from unittest.mock import patch

    from songmaker_cli.claude.provider import UnavailableError

    c = _make_authed_client(tmp_path)
    with patch(
        "songmaker_cli.chat_api.call_claude",
        side_effect=UnavailableError("Claude CLI error: /home/user/.local/bin..."),
    ):
        resp = c.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 503
    assert "Claude is currently unavailable" in resp.json()["detail"]
    assert "/home/" not in resp.json()["detail"]


# ── System prompt ──────────────────────────────────────────────────


def test_system_prompt_contains_style_and_structure() -> None:
    from songmaker_cli.chat_api import DEFAULT_CHAT_STYLE, STRUCTURAL_PROMPT, SYSTEM_PROMPT

    assert DEFAULT_CHAT_STYLE in SYSTEM_PROMPT
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
