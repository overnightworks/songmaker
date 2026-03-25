"""Integration tests for the REST API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.middleware import AuthenticatedUser


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    reset_engine()
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        _seed_db(session)

    from songmaker_cli.api import router
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    reset_engine()


def _make_authed_client(
    tmp_path: Path, role: str = "user", user_id: str = "u-test",
) -> TestClient:
    """Create a TestClient with a fake authenticated user injected."""
    reset_engine()
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(
            id=user_id, username=f"test_{role}",
            password_hash="unused", role=role,
        ))
        session.flush()
        _seed_db(session, owner_id=user_id if role != "admin" else None)

    from songmaker_cli.api import router

    app = FastAPI()

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            request.state.user = AuthenticatedUser(
                id=user_id, username=f"test_{role}",
                role=role, is_active=True,
            )
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
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
        mp3_path="rock/01_thunder_v1.mp3", seed=42,
        generation_params={"bpm": 140},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="rock/01_thunder_v2.mp3", seed=77,
    )
    session.add_all([gen1, gen2])
    score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 65.0})
    session.add(score)
    session.commit()


def test_list_albums(client: TestClient) -> None:
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_songs(client: TestClient) -> None:
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["generation_count"] == 2


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


def test_rate_by_path(client: TestClient) -> None:
    resp = client.post("/api/rate/rock/01_thunder_v2", json={"rating": 72.0})
    assert resp.status_code == 200


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


def test_generation_defaults_roundtrip(client: TestClient, tmp_path: Path) -> None:
    from songmaker_cli import config as config_mod
    original = config_mod._defaults_path

    config_mod._defaults_path = lambda: tmp_path / "gen_defaults.json"
    try:
        resp = client.get("/api/settings/generation-defaults")
        assert resp.status_code == 200
        assert resp.json() == {}

        resp = client.put("/api/settings/generation-defaults", json={
            "turbo": {"inference_steps": 12},
            "sft": {"inference_steps": 60},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["turbo"] == {"inference_steps": 12}
        assert data["sft"] == {"inference_steps": 60}

        resp = client.get("/api/settings/generation-defaults")
        assert resp.json()["turbo"]["inference_steps"] == 12
    finally:
        config_mod._defaults_path = original


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
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.models import Song, Version

    factory = get_session_factory()
    with factory() as session:
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
    from unittest.mock import MagicMock, patch

    mock_queue = MagicMock()

    with patch("songmaker_cli.api.get_gpu_queue", return_value=mock_queue):
        resp = client.post(
            "/api/songs/s1/generate",
            json={"count": 2},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "generate"
    mock_queue.submit.assert_called_once()


def test_score_generation_not_found(client: TestClient) -> None:
    resp = client.post(
        "/api/generations/nonexistent/score",
        json={},
    )
    assert resp.status_code == 404


def test_score_generation_submits_job(client: TestClient) -> None:
    from unittest.mock import MagicMock, patch

    mock_queue = MagicMock()

    with patch("songmaker_cli.api.get_gpu_queue", return_value=mock_queue):
        resp = client.post(
            "/api/generations/g1/score",
            json={},
        )

    assert resp.status_code == 200
    assert resp.json()["type"] == "score"
    mock_queue.submit.assert_called_once()


# ── Chat endpoint ───────────────────────────────────────────────────


def test_chat_success(client: TestClient) -> None:
    from unittest.mock import MagicMock, patch

    mock_response = MagicMock()
    mock_response.text = "Hello from Claude"

    with patch("songmaker_cli.api.call_claude", return_value=mock_response):
        resp = client.post("/api/chat", json={
            "message": "hi",
            "context": "Song: Test",
        })

    assert resp.status_code == 200
    assert resp.json()["response"] == "Hello from Claude"


def test_chat_with_claude_key_header(client: TestClient) -> None:
    from unittest.mock import MagicMock, patch

    mock_response = MagicMock()
    mock_response.text = "ok"

    with patch("songmaker_cli.api.call_claude", return_value=mock_response) as mock:
        resp = client.post(
            "/api/chat",
            json={"message": "hi"},
            headers={"X-Claude-Key": "sk-test-123"},
        )

    assert resp.status_code == 200
    call_kwargs = mock.call_args
    assert call_kwargs[1]["api_key"] == "sk-test-123"


def test_chat_unavailable(client: TestClient) -> None:
    from unittest.mock import patch

    from songmaker_cli.claude.provider import UnavailableError

    with patch(
        "songmaker_cli.api.call_claude",
        side_effect=UnavailableError("no backend"),
    ):
        resp = client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 503


def test_get_album(client: TestClient) -> None:
    resp = client.get("/api/albums/rock")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Rock Album"


def test_get_job_found(client: TestClient) -> None:
    from unittest.mock import MagicMock, patch

    mock_queue = MagicMock()

    with patch("songmaker_cli.api.get_gpu_queue", return_value=mock_queue):
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


def test_create_album_duplicate(client: TestClient) -> None:
    client.post("/api/albums", json={"title": "Dupe"})
    resp = client.post("/api/albums", json={"title": "Dupe"})
    assert resp.status_code == 409


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
    data = resp.json()
    assert "generations" not in data[0]
    assert data[0]["generation_count"] == 2


def test_get_song_has_generations(client: TestClient) -> None:
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    data = resp.json()
    assert "generations" in data
    assert len(data["generations"]) == 2


def test_get_song_best_scores_from_rated_gen(client: TestClient) -> None:
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.models import Rating

    factory = get_session_factory()
    with factory() as session:
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
    assert len(resp.json()) == 1
    assert resp.json()[0]["id"] == "rock"


def test_user_cannot_see_other_album(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    from songmaker_cli.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        session.add(User(
            id="u-other", username="other", password_hash="x", role="user",
        ))
        session.flush()
        session.add(Album(id="other", title="Other", artist="X", created_by="u-other"))
        session.commit()
    resp = c.get("/api/albums/other")
    assert resp.status_code == 404
    reset_engine()


def test_user_cannot_see_other_song(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    from songmaker_cli.db.engine import get_session_factory

    factory = get_session_factory()
    with factory() as session:
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
    reset_engine()


def test_admin_sees_all_albums(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="admin", user_id="u-admin")
    resp = c.get("/api/albums")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_authed_user_creates_album_with_ownership(tmp_path: Path) -> None:
    c = _make_authed_client(tmp_path, role="user", user_id="u-test")
    resp = c.post("/api/albums", json={"title": "My New Album"})
    assert resp.status_code == 200
    from songmaker_cli.db.engine import get_session_factory
    from songmaker_cli.db.queries import get_album
    factory = get_session_factory()
    with factory() as session:
        album = get_album(session, "my-new-album")
        assert album is not None
        assert album.created_by == "u-test"
    reset_engine()


